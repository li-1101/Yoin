"""逐条追加过程记录，保存本轮实际使用的输入和输出。"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import YoinError
from .files import write_json
from .library import SoundLibrary


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


def sound_snapshot(library: SoundLibrary) -> list[dict]:
    assets = []
    for sound in library.sounds.values():
        path = library.root / sound.file
        try:
            with path.open("rb") as file:
                digest = hashlib.file_digest(file, "sha256").hexdigest()
            assets.append({"sound_id": sound.id, "file": sound.file, "sha256": digest})
        except OSError:
            # 未选中的素材缺失不阻止其他素材使用，工具会在实际选用时返回中文错误。
            assets.append({"sound_id": sound.id, "file": sound.file, "sha256": None})
    return assets
