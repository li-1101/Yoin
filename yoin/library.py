"""加载声音资料与音频，素材路径始终相对声音目录文件解析。"""

from dataclasses import dataclass, field
import hashlib
from io import BytesIO
from pathlib import Path

import numpy as np
import soundfile as sf
from pydantic import ValidationError

from .config import SAMPLE_RATE, read_json
from .errors import YoinError
from .schema import Recipe, Sound, chinese_validation_error


@dataclass
class SoundLibrary:
    root: Path
    sounds: dict[str, Sound]
    _audio: dict[str, np.ndarray] = field(default_factory=dict, repr=False)
    _source_bytes: dict[str, bytes | None] = field(default_factory=dict, repr=False)

    def freeze_sources(self) -> list[dict]:
        """固定本轮素材字节，并返回与实际解码同一份字节的 SHA256。"""
        sources = []
        for sound in self.sounds.values():
            if sound.id not in self._source_bytes:
                try:
                    self._source_bytes[sound.id] = (self.root / sound.file).read_bytes()
                except OSError:
                    self._source_bytes[sound.id] = None
            content = self._source_bytes[sound.id]
            sources.append({"sound_id": sound.id, "file": sound.file,
                            "sha256": hashlib.sha256(content).hexdigest() if content is not None else None})
        return sources

    def credits(self, recipe: Recipe) -> str:
        lines = []
        for sound_id in dict.fromkeys(layer.sound_id for layer in recipe.layers):
            sound = self.sounds[sound_id]
            if not sound.placeholder and sound.source:
                lines.append(f"- {sound.name}：{sound.source}；许可：{sound.license}。已进行截取、重采样、滤波或电平调整。")
        return "\n".join(lines)

    def audio(self, sound_id: str) -> np.ndarray:
        if sound_id in self._audio:
            return self._audio[sound_id]
        sound = self.sounds.get(sound_id)
        if sound is None:
            raise YoinError(f"声音不存在：{sound_id}")
        path = self.root / sound.file
        if sound_id in self._source_bytes and self._source_bytes[sound_id] is None:
            raise YoinError(f"本轮开始时无法读取素材『{sound_id}』，请修复文件后重新运行")
        try:
            content = self._source_bytes[sound_id] if sound_id in self._source_bytes else path.read_bytes()
            audio, rate = sf.read(BytesIO(content), dtype="float32", always_2d=True)
        except (OSError, RuntimeError) as exc:
            raise YoinError(f"无法读取声音文件：{path}；请检查路径或先生成占位声音") from exc
        if rate != SAMPLE_RATE:
            raise YoinError(f"声音『{sound_id}』的采样率必须是 {SAMPLE_RATE} Hz，实际为 {rate} Hz")
        channels = 1 if sound.channels == "mono" else 2
        if audio.shape[1] != channels:
            raise YoinError(f"声音『{sound_id}』声道数与描述不符：应为 {channels} 声道")
        if not len(audio) or not np.isfinite(audio).all():
            raise YoinError(f"声音『{sound_id}』必须非空，且不能包含非有限数值")
        audio.flags.writeable = False
        self._source_bytes[sound_id] = content
        self._audio[sound_id] = audio
        return audio


def load_library(path: Path | str) -> SoundLibrary:
    path = Path(path).resolve()
    data = read_json(path)
    if not isinstance(data, list) or not data:
        raise YoinError("声音目录必须是非空的 JSON 数组")
    sounds = {}
    for index, item in enumerate(data):
        try:
            sound = Sound.model_validate(item)
        except ValidationError as exc:
            raise chinese_validation_error(exc, f"第 {index + 1} 项声音描述") from exc
        if sound.id in sounds:
            raise YoinError(f"声音目录存在重复 id：{sound.id}")
        sounds[sound.id] = sound
    return SoundLibrary(path.parent, sounds)
