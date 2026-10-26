import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import soundfile as sf

from .helpers import recipe, write_library


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write_library(self.root)
        self.recipe_path = self.root / "recipe.json"
        self.recipe_path.write_text(json.dumps(recipe()), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, module="yoin.render"):
        environment = dict(os.environ, YOIN_PROJECT_DIR=str(self.root))
        return subprocess.run([sys.executable, "-m", module, *args], cwd=self.root,
                              env=environment, capture_output=True, text=True, timeout=30)

    def test_render_command_from_another_working_directory(self):
        output = self.root / "out" / "mix.wav"
        result = self.call(str(self.recipe_path), "--seconds", "1", "--out", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("已生成", result.stdout)
        info = sf.info(output)
        self.assertEqual((info.duration, info.channels, info.samplerate, info.subtype), (1, 2, 48000, "FLOAT"))

    def test_invalid_recipe_has_chinese_error_without_traceback(self):
        self.recipe_path.write_text('{"bad": 1}', encoding="utf-8")
        result = self.call(str(self.recipe_path), "--out", str(self.root / "out.wav"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("校验失败", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_arguments_have_chinese_errors(self):
        for args in [[], [str(self.recipe_path), "--seconds", "abc", "--out", "out.wav"],
                     [str(self.recipe_path), "--seconds", "0", "--out", "out.wav"]]:
            with self.subTest(args=args):
                result = self.call(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("参数错误", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_cannot_overwrite_source_audio(self):
        before = (self.root / "mono.wav").read_bytes()
        result = self.call(str(self.recipe_path), "--out", str(self.root / "mono.wav"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("不能覆盖声音库素材", result.stderr)
        self.assertEqual(before, (self.root / "mono.wav").read_bytes())

    def test_flag_with_explicit_value_has_chinese_error(self):
        for module, flag in [("yoin.make_placeholders", "--force=true"), ("yoin.render", "--help=true")]:
            with self.subTest(module=module):
                result = self.call(flag, module=module)
                self.assertEqual(result.returncode, 2)
                self.assertIn("此开关不接受值", result.stderr)
                self.assertNotIn("ignored explicit", result.stderr)

    def test_analysis_can_be_saved_and_cannot_overwrite_recipe(self):
        analysis_path = self.root / "analysis.json"
        result = self.call(str(self.recipe_path), "--seconds", "1", "--out", "out.wav", "--analysis", str(analysis_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("advice", json.loads(analysis_path.read_text()))
        before = self.recipe_path.read_bytes()
        rejected = self.call(str(self.recipe_path), "--out", "other.wav", "--analysis", str(self.recipe_path))
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(before, self.recipe_path.read_bytes())
        self.assertFalse((self.root / "other.wav").exists())
