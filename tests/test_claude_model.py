import json
import tempfile
import unittest
from pathlib import Path

from yoin.agent import run_agent
from yoin.connections import ConnectionStore
from yoin.errors import YoinError

from .agent_helpers import create_project, preview, submit
from .fake_provider import LocalProvider


def claude_response(*calls, thinking=False):
    blocks = [{"type": "thinking", "thinking": "fixture", "signature": "fixture-signature"}] if thinking else []
    for call in calls:
        blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                       "input": json.loads(call["function"]["arguments"])})
    return {"id": "msg_fixture", "type": "message", "role": "assistant", "model": "fixture-claude",
            "content": blocks, "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}


class ClaudeModelTests(unittest.TestCase):
    def test_native_tool_round_trip_preserves_system_tools_results_and_thinking(self):
        with tempfile.TemporaryDirectory() as directory, LocalProvider([
            claude_response(preview(), thinking=True), claude_response(submit()),
        ], endpoint="/v1/messages") as provider:
            root = Path(directory)
            create_project(root)
            store = ConnectionStore(root)
            store.save({"provider": "claude", "api_key": "claude-test-private-key", "base_url": provider.url,
                        "model": "fixture-claude"})
            model, info = store.choice("claude").create_model()
            try:
                final = run_agent("安静阅读", root, model.complete, model_info=info, final_seconds=1)
            finally:
                model.close()
            self.assertTrue(final["submitted"])
            self.assertEqual(len(provider.requests), 2)
            first, second = provider.requests
            self.assertIn("合作者指导", first["system"])
            self.assertIn("quiet", first["system"])
            self.assertEqual({tool["name"] for tool in first["tools"]}, {"render_and_analyze", "submit_recipe"})
            self.assertTrue(all(provider.auth_present))
            self.assertEqual(second["messages"][1]["content"][0]["signature"], "fixture-signature")
            returned = second["messages"][2]["content"][0]
            self.assertEqual(returned["type"], "tool_result")
            self.assertEqual(returned["tool_use_id"], "preview")
            self.assertTrue(json.loads(returned["content"])["success"])
            snapshot = json.loads((Path(final["run_directory"]) / "inputs.json").read_text())
            self.assertEqual(snapshot["model"]["provider"], "claude")
            for path in Path(final["run_directory"]).iterdir():
                if path.suffix in {".json", ".jsonl", ".md"}:
                    self.assertNotIn("claude-test-private-key", path.read_text())

    def test_parallel_tool_results_are_merged_in_one_native_user_message(self):
        with tempfile.TemporaryDirectory() as directory, LocalProvider([
            claude_response(preview(call_id="p1"), preview(call_id="p2")), claude_response(submit()),
        ], endpoint="/v1/messages") as provider:
            root = Path(directory)
            create_project(root)
            store = ConnectionStore(root)
            store.save({"provider": "claude", "api_key": "test-key", "base_url": provider.url})
            model, _ = store.choice("claude").create_model()
            try:
                final = run_agent("阅读", root, model.complete, final_seconds=1)
            finally:
                model.close()
            results = provider.requests[1]["messages"][2]["content"]
            self.assertEqual([result["tool_use_id"] for result in results], ["p1", "p2"])
            self.assertTrue(final["submitted"])

    def test_native_errors_do_not_reveal_provider_details(self):
        for status, message in [(401, "认证失败"), (403, "拒绝访问"), (404, "不存在"),
                                (429, "限流"), (500, "HTTP 500")]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory, LocalProvider([
                (status, {"type": "error", "error": {"type": "api_error", "message": "private-provider-detail"}}),
            ], endpoint="/v1/messages") as provider:
                store = ConnectionStore(directory)
                store.save({"provider": "claude", "api_key": "test-key", "base_url": provider.url})
                model, _ = store.choice("claude").create_model()
                try:
                    with self.assertRaisesRegex(YoinError, message) as caught:
                        model.complete([{"role": "user", "content": "测试"}], [])
                    self.assertNotIn("private-provider-detail", str(caught.exception))
                    self.assertEqual(len(provider.requests), 1)
                finally:
                    model.close()


if __name__ == "__main__":
    unittest.main()
