"""v0 配方参数的标准实现；公式修改时必须更新 RENDERER_VERSION。"""

import hashlib
import math
from dataclasses import dataclass

import numpy as np
import pyloudnorm as pyln
from scipy import signal

from .config import MAX_SECONDS, RENDERER_VERSION, SAMPLE_RATE
from .errors import YoinError
from .library import SoundLibrary
from .schema import Layer, Recipe, validate_recipe

ROOM_SECONDS = {"none": 0.0, "small_room": 0.4, "wooden_cabin": 0.8, "hall": 2.0}
PEAK_LIMIT = 10 ** (-1 / 20)


@dataclass
class RenderResult:
    """stems 含各层混响贡献，并应用与 audio 相同的总线增益。"""

    recipe: Recipe
    audio: np.ndarray
    stems: dict[str, np.ndarray]
    event_times: dict[str, tuple[float, ...]]
    master_gain: float
    pre_master_loudness_lufs: float | None
    pre_master_peak_dbfs: float | None
    loudness_lufs: float | None
    peak_dbfs: float | None
    sample_rate: int = SAMPLE_RATE
    renderer_version: str = RENDERER_VERSION


def _rng(seed: int, namespace: str) -> np.random.Generator:
    # 稳定哈希不依赖 Python 的进程随机化；每层与房间各有独立随机流。
    digest = hashlib.blake2b(f"{seed}:{namespace}".encode(), digest_size=16).digest()
    return np.random.default_rng(int.from_bytes(digest, "little"))


