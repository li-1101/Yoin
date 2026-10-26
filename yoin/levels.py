"""渲染总线和分析器共用的电平测量，无法测量时返回 None。"""

import math

import numpy as np
import pyloudnorm as pyln

from .config import SAMPLE_RATE


def peak_dbfs(audio: np.ndarray) -> float | None:
    peak = float(np.max(np.abs(audio)))
    return 20 * math.log10(peak) if peak > 0 else None


def loudness_lufs(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float | None:
    if not np.any(audio):
        return None
    # 全部块低于响度门限时，测量库会计算空集合，结果应表示为不可测量。
    with np.errstate(invalid="ignore", divide="ignore"):
        value = float(pyln.Meter(sample_rate).integrated_loudness(audio))
    return value if math.isfinite(value) else None
