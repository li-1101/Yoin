"""生成七种 CC0 占位声音；不下载素材，不调用模型。"""

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from .cli import ChineseArgumentParser, run_cli
from .config import SAMPLE_RATE, project_root, read_json
from .errors import YoinError


def _level(audio: np.ndarray, rms: float) -> np.ndarray:
    audio = audio - np.mean(audio, axis=0)
    energy = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    return (audio * min(rms / energy, 0.8 / peak)).astype(np.float32)


def _colored_noise(frames: int, exponent: float, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal((frames, 2))
    spectrum = np.fft.rfft(white, axis=0)
    frequencies = np.fft.rfftfreq(frames, 1 / SAMPLE_RATE)
    weight = np.zeros_like(frequencies)
    weight[1:] = frequencies[1:] ** (-exponent / 2)
    return np.fft.irfft(spectrum * weight[:, None], n=frames, axis=0).astype(np.float32)


def _seamless(audio: np.ndarray) -> np.ndarray:
    # 原素材比目标多 0.5 秒。拼接尾与头，输出在循环边缘保持原有采样连续性。
    fade = round(0.5 * SAMPLE_RATE)
    angle = np.linspace(0, np.pi / 2, fade, dtype=np.float32)
    crossfade = audio[-fade:] * np.cos(angle)[:, None] + audio[:fade] * np.sin(angle)[:, None]
    return np.concatenate((audio[fade:-fade], crossfade)).astype(np.float32)


def _loop_sound(sound_id: str, seconds: int, rng: np.random.Generator) -> np.ndarray:
    frames = round((seconds + 0.5) * SAMPLE_RATE)
    if sound_id == "pad_soft_01":
        time = np.arange(frames, dtype=np.float64) / SAMPLE_RATE
        # C 大三和弦，加缓慢的音量起伏；只模拟柔和铺底，不模拟真实爵士乐。
        left = sum(np.sin(2 * np.pi * frequency * time) for frequency in (261.6256, 329.6276, 391.9954))
        right = sum(np.sin(2 * np.pi * frequency * time + 0.12) for frequency in (261.6256, 329.6276, 391.9954))
        audio = np.column_stack((left, right)) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.08 * time))[:, None]
        rms = 0.06
    else:
        exponent = {"noise_white_01": 0, "rain_pink_01": 1, "rain_brown_01": 2, "roomtone_01": 2}[sound_id]
        audio = _colored_noise(frames, exponent, rng)
        if sound_id == "roomtone_01":
            sos = signal.butter(2, 300, fs=SAMPLE_RATE, output="sos").astype(np.float32)
            audio = signal.sosfilt(sos, audio, axis=0)
        rms = {"noise_white_01": 0.08, "rain_pink_01": 0.10, "rain_brown_01": 0.12, "roomtone_01": 0.012}[sound_id]
    return _level(_seamless(audio.astype(np.float32)), rms)


def _event_sound(sound_id: str, rng: np.random.Generator) -> np.ndarray:
    seconds = 0.06 if sound_id == "tick_soft_01" else 1.5
    time = np.arange(round(seconds * SAMPLE_RATE), dtype=np.float64) / SAMPLE_RATE
    if sound_id == "tick_soft_01":
        audio = rng.standard_normal(len(time)).astype(np.float32)
        sos = signal.butter(2, 2500, fs=SAMPLE_RATE, output="sos").astype(np.float32)
        audio = signal.sosfilt(sos, audio)
        audio *= (np.sin(np.pi * time / seconds) ** 2 * np.exp(-5 * time / seconds)).astype(np.float32)
    else:
        audio = sum(amplitude * np.sin(2 * np.pi * frequency * time) for frequency, amplitude in ((440, 1), (880, 0.4), (1320, 0.1)))
        audio *= np.exp(-6 * time / seconds)
        audio *= np.minimum(time / 0.01, 1) * np.minimum((seconds - time) / 0.05, 1)
    # 不做去均值，避免给短事件首尾引入恒定电平跳变。
    return (audio[:, None] * (0.2 / np.max(np.abs(audio)))).astype(np.float32)


