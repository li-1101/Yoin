"""历史运行、继续调整的基准配方，以及追加式试听评分。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .config import read_json
from .errors import YoinError
from .schema import DataModel, chinese_validation_error, validate_recipe
from .trace import utc_now


class Rating(DataModel):
    which: Literal["draft", "final"]
    score: Annotated[int, Field(ge=1, le=5, strict=True)]
    note: Annotated[str, Field(max_length=2000)] = ""


class RunStore:
    _ratings_lock = threading.Lock()

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.parent = self.root / "runs"

    def directory(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
            raise YoinError("运行编号格式不正确")
        path = self.parent / run_id
        if path.is_symlink() or path.resolve().parent != self.parent.resolve() or not path.is_dir():
            raise YoinError("找不到该运行记录")
        return path

    def events(self, run_id: str) -> list[dict]:
        path = self.directory(run_id) / "trace.jsonl"
        if not path.is_file():
            return []
        events = []
        try:
            with path.open(encoding="utf-8") as file:
                for line in file:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue  # 正在写入的最后一行可能尚未完成。
                    if isinstance(event, dict):
                        events.append(event)
        except (OSError, UnicodeError) as exc:
            raise YoinError("无法读取运行过程记录") from exc
        return events

    def get(self, run_id: str) -> dict:
        directory = self.directory(run_id)
        events = self.events(run_id)
        final = next((event for event in reversed(events) if event.get("type") == "final"), {})
        start = next((event for event in events if event.get("type") == "start"), {})
        snapshot = read_json(directory / "inputs.json") if (directory / "inputs.json").is_file() else {}
        if not isinstance(snapshot, dict):
            raise YoinError("运行快照格式不正确")
        recipe_path = directory / "final.json"
        if not recipe_path.is_file():
            recipe_path = directory / "draft.json"
        recipe = read_json(recipe_path) if recipe_path.is_file() else {}
        if not isinstance(recipe, dict):
            raise YoinError("运行配方格式不正确")
        model = snapshot.get("model", {})
        if not isinstance(model, dict):
            raise YoinError("运行模型资料格式不正确")
        steps = [event.get("step", 0) for event in events if isinstance(event.get("step"), int)]
        status = final.get("status", "unfinished")
        phase = "正在调配声音"
        for event in reversed(events):
            if event.get("type") == "llm_request":
                break
            if event.get("type") == "tool_call":
                phase = "正在生成完整音频" if event.get("name") == "submit_recipe" else "正在渲染与试听"
                break
        if status in {"submitted", "fallback"}:
            phase = "调配完成" if status == "submitted" else "已保留最后有效版本"
        elif status == "failed":
            phase = "本次未完成"
        explanation_path = directory / "explanation.md"
        has_draft = (directory / "draft.wav").is_file() and (directory / "draft.analysis.json").is_file()
        has_final = (directory / "final.wav").is_file() and (directory / "final.analysis.json").is_file()
        can_refine = (status in {"submitted", "fallback"} and has_final) or (status == "failed" and has_draft)
        return {
            "run_id": run_id, "title": recipe.get("title") or start.get("user_request") or "未命名声音",
            "request": start.get("user_request", ""), "created_at": start.get("timestamp", ""),
            "parent_run_id": snapshot.get("parent_run_id"), "status": status, "phase": phase,
            "step": max(steps, default=0), "submitted": final.get("submitted", False),
            "warnings": final.get("warnings", []), "error": final.get("error", ""),
            "has_draft": has_draft, "has_final": has_final, "can_refine": can_refine,
            "explanation": explanation_path.read_text(encoding="utf-8") if explanation_path.is_file() else "",
            "provider": model.get("provider", "api"), "model": model.get("model", "unknown"),
            "scripted": "scripted" in str(model.get("model", "")).lower(),
            "recipe": recipe, "ratings": self.ratings(run_id),
        }

    def list(self, limit: int = 20) -> list[dict]:
        if not self.parent.is_dir():
            return []
        runs = []
        for path in sorted(self.parent.iterdir(), reverse=True):
            if not path.is_dir() or path.is_symlink() or not (path / "trace.jsonl").is_file():
                continue
            try:
                detail = self.get(path.name)
            except (YoinError, OSError, UnicodeError):
                continue
            runs.append({key: detail[key] for key in ("run_id", "title", "created_at", "status", "scripted", "has_final")})
            if len(runs) >= limit:
                break
        return runs

    def recipe(self, run_id: str, sounds):
        detail = self.get(run_id)
        if not detail["can_refine"]:
            raise YoinError("该运行尚无可继续调整的最终结果")
        filename = "final.json" if detail["has_final"] else "draft.json"
        return validate_recipe(read_json(self.directory(run_id) / filename), sounds)

    def ratings(self, run_id: str) -> list[dict]:
        path = self.parent / "ratings.jsonl"
        if not path.is_file():
            return []
        result = []
        with path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    rating = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rating, dict) and rating.get("run_id") == run_id:
                    result.append(rating)
        return result

    def rate(self, run_id: str, data: dict) -> dict:
        try:
            rating = Rating.model_validate(data)
        except ValidationError as exc:
            raise chinese_validation_error(exc, "评分") from exc
        directory = self.directory(run_id)
        if (not (directory / (rating.which + ".wav")).is_file()
                or not (directory / (rating.which + ".analysis.json")).is_file()):
            raise YoinError("所选版本的试听音频不存在或尚未生成完成")
        recipe_path = directory / (rating.which + ".json")
        if not recipe_path.is_file() and rating.which == "draft":
            recipe_path = directory / "iter_1.json"
        snapshot_path = directory / "inputs.json"
        snapshot = read_json(snapshot_path) if snapshot_path.is_file() else {}
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("templates", []), list):
            raise YoinError("运行快照格式不正确")
        if not all(isinstance(template, dict) for template in snapshot.get("templates", [])):
            raise YoinError("运行模板资料格式不正确")
        templates = [{"id": template.get("id"), "sha256": hashlib.sha256(
            json.dumps(template, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
            for template in snapshot.get("templates", [])]
        record = {"timestamp": utc_now(), "run_id": run_id, **rating.model_dump(),
                  "renderer_version": snapshot.get("renderer_version"), "template_context": templates,
                  "recipe_sha256": hashlib.sha256(recipe_path.read_bytes()).hexdigest() if recipe_path.is_file() else None}
        with self._ratings_lock, (self.parent / "ratings.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        return record
