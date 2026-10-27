import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from yoin.codex_model import CodexModel
from yoin.errors import YoinError
from yoin.model import create_model
from yoin.tools import tool_definitions


class CodexModelTests(unittest.TestCase):
    def fake_command(self, command, **kwargs):
        if command[1:3] == ["login", "status"]:
            return subprocess.CompletedProcess(command, 0, "", "Logged in using ChatGPT")
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, "codex-cli test", "")
        result_file = Path(command[command.index("--output-last-message") + 1])
        result_file.write_text(json.dumps({"tool": "render_and_analyze", "arguments_json": '{"recipe": {}}', "content": "先试听"}))
        return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}\n', "")

    def fake_process(self, command, **kwargs):
        result = self.fake_command(command)
        process = Mock()
        process.communicate.return_value = (result.stdout, result.stderr)
        process.returncode = result.returncode
        process.poll.return_value = result.returncode
        self.last_process = process
        return process

    def test_cli_decision_uses_existing_auth_and_maps_to_tool_call(self):
        with patch("shutil.which", return_value="/test/codex"), patch("subprocess.run", side_effect=self.fake_command):
            with patch("subprocess.Popen", side_effect=self.fake_process) as execute:
                with patch.dict(os.environ, {"CODEX_API_KEY": "not-forwarded", "OPENAI_API_KEY": "not-forwarded", "YOIN_CODEX_MODEL": ""}):
                    model = CodexModel()
                    response = model.complete([{"role": "user", "content": "; touch unwanted-file"}], tool_definitions())
        call = response["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "render_and_analyze")
        self.assertEqual(response["usage"]["output_tokens"], 5)
        invocation = execute.call_args
        self.assertNotIn("CODEX_API_KEY", invocation.kwargs["env"])
        self.assertNotIn("OPENAI_API_KEY", invocation.kwargs["env"])
        self.assertIn("; touch unwanted-file", self.last_process.communicate.call_args.args[0])
        self.assertNotIn("; touch unwanted-file", invocation.args[0])
        self.assertIn("read-only", invocation.args[0])
        self.assertEqual(model.public_info()["auth"], "chatgpt")

    def test_cli_missing_login_or_program_is_chinese(self):
        with patch("shutil.which", return_value=None), self.assertRaisesRegex(YoinError, "未找到本机 Codex"):
            CodexModel()
        result = subprocess.CompletedProcess([], 1, "", "not logged in")
        with patch("shutil.which", return_value="/test/codex"), patch("subprocess.run", return_value=result):
            with self.assertRaisesRegex(YoinError, "codex login"):
                CodexModel()

    def test_timeout_and_invalid_decision_do_not_leak_cli_stderr(self):
        with patch("shutil.which", return_value="/test/codex"), patch("subprocess.run", side_effect=self.fake_command):
            model = CodexModel()
        process = Mock(returncode=1)
        process.poll.return_value = 0
        process.communicate.side_effect = [subprocess.TimeoutExpired("codex", 1), ("", "")]
        with patch("subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(YoinError, "超时"):
                model.complete([], tool_definitions())
        process.communicate.side_effect = None
        process.communicate.return_value = ("", "secret-do-not-print")
        with patch("subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(YoinError, "未完成请求") as caught:
                model.complete([], tool_definitions())
            self.assertNotIn("secret-do-not-print", str(caught.exception))
        process.returncode = 0
        process.communicate.return_value = ("", "")
        with patch("subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(YoinError, "有效的工具决策"):
                model.complete([], tool_definitions())

    def test_close_stops_only_the_owned_process_and_prevents_later_requests(self):
        with patch("shutil.which", return_value="/test/codex"), patch("subprocess.run", side_effect=self.fake_command):
            model = CodexModel()
        process = Mock(pid=1234)
        process.poll.return_value = None
        model._process = process
        with patch("os.killpg") as kill:
            model.close()
        kill.assert_called_once_with(1234, 15)
        with patch("subprocess.Popen") as execute, self.assertRaisesRegex(YoinError, "已停止"):
            model.complete([], tool_definitions())
        execute.assert_not_called()

    def test_provider_selection_is_explicit_and_auto_prefers_api_when_configured(self):
        with patch.dict(os.environ, {"YOIN_PROVIDER": "api", "YOIN_API_KEY": "", "YOIN_BASE_URL": "", "YOIN_MODEL": ""}):
            with self.assertRaisesRegex(YoinError, "缺少模型环境变量"):
                create_model()
        with patch.dict(os.environ, {"YOIN_PROVIDER": "auto", "YOIN_API_KEY": "test", "YOIN_BASE_URL": "https://example.com/v1", "YOIN_MODEL": "test"}):
            with patch("yoin.model.ChatModel") as api:
                _, info = create_model()
                self.assertTrue(api.called)
                self.assertEqual(info["provider"], "api")
        with patch.dict(os.environ, {"YOIN_PROVIDER": "codex"}):
            with patch("yoin.codex_model.CodexModel") as local:
                create_model()
                self.assertTrue(local.called)