CATALOG = [
    ("noise_white_01", "白噪声（占位）", "持续均匀的嘶嘶声，高频较明显", "loop", ["噪声", "明亮"], False),
    ("rain_pink_01", "细雨（占位）", "均匀的沙沙声，近似中小雨；由粉噪声合成", "loop", ["雨", "均匀"], False),
    ("rain_brown_01", "远雨（占位）", "偏低沉的连续噪声，近似远处大雨或瀑布", "loop", ["雨", "低沉", "远处"], False),
    ("roomtone_01", "房间底噪（占位）", "很轻的低频背景，用于填充安静空间", "loop", ["室内", "底噪"], False),
    ("pad_soft_01", "柔和和弦（占位）", "正弦波 C 大三和弦，音量缓慢起伏；不是爵士乐", "loop", ["和弦", "柔和"], True),
    ("tick_soft_01", "轻短声（占位）", "很短的滤波噪声脉冲，近似轻微翻书或键盘声", "event", ["短声", "轻微"], False),
    ("chime_01", "铃音（占位）", "有明确音高的衰减合成铃音", "event", ["铃声", "清脆"], True),
]


def make_placeholders(root: Path | str, seconds: int = 30, *, force: bool = False) -> Path:
    if type(seconds) is not int or not 30 <= seconds <= 60:
        raise YoinError("占位循环素材长度必须是 30–60 秒的整数")
    root = Path(root)
    catalog_path = root / "library.json"
    sounds = []
    for sound_id, name, description, kind, tags, tonal in CATALOG:
        sounds.append({
            "id": sound_id, "name": name, "description": description,
            "kind": kind, "channels": "stereo" if kind == "loop" else "mono",
            "file": f"sounds/{sound_id}.wav", "tags": tags,
            "mood": ["安静"], "good_for": ["专注"], "placeholder": True,
            "source": "程序生成", "license": "CC0", "gain_db": 0.0,
            "tonal": tonal, "musical_key": "C major" if sound_id == "pad_soft_01" else None,
            "bpm": None,
        })
    existing = []
    if catalog_path.exists():
        try:
            existing = read_json(catalog_path)
        except YoinError:
            if not force:
                raise
        if not isinstance(existing, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in existing):
            if not force:
                raise YoinError("已有声音目录必须是包含 id 的声音数组")
            existing = []
    generated_ids = {sound["id"] for sound in sounds}
    extras = [sound for sound in existing if sound["id"] not in generated_ids]
    existing_generated = [sound for sound in existing if sound["id"] in generated_ids]
    targets = [root / sound["file"] for sound in sounds]
    existing_catalog_changed = bool(existing_generated) and existing_generated != sounds
    if not force and (existing_catalog_changed or any(path.exists() for path in targets)):
        raise YoinError("已有声音目录修改或占位素材已存在；重新生成请使用 --force（会覆盖同名文件）")
    (root / "sounds").mkdir(parents=True, exist_ok=True)
    for index, sound in enumerate(sounds):
        rng = np.random.default_rng(2026 + index)
        sound_id, kind = sound["id"], sound["kind"]
        audio = _loop_sound(sound_id, seconds, rng) if kind == "loop" else _event_sound(sound_id, rng)
        path = root / sound["file"]
        try:
            sf.write(path, audio, SAMPLE_RATE, subtype="FLOAT", format="WAV")
        except (RuntimeError, OSError) as exc:
            raise YoinError(f"无法写入占位声音：{path}") from exc
    catalog_path.write_text(json.dumps(sounds + extras, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return catalog_path


def _seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("素材长度必须是整数") from exc
    if not 30 <= seconds <= 60:
        raise argparse.ArgumentTypeError("素材长度必须在 30–60 秒之间")
    return seconds


def main() -> int:
    parser = ChineseArgumentParser(description="生成七种 Yoin 占位声音和 library.json")
    parser.add_argument("--seconds", type=_seconds, default=30, help="循环素材长度，30–60 秒，默认 30")
    parser.add_argument("--force", action="store_true", help="覆盖已有声音目录和同名占位声音")
    args = parser.parse_args()

    def action():
        path = make_placeholders(project_root(), args.seconds, force=args.force)
        print(f"已生成七种占位声音，声音目录：{path}")

    return run_cli(action)


if __name__ == "__main__":
    raise SystemExit(main())
