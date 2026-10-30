import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from yoin.connections import ConnectionStore
from yoin.errors import YoinError

from .agent_helpers import completion, create_project, function_call, preview, submit
from .fake_provider import LocalProvider


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ConnectionStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_three_profiles_persist_independently_without_public_keys(self):
        self.assertEqual(self.store.public()["active"], "environment")
        self.assertFalse(self.store.path.exists())
        for provider in ["claude", "openai", "deepseek"]:
            self.store.save({"provider": provider, "api_key": provider + "-private-key"})
        self.store.select({"provider": "deepseek"})
        restored = ConnectionStore(self.root)
        public = restored.public()
        self.assertEqual(public["active"], "deepseek")
        self.assertTrue(all(profile["configured"] for profile in public["profiles"]))
        for provider in ["claude", "openai", "deepseek"]:
            choice = restored.choice(provider)
            self.assertEqual(choice.config.api_key, provider + "-private-key")
            self.assertNotIn("private-key", repr(choice))
        self.assertNotIn("private-key", json.dumps(public))
        self.assertNotIn("api_key", json.dumps(public))
        self.assertEqual(stat.S_IMODE(restored.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(restored.directory.stat().st_mode), 0o700)
        self.assertEqual(sorted(path.name for path in restored.directory.iterdir()), ["connections.json"])

    def test_blank_key_keeps_saved_key_and_choice_freezes_model_and_key(self):
        self.store.save({"provider": "openai", "api_key": "old-key", "model": "first"})
        self.store.select({"provider": "openai"})
        old = self.store.choice()
        self.store.save({"provider": "openai", "api_key": "", "model": "second"})
        self.assertEqual(self.store.choice().config.api_key, "old-key")
        self.store.save({"provider": "openai", "api_key": "new-key"})
        self.assertEqual(self.store.choice().config.model, "second")
        self.assertEqual(self.store.choice().config.api_key, "new-key")
        self.assertEqual(old.config.model, "first")
        self.assertEqual(old.config.api_key, "old-key")

    def test_deleting_active_profile_restores_environment_and_keeps_other_profiles(self):
        self.store.save({"provider": "openai", "api_key": "key-a"})
        self.store.save({"provider": "deepseek", "api_key": "key-b"})
        self.store.select({"provider": "openai"})
        self.store.delete({"provider": "openai"})
        self.assertEqual(self.store.public()["active"], "environment")
        self.assertEqual(self.store.choice("deepseek").config.api_key, "key-b")
        self.assertNotIn("key-a", self.store.path.read_text())
        with self.assertRaisesRegex(YoinError, "先保存"):
            self.store.select({"provider": "openai"})
        self.store.select({"provider": "codex"})
        self.assertEqual(self.store.choice().provider, "codex")

    def test_invalid_inputs_and_url_credentials_have_chinese_errors_without_secrets(self):
        cases = [
            {"provider": "unknown", "api_key": "key"}, {"provider": "openai"},
            {"provider": "openai", "api_key": "line\nbreak"},
            {"provider": "openai", "api_key": "key", "model": " "},
            {"provider": "openai", "api_key": "key", "model": "bad name"},
            *[{"provider": "openai", "api_key": "key", "base_url": url} for url in
              ["ftp://example.com", "https://user:never-echo@example.com", "https://example.com?key=never-echo",
               "https://example.com#never-echo", "https://example.com:bad", "https://example.com/ new"]],
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(YoinError) as caught:
                self.store.save(data)
            self.assertNotIn("never-echo", str(caught.exception))
        self.assertFalse(self.store.path.exists())

    def test_concurrent_saves_do_not_overwrite_other_profiles(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda provider: self.store.save({"provider": provider, "api_key": provider + "-key"}),
                          ["claude", "openai", "deepseek"]))
        self.assertTrue(all(profile["configured"] for profile in self.store.public()["profiles"]))

    def test_symlink_and_corrupt_configuration_are_rejected(self):
        other = self.root / "other"
        other.mkdir()
        self.store.directory.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(YoinError, "符号链接"):
            self.store.save({"provider": "openai", "api_key": "secret"})
        self.assertFalse(list(other.iterdir()))
        self.store.directory.unlink()
        self.store.directory.mkdir()
        self.store.path.write_text('{"api_key":"never-echo",')
        with self.assertRaisesRegex(YoinError, "无法读取") as caught:
            self.store.public()
        self.assertNotIn("never-echo", str(caught.exception))
        self.store.path.unlink()
        target = other / "connections.json"
        target.write_text("{}")
        self.store.path.symlink_to(target)
        with self.assertRaisesRegex(YoinError, "符号链接"):
            self.store.public()

    def test_only_test_sends_request_and_deepseek_disables_thinking(self):
        response = completion(function_call("yoin_connection_check", {"ok": True}))
        with LocalProvider([response]) as provider:
            self.store.save({"provider": "deepseek", "api_key": "test-private-key", "base_url": provider.url})
            self.store.select({"provider": "deepseek"})
            self.store.public()
            self.assertEqual(provider.requests, [])
            result = self.store.test({"provider": "deepseek"})
            self.assertTrue(result["ok"])
            self.assertEqual(len(provider.requests), 1)
            self.assertEqual(provider.requests[0]["thinking"], {"type": "disabled"})
            self.assertEqual(provider.requests[0]["model"], "deepseek-flash")
            self.assertNotIn("test-private-key", json.dumps(result))
            self.assertNotIn("test-private-key", json.dumps(provider.requests))

    def test_connection_check_requires_a_real_tool_call_and_hides_provider_errors(self):
        for response, message in [
            (completion(content="ok"), "工具调用"),
            (completion(function_call("yoin_connection_check", {"ok": 1})), "工具调用"),
            ((401, {"error": {"message": "provider-private-detail", "type": "authentication_error"}}), "认证失败"),
        ]:
            with self.subTest(message=message), LocalProvider([response]) as provider:
                self.store.save({"provider": "openai", "api_key": "test-key", "base_url": provider.url})
                with self.assertRaisesRegex(YoinError, message) as caught:
                    self.store.test({"provider": "openai"})
                self.assertNotIn("provider-private-detail", str(caught.exception))

    def test_environment_fallback_uses_legacy_configuration(self):
        with patch.dict(os.environ, {"YOIN_PROVIDER": "api", "YOIN_API_KEY": "env-key",
                                     "YOIN_BASE_URL": "https://example.com/v1", "YOIN_MODEL": "env-model"}):
            model, info = self.store.choice().create_model()
            try:
                self.assertEqual(info["provider"], "api")
                self.assertEqual(info["model"], "env-model")
            finally:
                model.close()

    def test_cli_uses_saved_selection_instead_of_environment_api_values(self):
        with LocalProvider([completion(preview()), completion(submit())]) as provider:
            create_project(self.root)
            self.store.save({"provider": "openai", "api_key": "saved-cli-private-key", "base_url": provider.url,
                             "model": "saved-cli-model"})
            self.store.select({"provider": "openai"})
            environment = {**os.environ, "YOIN_PROJECT_DIR": str(self.root), "YOIN_PROVIDER": "api",
                           "YOIN_API_KEY": "", "YOIN_BASE_URL": "", "YOIN_MODEL": ""}
            process = subprocess.run([sys.executable, "-m", "yoin.run", "安静阅读"],
                                     env=environment, capture_output=True, text=True, timeout=90)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(len(provider.requests), 2)
            self.assertEqual(provider.requests[0]["model"], "saved-cli-model")
            self.assertNotIn("saved-cli-private-key", process.stdout + process.stderr)
            run = next((self.root / "runs").iterdir())
            snapshot = json.loads((run / "inputs.json").read_text())
            self.assertEqual(snapshot["model"]["provider"], "openai")


if __name__ == "__main__":
    unittest.main()