def _loop(source: np.ndarray, frames: int, rng: np.random.Generator) -> np.ndarray:
    fade = min(round(0.5 * SAMPLE_RATE), len(source) // 2)
    cycle = source
    if fade:
        # 在原始素材的首尾做 0.5 秒 cos/sin 等功率交叉淡化，再选择随机起点。
        # 若先 roll 素材，会把原始首尾接缝移到片段中间，遗漏该处的淡化。
        angle = np.linspace(0, np.pi / 2, fade, dtype=np.float32)
        fade_in, fade_out = np.sin(angle), np.cos(angle)
        fade_in[0], fade_in[-1] = 0, 1
        fade_out[0], fade_out[-1] = 1, 0
        crossfade = source[-fade:] * fade_out[:, None] + source[:fade] * fade_in[:, None]
        cycle = np.concatenate((source[fade:-fade], crossfade))
    offset = int(rng.integers(len(cycle)))
    output = np.empty((frames, source.shape[1]), dtype=np.float32)
    written = 0
    while written < frames:
        count = min(len(cycle) - offset, frames - written)
        output[written : written + count] = cycle[offset : offset + count]
        written += count
        offset = 0
    return output


def _events(source: np.ndarray, frames: int, layer: Layer, rng: np.random.Generator):
    output = np.zeros((frames, source.shape[1]), dtype=np.float32)
    times = []
    if layer.events_per_minute == 0:
        return output, ()
    # m = 60 / rate；首个事件 uniform(0,m)，后续间隔 uniform(m(1-.9r),m(1+.9r))。
    interval = 60 / layer.events_per_minute
    spread = 0.9 * layer.randomness
    moment = float(rng.uniform(0, interval))
    while moment < frames / SAMPLE_RATE:
        start = round(moment * SAMPLE_RATE)
        if start < frames:
            count = min(len(source), frames - start)
            output[start : start + count] += source[:count]
            times.append(moment)
        moment += float(rng.uniform(interval * (1 - spread), interval * (1 + spread)))
    return output, tuple(times)


def _process_layer(audio: np.ndarray, layer: Layer, gain_db: float) -> np.ndarray:
    # fc_d = 18000 * (2000/18000)**distance
    # fc_b = 2000 * (16000/2000)**brightness；fc = min(fc_d,fc_b)。
    cutoff = min(
        18_000 * (2_000 / 18_000) ** layer.distance,
        2_000 * (16_000 / 2_000) ** layer.brightness,
    )
    sos = signal.butter(2, cutoff, fs=SAMPLE_RATE, output="sos").astype(np.float32)
    audio = signal.sosfilt(sos, audio, axis=0)
    # g_v = volume**2；距离衰减 -18*distance dB；另乘素材校准增益。
    audio *= np.float32(layer.volume**2 * 10 ** ((gain_db - 18 * layer.distance) / 20))
    angle = (layer.pan + 1) * math.pi / 4
    left, right = math.cos(angle), math.sin(angle)
    if audio.shape[1] == 1:
        # 单声道：L=cos(theta)，R=sin(theta)。
        return audio * np.array([[left, right]], dtype=np.float32)
    # 立体声：左乘 min(1,sqrt(2)*cos(theta))，右乘 min(1,sqrt(2)*sin(theta))。
    audio *= np.array([[min(1, math.sqrt(2) * left), min(1, math.sqrt(2) * right)]], dtype=np.float32)
    return audio


def _room_ir(room_type: str, seed: int) -> np.ndarray:
    seconds = ROOM_SECONDS[room_type]
    frames = round(seconds * SAMPLE_RATE)
    rng = _rng(seed, f"room:{room_type}")
    # 独立左右白噪声 * exp(-6.91*t/T)，各声道归一化到单位能量。
    ir = rng.standard_normal((frames, 2)).astype(np.float32)
    time = np.arange(frames, dtype=np.float32) / SAMPLE_RATE
    ir *= np.exp(-6.91 * time / seconds)[:, None]
    ir /= np.sqrt(np.sum(ir.astype(np.float64) ** 2, axis=0)).astype(np.float32)
    return ir


def _convolve(audio: np.ndarray, ir: np.ndarray) -> np.ndarray:
    # 逐声道卷积，不沿声道轴做卷积；混响尾音截取到请求时长。
    return np.column_stack(
        [signal.fftconvolve(audio[:, channel], ir[:, channel])[: len(audio)] for channel in (0, 1)]
    ).astype(np.float32)


def _peak_dbfs(audio: np.ndarray) -> float | None:
    peak = float(np.max(np.abs(audio)))
    return 20 * math.log10(peak) if peak > 0 else None


def _loudness(meter: pyln.Meter, audio: np.ndarray) -> float | None:
    if not np.any(audio):
        return None
    value = float(meter.integrated_loudness(audio))
    return value if math.isfinite(value) else None


def render(
    recipe: Recipe | dict,
    library: SoundLibrary,
    seconds: int = 30,
    *,
    target_lufs: float = -24.0,
) -> RenderResult:
    """离线渲染，不写文件、不访问模型；响度参数由调用方从规则中读取。"""
    if type(seconds) is not int or not 1 <= seconds <= MAX_SECONDS:
        raise YoinError(f"渲染时长必须是 1–{MAX_SECONDS} 秒的整数")
    if (
        isinstance(target_lufs, bool)
        or not isinstance(target_lufs, (int, float))
        or not math.isfinite(target_lufs)
        or target_lufs >= 0
    ):
        raise YoinError("目标响度必须是小于 0 的有限数值")
    recipe = validate_recipe(recipe, library.sounds)
    frames = seconds * SAMPLE_RATE
    dry_mix = np.zeros((frames, 2), dtype=np.float32)
    reverb_bus = np.zeros_like(dry_mix)
    stems, event_times, sends = {}, {}, {}
    for layer in recipe.layers:
        sound = library.sounds[layer.sound_id]
        source = library.audio(layer.sound_id)
        rng = _rng(recipe.seed, f"layer:{layer.layer_id}")
        if sound.kind == "loop":
            laid_out = _loop(source, frames, rng)
        else:
            laid_out, times = _events(source, frames, layer, rng)
            event_times[layer.layer_id] = times
        track = _process_layer(laid_out, layer, sound.gain_db)
        # send = .05 + .55*distance；所有层送到同一个房间混响。
        send = np.float32(0.05 + 0.55 * layer.distance)
        stems[layer.layer_id], sends[layer.layer_id] = track, send
        dry_mix += track
        reverb_bus += track * send
    if recipe.room.type != "none" and recipe.room.amount > 0:
        ir = _room_ir(recipe.room.type, recipe.seed)
        # 输出 = sum(dry) + amount * convolve(sum(dry*send),IR)。
        dry_mix += np.float32(recipe.room.amount) * _convolve(reverb_bus, ir)
        for layer_id, track in stems.items():
            # 线性混响可分解到各层，方便后续单轨分析或导出。
            wet = _convolve(track * sends[layer_id], ir)
            stems[layer_id] = track + np.float32(recipe.room.amount) * wet
    if not np.isfinite(dry_mix).all():
        raise YoinError("混音包含非有限数值，请降低素材校准增益或检查音频文件")

    meter = pyln.Meter(SAMPLE_RATE)
    pre_loudness = _loudness(meter, dry_mix)
    pre_peak = _peak_dbfs(dry_mix)
    gain = 10 ** ((target_lufs - pre_loudness) / 20) if pre_loudness is not None else 1.0
    peak = float(np.max(np.abs(dry_mix)))
    if peak > 0:
        # 先归一化到 target_lufs，再整体压低到 -1 dBFS；统一为一次标量增益。
        gain = min(gain, PEAK_LIMIT / peak)
    gain32 = np.float32(gain)
    dry_mix *= gain32
    for track in stems.values():
        track *= gain32
    return RenderResult(
        recipe=recipe,
        audio=dry_mix,
        stems=stems,
        event_times=event_times,
        master_gain=float(gain32),
        pre_master_loudness_lufs=pre_loudness,
        pre_master_peak_dbfs=pre_peak,
        loudness_lufs=_loudness(meter, dry_mix),
        peak_dbfs=_peak_dbfs(dry_mix),
    )
