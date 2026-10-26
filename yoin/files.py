"""输出 JSON 和浮点 WAV，统一目录创建与中文写入错误。"""

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import SAMPLE_RATE
from .errors import YoinError


def write_json(path: Path, data) -> None:
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    except (ValueError, TypeError) as exc:
        raise YoinError(f"输出数据包含不能保存的数值或类型：{path}") from exc
    except OSError as exc:
        raise YoinError(f"无法写入 JSON：{path}") from exc


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, audio, sample_rate, subtype="FLOAT", format="WAV")
    except (OSError, RuntimeError) as exc:
        raise YoinError(f"无法写入 WAV：{path}") from exc
