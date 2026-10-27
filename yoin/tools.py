"""仅开放两个工具，管理试听、修订约束和最终产物。"""

import json
import re
from typing import Annotated

from pydantic import Field, ValidationError, field_validator

from .analysis import analyze
from .config import MAX_PREVIEWS, MAX_SECONDS
from .errors import YoinError
from .files import write_wav
from .library import SoundLibrary
from .renderer import render
from .rules import MixingRules
from .schema import DataModel, Recipe, chinese_validation_error, validate_recipe
from .trace import RunTrace


class RenderArguments(DataModel):
    recipe: Recipe
    seconds: Annotated[int, Field(ge=1, le=MAX_SECONDS, strict=True)] = 30


class SubmitArguments(DataModel):
    recipe: Recipe
    explanation: Annotated[str, Field(min_length=1)]

    @field_validator("explanation")
    @classmethod
    def require_chinese(cls, value):
        if not re.search(r"[\u3400-\u9fff]", value):
            raise ValueError("解释必须包含中文")
        return value


def tool_definitions() -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": "render_and_analyze",
            "description": "校验配方，离线试听并返回测量与中文建议。success 表示成功，ok 仅表示没有建议。",
            "parameters": RenderArguments.model_json_schema(),
        }},
        {"type": "function", "function": {
            "name": "submit_recipe",
            "description": "提交最终配方与中文解释并结束。需先试听；收到建议后至少尝试一次参数调整，允许解释后保留建议。",
            "parameters": SubmitArguments.model_json_schema(),
        }},
    ]


def _mix_signature(recipe: Recipe) -> str:
    # 标题、种子、层命名或单纯换序不能代替一次混音参数调整。
    layers = [layer.model_dump(exclude={"layer_id"}, exclude_none=True) for layer in recipe.layers]
    layers.sort(key=lambda layer: json.dumps(layer, sort_keys=True))
    return json.dumps({"layers": layers, "room": recipe.room.model_dump()}, sort_keys=True)


class ToolSession:
    def __init__(self, library: SoundLibrary, rules: MixingRules, trace: RunTrace, final_seconds: int = 120):
        if type(final_seconds) is not int or not 1 <= final_seconds <= MAX_SECONDS:
            raise YoinError("最终时长必须是 1–300 秒的整数")
        self.library, self.rules, self.trace = library, rules, trace
        self.final_seconds = final_seconds
        self.preview_count = 0
        self.first_recipe: Recipe | None = None
        self.last_recipe: Recipe | None = None
        self.final_data: dict | None = None
        self.revision_attempted = False
        self._warning_signature: str | None = None

    def execute(self, name: str, arguments: str | dict) -> dict:
        if self.final_data is not None:
            return {"success": False, "error": "运行已结束，后续工具不会执行"}
        if name not in {"render_and_analyze", "submit_recipe"}:
            return {"success": False, "error": f"不支持的工具：{name}，只能使用试听或提交工具"}
        try:
            try:
                data = json.loads(arguments) if isinstance(arguments, str) else arguments
            except (ValueError, TypeError) as exc:
                raise YoinError("工具参数必须是有效的 JSON 对象") from exc
            if name == "render_and_analyze":
                return self._preview(RenderArguments.model_validate(data))
            return self._submit(SubmitArguments.model_validate(data))
        except ValidationError as exc:
            return {"success": False, "error": str(chinese_validation_error(exc, "工具参数"))}
        except YoinError as exc:
            return {"success": False, "error": str(exc)}
        except OSError:
            return {"success": False, "error": "无法保存音频或解释，请检查运行目录和磁盘空间"}

    def _render_files(self, recipe: Recipe, basename: str, seconds: int) -> tuple[Recipe, dict]:
        result = render(recipe, self.library, seconds, target_lufs=self.rules.target_lufs)
        report = analyze(result, self.rules)
        self.trace.save_json(basename + ".json", result.recipe.model_dump(exclude_none=True))
        write_wav(self.trace.directory / (basename + ".wav"), result.audio, result.sample_rate)
        self.trace.save_json(basename + ".analysis.json", report)
        credits = self.library.credits(result.recipe)
        if credits:
            (self.trace.directory / (basename + ".credits.md")).write_text(credits + "\n", encoding="utf-8")
        return result.recipe, report

    def _preview(self, args: RenderArguments) -> dict:
        recipe = validate_recipe(args.recipe, self.library.sounds)
        if self.preview_count >= MAX_PREVIEWS:
            raise YoinError("试听次数已达 4 次，请提交已有配方并解释取舍")
        self.preview_count += 1
        basename = f"iter_{self.preview_count}"
        recipe, report = self._render_files(recipe, basename, args.seconds)
        if self.first_recipe is None:
            self._render_files(recipe, "draft", self.final_seconds)
            self.first_recipe = recipe
        signature = _mix_signature(recipe)
        if self._warning_signature is not None and signature != self._warning_signature:
            self.revision_attempted = True
        if report["warnings"] and self._warning_signature is None:
            self._warning_signature = signature
        self.last_recipe = recipe
        return {"success": True, "valid": True, **report,
                "recipe": recipe.model_dump(exclude_none=True),
                "preview_file": str(self.trace.directory / (basename + ".wav")),
                "remaining_previews": MAX_PREVIEWS - self.preview_count,
                "revision_attempted": self.revision_attempted}

    def _submit(self, args: SubmitArguments) -> dict:
        recipe = validate_recipe(args.recipe, self.library.sounds)
        if self.first_recipe is None:
            raise YoinError("提交前必须先调用 render_and_analyze，生成第一版试听")
        if self.preview_count >= MAX_PREVIEWS and _mix_signature(recipe) != _mix_signature(self.last_recipe):
            raise YoinError("试听次数已用完，请提交最后已试听的配方，避免超过三次修改")
        if self._warning_signature is not None and not self.revision_attempted:
            if _mix_signature(recipe) == self._warning_signature:
                raise YoinError("出现混音建议后必须先尝试一次参数调整，再提交并解释取舍")
        final = self.finish(recipe, args.explanation, submitted=True, reason="模型主动提交")
        return {"success": True, "valid": True, **final}

    def finish(self, recipe: Recipe, explanation: str, *, submitted: bool, reason: str) -> dict:
        recipe, report = self._render_files(recipe, "final", self.final_seconds)
        if self._warning_signature is not None and _mix_signature(recipe) != self._warning_signature:
            self.revision_attempted = True
        if report["warnings"]:
            explanation += "\n\n保留的分析建议（不代表配方无效）：\n" + "\n".join("- " + warning for warning in report["warnings"])
        credits = self.library.credits(recipe)
        if credits:
            explanation += "\n\n素材来源与许可：\n" + credits
        (self.trace.directory / "explanation.md").write_text(explanation.rstrip() + "\n", encoding="utf-8")
        self.last_recipe = recipe
        self.final_data = {
            "status": "submitted" if submitted else "fallback", "submitted": submitted,
            "reason": reason, "preview_count": self.preview_count,
            "revision_attempted": self.revision_attempted, "seconds": self.final_seconds,
            "ok": report["ok"], "warnings": report["warnings"],
            "loudness_lufs": report["loudness_lufs"], "peak_dbfs": report["peak_dbfs"],
            "recipe_file": str(self.trace.directory / "final.json"),
            "audio_file": str(self.trace.directory / "final.wav"),
            "explanation_file": str(self.trace.directory / "explanation.md"),
        }
        return self.final_data
