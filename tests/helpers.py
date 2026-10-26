"""测试使用确定性的短素材，避免依赖下载和模型。"""

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from yoin.config import SAMPLE_RATE
from yoin.library import load_library


def write_library(root: Path):
    rng = np.random.default_rng(9)
    frames = 2 * SAMPLE_RATE
    time = np.arange(frames) / SAMPLE_RATE
    mono = (0.08 * rng.standard_normal((frames, 1))).astype(np.float32)
    stereo = np.column_stack((0.1 * np.sin(2 * np.pi * 300 * time), 0.1 * np.sin(2 * np.pi * 700 * time))).astype(np.float32)
    pulse_time = np.arange(960) / SAMPLE_RATE
    pulse = (0.1 * np.sin(2 * np.pi * 1000 * pulse_time) * np.hanning(960)).astype(np.float32)[:, None]
    ramp = np.linspace(-0.1, 0.1, frames, dtype=np.float32)[:, None]
    descriptions = []
    for name, audio, kind in [("mono", mono, "loop"), ("stereo", stereo, "loop"), ("pulse", pulse, "event"), ("ramp", ramp, "loop")]:
        sf.write(root / f"{name}.wav", audio, SAMPLE_RATE, subtype="FLOAT")
        descriptions.append({"id": name, "name": name, "description": "测试素材", "kind": kind,
                             "channels": "mono" if audio.shape[1] == 1 else "stereo", "file": f"{name}.wav"})
    (root / "library.json").write_text(json.dumps(descriptions), encoding="utf-8")
    (root / "mixing_rules.json").write_text('{"target_lufs": -24}', encoding="utf-8")
    return load_library(root / "library.json")


def recipe(sound_id="mono", **changes):
    layer = {"sound_id": sound_id, "volume": 0.6, "pan": 0.0, "distance": 0.0, "brightness": 1.0}
    layer.update(changes)
    return {"title": "测试配方", "seed": 17, "layers": [layer], "room": {"type": "none", "amount": 0.0}}
