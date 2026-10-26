import copy
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from yoin.config import SAMPLE_RATE
from yoin.errors import YoinError
from yoin.renderer import PEAK_LIMIT, render

from .helpers import recipe, write_library


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.library = write_library(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_mono_pan_left_and_center(self):
        left = render(recipe(pan=-1.0), self.library, 2)
        self.assertLess(float(np.max(np.abs(left.audio[:, 1]))), 1e-7)
        centered = render(recipe(pan=0.0), self.library, 2)
        np.testing.assert_array_equal(centered.audio[:, 0], centered.audio[:, 1])

    def test_stereo_center_preserves_channels_and_right_pan(self):
        center = render(recipe("stereo"), self.library, 2)
        frequencies = np.fft.rfftfreq(len(center.audio), 1 / SAMPLE_RATE)
        peaks = frequencies[np.argmax(np.abs(np.fft.rfft(center.audio, axis=0)), axis=0)]
        np.testing.assert_allclose(peaks, [300, 700], atol=1)
        right = render(recipe("stereo", pan=1.0), self.library, 2)
        self.assertLess(float(np.max(np.abs(right.audio[:, 0]))), 1e-7)

    def test_distance_reduces_energy_and_high_band_before_mastering(self):
        near = render(recipe(distance=0.0), self.library, 3)
        far = render(recipe(distance=1.0), self.library, 3)
        near_raw, far_raw = near.audio / near.master_gain, far.audio / far.master_gain
        self.assertLess(float(np.mean(far_raw**2)), float(np.mean(near_raw**2)) * 0.03)
        frequencies, near_power = signal.welch(near_raw[:, 0], fs=SAMPLE_RATE)
        _, far_power = signal.welch(far_raw[:, 0], fs=SAMPLE_RATE)
        self.assertLess(float(far_power[frequencies > 4000].sum()), float(near_power[frequencies > 4000].sum()) * 0.01)

    def test_same_seed_produces_bit_identical_output_and_stems(self):
        data = recipe()
        data["room"] = {"type": "hall", "amount": 0.3}
        first, second = render(data, self.library, 3), render(data, self.library, 3)
        np.testing.assert_array_equal(first.audio, second.audio)
        np.testing.assert_array_equal(first.stems["mono"], second.stems["mono"])
        data["seed"] += 1
        self.assertFalse(np.array_equal(first.audio, render(data, self.library, 3).audio))

    def test_loop_crossfades_remove_the_ramp_wrap_jump(self):
        result = render(recipe("ramp"), self.library, 6)
        raw = result.audio[:, 0] / result.master_gain
        # 排除滤波器起始瞬态；未淡化的斜坡循环会产生约 0.14 的单采样跳变。
        self.assertLess(float(np.max(np.abs(np.diff(raw[SAMPLE_RATE:])))), 0.0002)

    def test_actual_event_bursts_match_rate(self):
        result = render(recipe("pulse", events_per_minute=6.0, randomness=0.0), self.library, 30)
        envelope = np.max(np.abs(result.audio[:, 0]).reshape(-1, 480), axis=1)
        active = envelope > float(envelope.max()) * 0.01
        starts = int(np.sum(np.diff(np.r_[False, active].astype(int)) == 1))
        self.assertEqual(starts, 3)
        self.assertEqual(len(result.event_times["pulse"]), 3)

    def test_zero_event_rate_and_zero_volume_render_finite_silence(self):
        for data in [recipe("pulse", events_per_minute=0), recipe(volume=0.0)]:
            with self.subTest(recipe=data):
                result = render(data, self.library, 1)
                self.assertFalse(np.any(result.audio))
                self.assertIsNone(result.loudness_lufs)
                self.assertIsNone(result.peak_dbfs)
                self.assertTrue(np.isfinite(result.audio).all())

    def test_extremely_low_event_rate_is_silent_without_overflow(self):
        for rate in [1e-308, 1e-323]:
            with self.subTest(rate=rate):
                result = render(recipe("pulse", events_per_minute=rate), self.library, 1)
                self.assertEqual(result.event_times["pulse"], ())
                self.assertFalse(np.any(result.audio))

    def test_room_contributions_sum_to_mix(self):
        data = recipe(layer_id="rain")
        data["layers"].append(recipe("stereo", layer_id="music")["layers"][0])
        data["room"] = {"type": "wooden_cabin", "amount": 0.5}
        result = render(data, self.library, 2)
        np.testing.assert_allclose(sum(result.stems.values()), result.audio, atol=2e-7)
        self.assertEqual(result.audio.dtype, np.float32)
        self.assertEqual(result.audio.shape, (2 * SAMPLE_RATE, 2))

    def test_loudness_and_peak_limit(self):
        result = render(recipe(), self.library, 3)
        self.assertAlmostEqual(result.loudness_lufs, -24, delta=0.1)
        transient = render(recipe("pulse", events_per_minute=30), self.library, 3, target_lufs=-3)
        self.assertLessEqual(float(np.max(np.abs(transient.audio))), PEAK_LIMIT + 1e-7)
        self.assertAlmostEqual(transient.peak_dbfs, -1, delta=0.01)

    def test_single_layer_volume_is_relative_after_mastering(self):
        quiet = render(recipe(volume=0.3), self.library, 2)
        loud = render(recipe(volume=0.9), self.library, 2)
        self.assertGreater(loud.pre_master_loudness_lufs, quiet.pre_master_loudness_lufs + 10)
        self.assertAlmostEqual(loud.loudness_lufs, quiet.loudness_lufs, delta=0.01)

    def test_streams_are_stable_across_duration_and_unrelated_layers(self):
        data = recipe("pulse", layer_id="accent", events_per_minute=10, randomness=0.8)
        short = render(data, self.library, 6)
        longer_data = copy.deepcopy(data)
        longer_data["layers"].insert(0, recipe(layer_id="bed")["layers"][0])
        longer = render(longer_data, self.library, 8)
        self.assertGreater(len(short.event_times["accent"]), 0)
        expected = tuple(time for time in longer.event_times["accent"] if time < 6)
        self.assertEqual(short.event_times["accent"], expected)
        np.testing.assert_allclose(short.stems["accent"] / short.master_gain,
                                   longer.stems["accent"][:6 * SAMPLE_RATE] / longer.master_gain, atol=1e-7)

    def test_calibration_gain_applies_before_mastering(self):
        baseline = render(recipe(), self.library, 2)
        original = self.library.sounds["mono"].gain_db
        try:
            self.library.sounds["mono"].gain_db = -6
            calibrated = render(recipe(), self.library, 2)
        finally:
            self.library.sounds["mono"].gain_db = original
        self.assertAlmostEqual(calibrated.pre_master_loudness_lufs, baseline.pre_master_loudness_lufs - 6, delta=0.01)

    def test_bad_duration_and_target_are_chinese_errors(self):
        for seconds in [0, 301, 1.5, True]:
            with self.subTest(seconds=seconds), self.assertRaisesRegex(YoinError, "渲染时长必须"):
                render(recipe(), self.library, seconds)
        for target in [float("nan"), float("inf"), 0, True]:
            with self.subTest(target=target), self.assertRaisesRegex(YoinError, "目标响度必须"):
                render(recipe(), self.library, 1, target_lufs=target)

    def test_wrong_sample_rate_and_channel_description_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            library = write_library(Path(directory))
            sf.write(Path(directory) / "mono.wav", np.zeros((1000, 1), dtype=np.float32), 44100)
            with self.assertRaisesRegex(YoinError, "采样率必须"):
                render(recipe(), library, 1)
            sf.write(Path(directory) / "mono.wav", np.zeros((1000, 2), dtype=np.float32), SAMPLE_RATE)
            with self.assertRaisesRegex(YoinError, "声道数与描述不符"):
                render(recipe(), library, 1)
