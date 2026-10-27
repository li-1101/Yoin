import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from yoin.agent import run_agent
from yoin.errors import YoinError

from .agent_helpers import ScriptedModel, completion, create_project, function_call, preview, submit
from .helpers import recipe


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        create_project(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def run_model(self, responses):
        model = ScriptedModel(responses)
        final = run_agent("安静地写代码", self.root, model.complete,
                          model_info={"model": "scripted-unit-test"}, final_seconds=1)
        return final, model

    def trace(self, directory):
        return [json.loads(line) for line in (Path(directory) / "trace.jsonl").read_text().splitlines()]

    def test_happy_path_saves_complete_artifacts_and_inputs(self):
        final, model = self.run_model([completion(preview()), completion(submit())])
        directory = Path(final["run_directory"])
        required = ["inputs.json", "trace.jsonl", "iter_1.json", "iter_1.wav", "iter_1.analysis.json",
                    "draft.json", "draft.wav", "final.json", "final.wav", "final.analysis.json", "explanation.md"]
        self.assertTrue(all((directory / name).is_file() for name in required))
        self.assertTrue(final["submitted"])
        self.assertEqual(len(model.requests), 2)
        snapshot = json.loads((directory / "inputs.json").read_text())
        self.assertEqual(snapshot["templates"][0]["id"], "quiet")
        self.assertIn("合作者指导", snapshot["system_prompt"])
        self.assertEqual(len(snapshot["sound_files"][0]["sha256"]), 64)
        self.assertEqual(snapshot["renderer_version"], "yoin-renderer-0.1")
        events = self.trace(directory)
        self.assertTrue({"llm_request", "llm_response", "tool_call", "tool_result", "final"} <= {e["type"] for e in events})
        self.assertTrue(all("timestamp" in event for event in events))
        self.assertEqual(events[-1]["status"], "submitted")
        self.assertEqual(sf.info(directory / "draft.wav").frames, sf.info(directory / "final.wav").frames)

    def test_output_credits_include_used_assets_and_exclude_unused_assets(self):
        catalog_path = self.root / "library.json"
        catalog = json.loads(catalog_path.read_text())
        catalog[0].update(source="Used Author — https://example.com/used", license="CC-BY-4.0")
        catalog[1].update(source="Unused Author — https://example.com/unused", license="CC0")
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        final, _ = self.run_model([completion(preview()), completion(submit())])
        text = Path(final["explanation_file"]).read_text()
        self.assertIn("Used Author", text)
        self.assertNotIn("Unused Author", text)
        self.assertTrue((Path(final["run_directory"]) / "final.credits.md").is_file())

    def test_asset_changes_during_model_request_do_not_change_used_snapshot(self):
        original_hash = hashlib.sha256((self.root / "mono.wav").read_bytes()).hexdigest()
        model = ScriptedModel([completion(preview()), completion(submit())])

        def replace_then_complete(messages, tools):
            sf.write(self.root / "mono.wav", np.zeros((96000, 1), dtype=np.float32), 48000, subtype="FLOAT")
            return model.complete(messages, tools)

        final = run_agent("安静", self.root, replace_then_complete, final_seconds=1)
        inputs = json.loads((Path(final["run_directory"]) / "inputs.json").read_text())
        snapshot = next(item for item in inputs["sound_files"] if item["sound_id"] == "mono")
        self.assertEqual(snapshot["sha256"], original_hash)
        self.assertNotEqual(hashlib.sha256((self.root / "mono.wav").read_bytes()).hexdigest(), original_hash)
        rendered, _ = sf.read(final["audio_file"])
        self.assertTrue(np.any(rendered))

    def test_unavailable_asset_stays_unavailable_within_run(self):
        (self.root / "stereo.wav").unlink()
        model = ScriptedModel([completion(preview(recipe("stereo"))), completion(preview()), completion(submit())])

        def add_then_complete(messages, tools):
            sf.write(self.root / "stereo.wav", np.zeros((96000, 2), dtype=np.float32), 48000, subtype="FLOAT")
            return model.complete(messages, tools)

        final = run_agent("安静", self.root, add_then_complete, final_seconds=1)
        result = next(event["result"] for event in self.trace(final["run_directory"]) if event["type"] == "tool_result")
        self.assertFalse(result["success"])
        self.assertIn("本轮开始时", result["error"])

    def test_warnings_require_real_adjustment_but_can_remain_at_submit(self):
        first = recipe(layer_id="rain")
        first["layers"].append(recipe("stereo", layer_id="music", volume=0.03)["layers"][0])
        changed = json.loads(json.dumps(first))
        changed["layers"][1]["volume"] = 0.04
        final, _ = self.run_model([completion(preview(first)), completion(submit(first, "unchanged")),
                                  completion(preview(changed)), completion(submit(changed))])
        events = self.trace(final["run_directory"])
        results = [e["result"] for e in events if e["type"] == "tool_result"]
        self.assertTrue(results[0]["success"])
        self.assertFalse(results[0]["ok"])
        self.assertFalse(results[1]["success"])
        self.assertIn("参数调整", results[1]["error"])
        self.assertTrue(final["submitted"])
        self.assertTrue(final["revision_attempted"])
        self.assertTrue(final["warnings"])
        self.assertIn("保留的分析建议", Path(final["explanation_file"]).read_text())

    def test_adjusted_final_recipe_can_count_as_revision(self):
        first = recipe(pan=-1.0)
        final_recipe = recipe(pan=0.0)
        final, _ = self.run_model([completion(preview(first)), completion(submit(final_recipe))])
        self.assertTrue(final["submitted"])
        self.assertTrue(final["revision_attempted"])

    def test_title_and_seed_changes_do_not_replace_parameter_adjustment(self):
        first = recipe(pan=-1.0)
        renamed = recipe(pan=-1.0)
        renamed["title"], renamed["seed"] = "只是换名", 999
        final, _ = self.run_model([completion(preview(first)), completion(submit(renamed)),
                                  completion(submit(recipe()))])
        rejected = [event for event in self.trace(final["run_directory"]) if event["type"] == "tool_result"][1]
        self.assertFalse(rejected["result"]["success"])

    def test_bad_json_unknown_sound_and_unknown_tool_are_recoverable(self):
        responses = [completion(function_call("render_and_analyze", "{")),
                     completion(preview(recipe("not_in_catalog"))),
                     completion(function_call("search_sounds", {}), preview(call_id="valid")),
                     completion(submit())]
        final, model = self.run_model(responses)
        results = [event["result"] for event in self.trace(final["run_directory"]) if event["type"] == "tool_result"]
        self.assertTrue(all(not result["success"] for result in results[:3]))
        self.assertEqual(final["preview_count"], 1)
        self.assertEqual(len(model.requests), 4)
        prior = model.requests[-1]["messages"]
        self.assertEqual([message["tool_call_id"] for message in prior if message["role"] == "tool"][-2:], ["call_1", "valid"])

    def test_submit_before_preview_and_english_explanation_are_rejected(self):
        responses = [completion(submit()), completion(preview()),
                     completion(submit(explanation="English only")), completion(submit())]
        final, _ = self.run_model(responses)
        results = [event["result"] for event in self.trace(final["run_directory"]) if event["type"] == "tool_result"]
        self.assertIn("先调用", results[0]["error"])
        self.assertIn("中文", results[2]["error"])
        self.assertTrue(final["submitted"])

    def test_budget_fallback_uses_last_successful_recipe(self):
        final, model = self.run_model([completion(preview())])
        self.assertEqual(len(model.requests), 8)
        self.assertEqual(final["status"], "fallback")
        self.assertIn("未主动提交", final["reason"])
        first, _ = sf.read(Path(final["run_directory"]) / "draft.wav", dtype="float32")
        last, _ = sf.read(Path(final["run_directory"]) / "final.wav", dtype="float32")
        np.testing.assert_array_equal(first, last)

    def test_no_valid_recipe_fails_and_keeps_trace(self):
        model = ScriptedModel([])
        with self.assertRaisesRegex(YoinError, "未产生有效配方"):
            run_agent("安静", self.root, model.complete, final_seconds=1)
        self.assertEqual(len(model.requests), 8)
        directory = next((self.root / "runs").iterdir())
        self.assertEqual(self.trace(directory)[-1]["status"], "failed")
        self.assertFalse((directory / "final.wav").exists())

    def test_service_failure_after_preview_falls_back(self):
        final, _ = self.run_model([completion(preview()), YoinError("模型请求超时")])
        self.assertFalse(final["submitted"])
        self.assertIn("超时", final["reason"])
        self.assertTrue(any(event["type"] == "error" for event in self.trace(final["run_directory"])))

    def test_malformed_response_before_any_recipe_fails_clearly(self):
        model = ScriptedModel([{"choices": []}])
        with self.assertRaisesRegex(YoinError, "结构无效"):
            run_agent("安静", self.root, model.complete, final_seconds=1)
        directory = next((self.root / "runs").iterdir())
        self.assertTrue(any(event["type"] == "llm_response" for event in self.trace(directory)))

    def test_interruption_preserves_trace_with_chinese_failure(self):
        model = ScriptedModel([completion(preview()), KeyboardInterrupt()])
        with self.assertRaisesRegex(YoinError, "用户中断"):
            run_agent("安静", self.root, model.complete, final_seconds=1)
        directory = next((self.root / "runs").iterdir())
        self.assertEqual(self.trace(directory)[-1]["status"], "failed")
        self.assertTrue((directory / "draft.wav").exists())

    def test_batch_after_successful_submit_is_recorded_without_execution(self):
        final, _ = self.run_model([completion(preview()), completion(submit(), preview(call_id="late"))])
        events = self.trace(final["run_directory"])
        last_result = [event for event in events if event["type"] == "tool_result"][-1]
        self.assertEqual(last_result["tool_call_id"], "late")
        self.assertIn("已结束", last_result["result"]["error"])
        self.assertFalse((Path(final["run_directory"]) / "iter_2.wav").exists())

    def test_preview_limit_does_not_spend_more_audio_renders(self):
        responses = [completion(preview(call_id=str(index))) for index in range(5)]
        responses += [completion(submit(recipe(volume=0.7))), completion(submit())]
        final, _ = self.run_model(responses)
        self.assertEqual(final["preview_count"], 4)
        results = [e["result"] for e in self.trace(final["run_directory"]) if e["type"] == "tool_result"]
        self.assertIn("4 次", results[4]["error"])
        self.assertIn("三次修改", results[5]["error"])
        self.assertFalse((Path(final["run_directory"]) / "iter_5.wav").exists())

    def test_provider_reasoning_content_is_echoed_and_full_response_logged(self):
        final, model = self.run_model([completion(preview(), reasoning="兼容服务的推理字段"), completion(submit())])
        assistant = next(message for message in model.requests[1]["messages"] if message["role"] == "assistant")
        self.assertEqual(assistant["reasoning_content"], "兼容服务的推理字段")
        response = next(event["response"] for event in self.trace(final["run_directory"]) if event["type"] == "llm_response")
        self.assertEqual(response["usage"]["total_tokens"], 20)

    def test_changed_guidance_is_loaded_and_invalid_template_fails_before_model(self):
        (self.root / "guidance" / "mixing.md").write_text("新的指导：保留雨声主体。", encoding="utf-8")
        final, model = self.run_model([completion(preview()), completion(submit())])
        self.assertIn("新的指导", model.requests[0]["messages"][0]["content"])
        (self.root / "templates" / "quiet.recipe.json").write_text(json.dumps(recipe("missing")), encoding="utf-8")
        bad_model = ScriptedModel([])
        with self.assertRaisesRegex(YoinError, "声音不存在"):
            run_agent("安静", self.root, bad_model.complete, final_seconds=1)
        self.assertEqual(bad_model.requests, [])
