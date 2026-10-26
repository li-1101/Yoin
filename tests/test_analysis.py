import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from yoin.analysis import analyze, check_rules, measure
from yoin.errors import YoinError
from yoin.renderer import render
from yoin.rules import MixingRules, load_rules

from .helpers import recipe, write_library


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.library = write_library(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def mix(self, music_volume):
        data = recipe(layer_id="rain")
        data["layers"].append(recipe("stereo", layer_id="music", volume=music_volume)["layers"][0])
        return render(data, self.library, 2)

    def test_quiet_harmony_is_masked_and_raising_it_clears_warning(self):
        quiet = analyze(self.mix(0.03), MixingRules())
        raised = analyze(self.mix(0.4), MixingRules())
        def music_masked(report):
            return any(item["code"] == "masking" and item["layer_ids"][0] == "music" for item in report["advice"])
        self.assertTrue(music_masked(quiet))
        self.assertFalse(music_masked(raised))
        self.assertIn("可能被", " ".join(quiet["warnings"]))

    def test_band_power_integrates_density_and_shares_sum_to_100(self):
        result = self.mix(0.4)
        metrics = measure(result)
        self.assertAlmostEqual(sum(layer["share_pct"] for layer in metrics["layers"]), 100)
        music = metrics["layers"][1]
        band_power = sum(10 ** (value / 10) for value in music["band_db"].values() if value is not None)
        self.assertAlmostEqual(band_power / music["power"], 1, delta=0.05)
        self.assertEqual(metrics["energy_share_basis"], "sum_of_stem_energies")

    def test_disabled_rule_and_severity_do_not_change_measurement(self):
        result = self.mix(0.03)
        metrics = measure(result)
        rules = MixingRules.model_validate({"checks": {"masking": {"enabled": False},
                                                       "dominance": {"severity": "info"}}})
        advice = check_rules(metrics, result.recipe, rules)
        self.assertFalse(any(item["code"] == "masking" for item in advice))
        self.assertEqual(next(item["severity"] for item in advice if item["code"] == "dominance"), "info")
        self.assertEqual(metrics, measure(result))

    def test_layer_count_event_rate_and_stereo_checks(self):
        data = recipe("pulse", events_per_minute=30, pan=-1.0)
        data["layers"].append(recipe(pan=-1.0)["layers"][0])
        report = analyze(render(data, self.library, 2), MixingRules(max_layers=1))
        codes = {item["code"] for item in report["advice"]}
        self.assertTrue({"layer_count", "event_rate", "stereo_imbalance"} <= codes)

    def test_silence_and_one_silent_channel_are_strict_json(self):
        silent = analyze(render(recipe(volume=0), self.library, 1), MixingRules())
        self.assertIsNone(silent["loudness_lufs"])
        self.assertEqual(silent["layers"][0]["share_pct"], 0)
        self.assertEqual(silent["stereo_imbalance_db"], 0)
        json.dumps(silent, allow_nan=False)
        result = render(recipe(), self.library, 1)
        result.audio[:, 1] = 0
        for stem in result.stems.values():
            stem[:, 1] = 0
        one_sided = analyze(result, MixingRules())
        self.assertIsNone(one_sided["stereo_imbalance_db"])
        self.assertEqual(one_sided["silent_channel"], "right")
        self.assertTrue(any(item["code"] == "stereo_imbalance" for item in one_sided["advice"]))
        json.dumps(one_sided, allow_nan=False)

    def test_correlated_layers_still_have_bounded_shares(self):
        data = recipe(layer_id="one")
        data["layers"].append(recipe(layer_id="two")["layers"][0])
        result = render(data, self.library, 1)
        result.stems["two"] = result.stems["one"].copy()
        result.audio = result.stems["one"] + result.stems["two"]
        shares = [layer["share_pct"] for layer in measure(result)["layers"]]
        np.testing.assert_allclose(shares, [50, 50])

    def test_legacy_rules_load_and_invalid_rules_are_chinese(self):
        rules = load_rules(self.root / "mixing_rules.json")
        self.assertTrue(rules.checks.masking.enabled)
        invalid_values = [
            {"target_lufs": 0}, {"target_lufs": float("nan")}, {"masking_db": -1},
            {"bands_hz": {"low": [300, 250]}}, {"checks": {"unknown": {}}},
            {"checks": {"masking": {"enabled": "false"}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            for value in invalid_values:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaisesRegex(YoinError, "混音规则校验失败"):
                        load_rules(path)
