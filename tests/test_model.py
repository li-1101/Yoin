import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import soundfile as sf
import openai

from yoin.agent import run_agent
from yoin.config import ModelConfig
from yoin.errors import YoinError
from yoin.model import ChatModel
from yoin.tools import tool_definitions

from .agent_helpers import completion, create_project, preview, submit
from .fake_provider import LocalProvider
from .helpers import recipe


class ModelTests(unittest.TestCase):
    def test_local_fixture_bypasses_inherited_proxy(self):
        proxy_environment = {name: "http://127.0.0.1:1" for name in
                             ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"]}
        proxy_environment.update({"NO_PROXY": "", "no_proxy": ""})
        with patch.dict(os.environ, proxy_environment), LocalProvider([completion(content="成功")]) as provider:
            with openai.OpenAI(api_key="local-test-key", base_url=provider.url, timeout=1, max_retries=0) as client:
                response = client.chat.completions.create(model="test", messages=[{"role": "user", "content": "测试"}])
            self.assertEqual(response.choices[0].message.content, "成功")
            self.assertEqual(len(provider.requests), 1)

    def test_missing_config_and_invalid_base_url_are_chinese(self):
        with patch.dict(os.environ, {"YOIN_API_KEY": "", "YOIN_BASE_URL": "", "YOIN_MODEL": ""}):
            with self.assertRaisesRegex(YoinError, "缺少模型环境变量.*YOIN_API_KEY"):
                ModelConfig.from_env()
        with patch.dict(os.environ, {"YOIN_API_KEY": "secret", "YOIN_BASE_URL": "ftp://example.com", "YOIN_MODEL": "test"}):
            with self.assertRaisesRegex(YoinError, "有效的 HTTP"):
                ModelConfig.from_env()

    def test_config_repr_and_public_metadata_do_not_expose_credentials(self):
        config = ModelConfig("api-key-secret", "https://user:password@example.com/v1?token=query-secret#fragment", "test")
        public = json.dumps(config.public_info())
        for secret in ["api-key-secret", "password", "query-secret"]:
            self.assertNotIn(secret, public)
            self.assertNotIn(secret, repr(config))
        self.assertEqual(config.public_info()["base_url"], "https://example.com/v1")

    def test_sdk_posts_two_function_tools_and_returns_response(self):
        with LocalProvider([completion(preview())]) as provider:
            model = ChatModel(ModelConfig("local-test-key", provider.url, "local-scripted"))
            try:
                result = model.complete([{"role": "user", "content": "测试"}], tool_definitions())
            finally:
                model.close()
            body = provider.requests[0]
            self.assertEqual(body["model"], "local-scripted")
            self.assertEqual({tool["function"]["name"] for tool in body["tools"]}, {"render_and_analyze", "submit_recipe"})
            self.assertTrue(provider.auth_present[0])
            self.assertEqual(result["choices"][0]["message"]["tool_calls"][0]["id"], "preview")

    def test_sdk_errors_are_chinese_and_do_not_log_provider_secrets(self):
        for status, message in [(401, "认证失败"), (429, "限流"), (500, "HTTP 500")]:
            with self.subTest(status=status), LocalProvider([
                (status, {"error": {"message": "provider-secret-in-body", "type": "error", "code": "error"}})
            ]) as provider:
                model = ChatModel(ModelConfig("local-test-key", provider.url, "local-scripted"))
                try:
                    with self.assertRaisesRegex(YoinError, message) as caught:
                        model.complete([{"role": "user", "content": "测试"}], tool_definitions())
                    self.assertNotIn("provider-secret-in-body", str(caught.exception))
                    self.assertEqual(len(provider.requests), 1)
                finally:
                    model.close()

    def test_sdk_reasoning_field_survives_next_turn(self):
        with tempfile.TemporaryDirectory() as directory, LocalProvider([
            completion(preview(), reasoning="兼容推理字段"), completion(submit()),
        ]) as provider:
            root = Path(directory)
            create_project(root)
            config = ModelConfig("local-test-key", provider.url, "local-scripted")
            model = ChatModel(config)
            try:
                result = run_agent("测试", root, model.complete, model_info=config.public_info(), final_seconds=1)
            finally:
                model.close()
            assistant = next(message for message in provider.requests[1]["messages"] if message["role"] == "assistant")
            self.assertEqual(assistant["reasoning_content"], "兼容推理字段")
            self.assertTrue(result["submitted"])

    def test_cli_end_to_end_saves_default_120_second_draft_and_final(self):
        with tempfile.TemporaryDirectory() as directory, LocalProvider([
            completion(preview(recipe(pan=-1.0))), completion(preview(recipe())), completion(submit()),
        ]) as provider:
            root = Path(directory)
            create_project(root)
            environment = dict(os.environ, YOIN_PROVIDER="api", YOIN_PROJECT_DIR=str(root), YOIN_API_KEY="cli-test-secret",
                               YOIN_BASE_URL=provider.url, YOIN_MODEL="local-scripted-cli")
            process = subprocess.run([sys.executable, "-m", "yoin.run", "安静地写代码"], cwd=root,
                                     env=environment, capture_output=True, text=True, timeout=90)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("模型已提交", process.stdout)
            run_dir = next((root / "runs").iterdir())
            self.assertEqual(sf.info(run_dir / "draft.wav").duration, 120)
            self.assertEqual(sf.info(run_dir / "final.wav").duration, 120)
            self.assertEqual(len(provider.requests), 3)
            final_request = provider.requests[-1]
            results = [json.loads(message["content"]) for message in final_request["messages"] if message["role"] == "tool"]
            self.assertTrue(results[0]["warnings"])
            self.assertTrue(results[1]["revision_attempted"])
            for path in run_dir.iterdir():
                if path.suffix in {".json", ".jsonl", ".md"}:
                    self.assertNotIn("cli-test-secret", path.read_text())

    def test_run_cli_without_config_fails_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, YOIN_PROVIDER="api", YOIN_API_KEY="", YOIN_BASE_URL="", YOIN_MODEL="")
            result = subprocess.run([sys.executable, "-m", "yoin.run", "安静"], cwd=directory,
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertIn("缺少模型环境变量", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
