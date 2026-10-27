import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from yoin.agent import run_agent
from yoin.errors import YoinError
from yoin.runs import RunStore
from yoin.trace import RunTrace

from .agent_helpers import ScriptedModel, completion, create_project, preview, submit
from .helpers import recipe


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        create_project(self.root)
        model = ScriptedModel([completion(preview()), completion(submit())])
        self.first = run_agent("安静阅读", self.root, model.complete, final_seconds=1,
                               model_info={"model": "scripted-store-test"})
        self.store = RunStore(self.root)
        self.run_id = self.first["run_id"]
        self.directory = Path(self.first["run_directory"])

    def tearDown(self):
        self.temp.cleanup()

    def test_refinement_snapshots_parent_and_passes_base_recipe_without_overwriting(self):
        original = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in self.directory.iterdir()}
        previous = json.loads((self.directory / "final.json").read_text())
        adjusted = copy.deepcopy(previous)
        adjusted["layers"][0]["volume"] = 0.4
        model = ScriptedModel([completion(preview(adjusted)), completion(submit(adjusted))])
        started = []
        final = run_agent("背景轻一点", self.root, model.complete, final_seconds=1,
                          from_run=self.run_id, on_started=started.append)
        snapshot = json.loads((Path(final["run_directory"]) / "inputs.json").read_text())
        self.assertEqual(snapshot["base_recipe"], previous)
        self.assertEqual(snapshot["parent_run_id"], self.run_id)
        prompt = model.requests[0]["messages"][1]["content"]
        self.assertIn("背景轻一点", prompt)
        self.assertIn("保留 seed、layer_id", prompt)
        self.assertIn(previous["layers"][0]["layer_id"], prompt)
        result = self.store.get(final["run_id"])
        self.assertEqual(result["recipe"]["seed"], previous["seed"])
        self.assertEqual(result["recipe"]["layers"][0]["layer_id"], previous["layers"][0]["layer_id"])
        self.assertEqual(started, [Path(final["run_directory"])])
        self.assertEqual(original, {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in self.directory.iterdir()})

    def test_refinement_requires_a_completed_parent_and_never_calls_model_on_error(self):
        (self.directory / "final.analysis.json").unlink()
        model = ScriptedModel([])
        with self.assertRaisesRegex(YoinError, "尚无可继续调整"):
            run_agent("更轻", self.root, model.complete, final_seconds=1, from_run=self.run_id)
        self.assertEqual(model.requests, [])
        self.assertTrue(any(item["status"] == "failed" for item in self.store.list()))

    def test_interrupted_generation_can_continue_from_the_saved_draft(self):
        for filename in ["final.json", "final.wav", "final.analysis.json"]:
            (self.directory / filename).unlink()
        RunTrace(self.directory).record("final", status="failed", error="本地服务中断，初稿已保留")
        self.assertTrue(self.store.get(self.run_id)["can_refine"])
        model = ScriptedModel([completion(preview()), completion(submit())])
        final = run_agent("从初稿继续", self.root, model.complete, final_seconds=1, from_run=self.run_id)
        self.assertTrue(final["submitted"])
        self.assertEqual(self.store.get(final["run_id"])["parent_run_id"], self.run_id)

    def test_rating_is_append_only_with_exact_recipe_and_template_references(self):
        first = self.store.rate(self.run_id, {"which": "draft", "score": 3, "note": "翻页可以少些"})
        second = self.store.rate(self.run_id, {"which": "final", "score": 4})
        self.assertEqual(first["recipe_sha256"], hashlib.sha256((self.directory / "draft.json").read_bytes()).hexdigest())
        self.assertEqual(second["renderer_version"], "yoin-renderer-0.1")
        self.assertEqual(second["template_context"][0]["id"], "quiet")
        self.assertEqual(len(second["template_context"][0]["sha256"]), 64)
        self.assertEqual(self.store.get(self.run_id)["ratings"], [first, second])
        self.assertTrue(self.store.get(self.run_id)["scripted"])

    def test_rating_rejects_invalid_input_and_incomplete_audio(self):
        for data in ({"which": "final", "score": value} for value in [0, 6, True, "4", 2.5]):
            with self.subTest(data=data), self.assertRaises(YoinError):
                self.store.rate(self.run_id, data)
        for data in [{"which": "other", "score": 4}, {"which": "final", "score": 4, "note": "a" * 2001}]:
            with self.assertRaises(YoinError):
                self.store.rate(self.run_id, data)
        (self.directory / "final.analysis.json").unlink()
        self.assertFalse(self.store.get(self.run_id)["has_final"])
        with self.assertRaisesRegex(YoinError, "尚未生成完成"):
            self.store.rate(self.run_id, {"which": "final", "score": 4})
        self.assertFalse((self.root / "runs" / "ratings.jsonl").exists())

    def test_ratings_from_concurrent_requests_remain_complete_json_lines(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(lambda index: self.store.rate(self.run_id, {
                "which": "final", "score": 4, "note": str(index)}), range(12)))
        self.assertEqual(len(self.store.ratings(self.run_id)), 12)
        self.assertEqual({record["note"] for record in records}, {str(index) for index in range(12)})

    def test_run_paths_and_symlinks_are_rejected_and_partial_trace_is_tolerated(self):
        for name in ["../escape", "", "run/child", None]:
            with self.assertRaises(YoinError):
                self.store.directory(name)
        (self.root / "runs" / "alias").symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(YoinError):
            self.store.directory("alias")
        with (self.directory / "trace.jsonl").open("a") as trace:
            trace.write('{"type":')
        self.assertEqual(self.store.get(self.run_id)["status"], "submitted")
        self.assertEqual(len(self.store.list()), 1)

    def test_rating_cli_uses_the_same_store_and_chinese_errors(self):
        environment = {**os.environ, "YOIN_PROJECT_DIR": str(self.root)}
        result = subprocess.run([sys.executable, "-m", "yoin.rate", self.run_id,
                                 "--which", "final", "--score", "5", "--note", "舒服"],
                                env=environment, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.store.ratings(self.run_id)[0]["note"], "舒服")
        bad = subprocess.run([sys.executable, "-m", "yoin.rate", self.run_id, "--score", "6"],
                             env=environment, text=True, capture_output=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("评分必须在", bad.stderr)


if __name__ == "__main__":
    unittest.main()
