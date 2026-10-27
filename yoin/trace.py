"""逐条追加过程记录，保存本轮实际使用的输入和输出。"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import YoinError
from .files import write_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunTrace:
    directory: Path

    @classmethod
    def create(cls, root: Path):
        parent = root / "runs"
        parent.mkdir(parents=True, exist_ok=True)
        while True:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            directory = parent / run_id
            try:
                directory.mkdir()
                return cls(directory)
            except FileExistsError:
                continue

    def record(self, event_type: str, **data) -> None:
        try:
            line = json.dumps({"type": event_type, "timestamp": utc_now(), **data},
                              ensure_ascii=False, allow_nan=False)
            with (self.directory / "trace.jsonl").open("a", encoding="utf-8") as file:
                file.write(line + "\n")
        except (TypeError, ValueError, OSError) as exc:
            raise YoinError(f"无法保存过程记录：{self.directory}") from exc

    def save_json(self, filename: str, data) -> None:
        write_json(self.directory / filename, data)
