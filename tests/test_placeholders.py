import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from yoin.config import SAMPLE_RATE
from yoin.errors import YoinError
from yoin.library import load_library
from yoin.make_placeholders import make_placeholders


class PlaceholderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        make_placeholders(cls.root)
        cls.library = load_library(cls.root / "library.json")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_catalog_and_files_match(self):
        self.assertEqual(len(self.library.sounds), 7)
        for sound in self.library.sounds.values():
            with self.subTest(sound=sound.id):
                info = sf.info(self.root / sound.file)
                self.assertEqual(info.samplerate, SAMPLE_RATE)
                self.assertEqual(info.subtype, "FLOAT")
                self.assertEqual(info.channels, 2 if sound.kind == "loop" else 1)
                if sound.kind == "loop":
                    self.assertEqual(info.duration, 30)
                self.assertTrue(sound.placeholder)
                self.assertEqual(sound.license, "CC0")
                self.assertTrue(np.isfinite(self.library.audio(sound.id)).all())

    def test_colored_noise_has_expected_spectral_order(self):
        ratios = []
        for sound_id in ["noise_white_01", "rain_pink_01", "rain_brown_01"]:
            audio = self.library.audio(sound_id)[:, 0]
            frequencies, power = signal.welch(audio, fs=SAMPLE_RATE, nperseg=8192)
            low = power[(frequencies >= 50) & (frequencies < 500)].mean()
            high = power[(frequencies >= 4000) & (frequencies < 8000)].mean()
            ratios.append(float(low / high))
        self.assertLess(ratios[0], ratios[1])
        self.assertLess(ratios[1], ratios[2])

    def test_loop_endpoints_do_not_have_an_outlier_jump(self):
        for sound in self.library.sounds.values():
            if sound.kind != "loop":
                continue
            audio = self.library.audio(sound.id)
            nearby = np.concatenate((np.diff(audio[:4800], axis=0), np.diff(audio[-4800:], axis=0)))
            self.assertLessEqual(float(np.max(np.abs(audio[-1] - audio[0]))), float(np.max(np.abs(nearby))) * 4)

    def test_existing_assets_are_not_overwritten_without_force(self):
        before = (self.root / "library.json").read_bytes()
        with self.assertRaisesRegex(YoinError, "已存在"):
            make_placeholders(self.root)
        self.assertEqual(before, (self.root / "library.json").read_bytes())

    def test_tracked_catalog_without_audio_can_be_generated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "library.json").write_bytes((self.root / "library.json").read_bytes())
            make_placeholders(root)
            audio, _ = sf.read(root / "sounds" / "tick_soft_01.wav", dtype="float32")
            np.testing.assert_array_equal(audio, self.library.audio("tick_soft_01")[:, 0])

    def test_wrong_duration_and_malformed_catalog_are_chinese(self):
        with self.assertRaisesRegex(YoinError, "30–60"):
            make_placeholders(self.root, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            path.write_text(json.dumps({"wrong": []}), encoding="utf-8")
            with self.assertRaisesRegex(YoinError, "非空的 JSON 数组"):
                load_library(path)
