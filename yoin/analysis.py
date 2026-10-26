"""先测量，再按可配置规则给出建议；不判断音乐是否好听。"""

import math

import numpy as np
from scipy import signal

from .levels import loudness_lufs, peak_dbfs
from .renderer import RenderResult
from .rules import FrequencyBands, MixingRules
from .schema import Recipe


def _power_db(power: float) -> float | None:
    return 10 * math.log10(power) if power > 0 else None


def _measure_audio(audio: np.ndarray, sample_rate: int, bands: FrequencyBands) -> dict:
    channel_power = np.einsum("nc,nc->c", audio, audio, dtype=np.float64) / len(audio)
    left, right = map(float, channel_power)
    imbalance = 10 * math.log10(left / right) if left > 0 and right > 0 else None
    silent_channel = "left" if left == 0 < right else "right" if right == 0 < left else None
    if left == right == 0:
        imbalance = 0.0
    frequencies, density = signal.welch(
        audio, fs=sample_rate, nperseg=min(4096, len(audio)),
        scaling="density", detrend=False, axis=0,
    )
    density = density.mean(axis=1)
    resolution = float(frequencies[1] - frequencies[0])
    band_db = {}
    for name, (low, high) in bands.model_dump().items():
        selected = (frequencies >= low) & (frequencies < high)
        # Welch 返回功率密度，积分时必须乘以频率分辨率，才能得到频段功率。
        power = float(np.sum(density[selected], dtype=np.float64)) * resolution
        band_db[name] = _power_db(power)
    return {
        "loudness_lufs": loudness_lufs(audio, sample_rate),
        "peak_dbfs": peak_dbfs(audio),
        "power": (left + right) / 2,
        "channel_power": {"left": left, "right": right},
        "stereo_imbalance_db": imbalance,
        "silent_channel": silent_channel,
        "band_db": band_db,
    }


def measure(result: RenderResult, bands: FrequencyBands | None = None) -> dict:
    """客观测量，不受建议开关、阈值或层角色影响。"""
    bands = bands or FrequencyBands()
    layers = []
    for layer in result.recipe.layers:
        metrics = _measure_audio(result.stems[layer.layer_id], result.sample_rate, bands)
        layers.append({"layer_id": layer.layer_id, "sound_id": layer.sound_id, **metrics})
    total_stem_power = sum(layer["power"] for layer in layers)
    for layer in layers:
        layer["share_pct"] = 100 * layer["power"] / total_stem_power if total_stem_power > 0 else 0.0
    return {
        **_measure_audio(result.audio, result.sample_rate, bands),
        "layers": layers,
        # 相干声音存在交叉项，不能把单轨功率直接除以混音功率，否则占比可能超过 100%。
        "energy_share_basis": "sum_of_stem_energies",
    }


def check_rules(metrics: dict, recipe: Recipe, rules: MixingRules) -> list[dict]:
    """规则只能产生建议，配方是否合法由 schema 决定。"""
    advice = []

    def add(code, layer_ids, message, **evidence):
        options = getattr(rules.checks, code)
        if options.enabled:
            advice.append({"code": code, "severity": options.severity, "layer_ids": layer_ids,
                           "message": message, "evidence": evidence})

    layers = metrics["layers"]
    band_names = {"low": "低频", "mid": "中频", "high": "高频"}
    for layer in layers:
        active_bands = {name: value for name, value in layer["band_db"].items() if value is not None}
        if active_bands:
            band = max(active_bands, key=active_bands.get)
            others = [other for other in layers if other["layer_id"] != layer["layer_id"]
                      and other["band_db"][band] is not None]
            if others:
                strongest = max(others, key=lambda other: other["band_db"][band])
                gap = strongest["band_db"][band] - active_bands[band]
                if gap >= rules.masking_db:
                    add("masking", [layer["layer_id"], strongest["layer_id"]],
                        f"『{layer['layer_id']}』在{band_names[band]}可能被『{strongest['layer_id']}』掩盖（低 {gap:.1f} dB）",
                        band=band, gap_db=gap)
        if len(layers) > 1 and layer["share_pct"] > rules.dominance_share_pct:
            add("dominance", [layer["layer_id"]],
                f"『{layer['layer_id']}』能量占比为 {layer['share_pct']:.1f}%，请结合主体安排检查是否合适",
                share_pct=layer["share_pct"])
    if len(recipe.layers) > rules.max_layers:
        add("layer_count", [], f"当前有 {len(recipe.layers)} 层，超过建议的 {rules.max_layers} 层",
            layer_count=len(recipe.layers))
    for layer in recipe.layers:
        if layer.events_per_minute is not None and layer.events_per_minute > rules.max_event_rate_focus:
            add("event_rate", [layer.layer_id],
                f"『{layer.layer_id}』每分钟 {layer.events_per_minute:g} 次，超过专注场景建议的 {rules.max_event_rate_focus:g} 次",
                events_per_minute=layer.events_per_minute)
    imbalance, silent_channel = metrics["stereo_imbalance_db"], metrics["silent_channel"]
    if silent_channel is not None:
        label = "左" if silent_channel == "left" else "右"
        add("stereo_imbalance", [], f"{label}声道静音，左右能量不平衡", silent_channel=silent_channel)
    elif imbalance is not None and abs(imbalance) > rules.stereo_imbalance_db:
        add("stereo_imbalance", [], f"左右能量差为 {abs(imbalance):.1f} dB，超过建议范围",
            difference_db=imbalance)
    return advice


def analyze(result: RenderResult, rules: MixingRules) -> dict:
    metrics = measure(result, rules.bands_hz)
    advice = check_rules(metrics, result.recipe, rules)
    return {"ok": not advice, **metrics, "warnings": [item["message"] for item in advice], "advice": advice}
