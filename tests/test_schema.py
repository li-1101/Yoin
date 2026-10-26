import copy
import tempfile
import unittest
from pathlib import Path

from yoin.errors import YoinError
from yoin.schema import validate_recipe

from .helpers import recipe, write_library


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.library = write_library(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_legacy_recipe_gets_version_and_stable_ids(self):
        data = recipe()
        data["layers"].append(copy.deepcopy(data["layers"][0]))
        valid = validate_recipe(data, self.library.sounds)
        self.assertEqual(valid.schema_version, 1)
        self.assertEqual([layer.layer_id for layer in valid.layers], ["mono", "mono_2"])
        self.assertNotIn("layer_id", data["layers"][0])

    def test_explicit_ids_are_preserved_and_must_be_unique(self):
        data = recipe(layer_id="rain")
        data["layers"].append(copy.deepcopy(data["layers"][0]))
        with self.assertRaisesRegex(YoinError, "layer_id 必须唯一"):
            validate_recipe(data, self.library.sounds)

    def test_event_defaults_randomness_and_allows_zero(self):
        valid = validate_recipe(recipe("pulse", events_per_minute=0), self.library.sounds)
        self.assertEqual(valid.layers[0].randomness, 0.5)

    def test_event_requires_rate(self):
        with self.assertRaisesRegex(YoinError, "必须填写 events_per_minute"):
            validate_recipe(recipe("pulse"), self.library.sounds)

    def test_loop_rejects_event_fields(self):
        with self.assertRaisesRegex(YoinError, "循环声音.*不能填写"):
            validate_recipe(recipe(events_per_minute=2), self.library.sounds)

    def test_unknown_sound_and_out_of_range_are_chinese(self):
        with self.assertRaisesRegex(YoinError, "声音不存在"):
            validate_recipe(recipe("missing"), self.library.sounds)
        for field, value in [("volume", 1.1), ("pan", -1.1), ("distance", -0.1), ("brightness", 2)]:
            with self.subTest(field=field), self.assertRaisesRegex(YoinError, "校验失败.*必须"):
                validate_recipe(recipe(**{field: value}), self.library.sounds)

    def test_nonfinite_bool_and_unknown_fields_are_rejected(self):
        for value in [float("nan"), float("inf"), True, "0.5"]:
            with self.subTest(value=value), self.assertRaises(YoinError):
                validate_recipe(recipe(volume=value), self.library.sounds)
        data = recipe()
        data["seed"] = True
        with self.assertRaisesRegex(YoinError, "必须是整数"):
            validate_recipe(data, self.library.sounds)
        with self.assertRaisesRegex(YoinError, "不支持此字段"):
            validate_recipe(recipe(surprise=1), self.library.sounds)

    def test_mutated_model_is_revalidated(self):
        valid = validate_recipe(recipe(), self.library.sounds)
        valid.layers[0].volume = 8
        with self.assertRaises(YoinError):
            validate_recipe(valid, self.library.sounds)
