import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from yoin.agent import run_agent
from yoin.connections import ConnectionChoice
from yoin.errors import YoinError
from yoin.web import main, make_server

from .agent_helpers import ScriptedModel, completion, create_project, preview, submit
from .fake_provider import LocalProvider


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        create_project(self.root)
        model = ScriptedModel([completion(preview()), completion(submit())])
        self.final = run_agent("阅读", self.root, model.complete, final_seconds=1)
        self.models = []

        def factory():
            model = ScriptedModel([completion(preview()), completion(submit())])
            self.models.append(model)
            return model, {"provider": "test", "model": "scripted-web-test"}

        self.server = make_server(self.root, 0, model_factory=factory)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.token = self.server.app.token

    def stop_server(self):
        self.server.shutdown()
        self.server.app.close()
        self.server.server_close()
        self.thread.join(5)

    def restart_server(self, *, local_codex=False):
        self.stop_server()
        self.server = make_server(self.root, 0, local_codex=local_codex)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.token = self.server.app.token

    def tearDown(self):
        self.stop_server()
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None, raw=None):
        body = json.dumps(data, ensure_ascii=False).encode() if data is not None else raw
        defaults = {"Content-Type": "application/json", "X-Yoin-Token": self.token}
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request(method, path, body=body, headers={**defaults, **(headers or {})})
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, dict(response.getheaders()), payload)
        connection.close()
        return result

    def json_request(self, method, path, data=None, **kwargs):
        status, headers, body = self.request(method, path, data, **kwargs)
        return status, headers, json.loads(body)

    def wait_job(self, job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, _, job = self.json_request("GET", "/api/jobs/" + job_id)
            self.assertEqual(status, 200)
            if job["status"] != "running":
                return job
            time.sleep(0.05)
        self.fail("本地脚本生成超时")

    def test_static_bootstrap_and_history_share_the_existing_runs(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Yoin 余韵".encode(), body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        status, _, bootstrap = self.json_request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertTrue(bootstrap["connection"]["ready"])
        self.assertEqual(bootstrap["token"], self.token)
        _, _, history = self.json_request("GET", "/api/runs")
        self.assertEqual(history["runs"][0]["run_id"], self.final["run_id"])
        for path in ["/app.js", "/style.css"]:
            self.assertEqual(self.request("GET", path)[0], 200)

    def test_external_origins_hosts_and_missing_tokens_cannot_start_generation(self):
        data = {"request": "安静"}
        for headers in [{"Origin": "https://example.com"}, {"Host": "example.com"}, {"X-Yoin-Token": ""}]:
            status, response_headers, _ = self.json_request("POST", "/api/jobs", data, headers=headers)
            self.assertEqual(status, 403)
            self.assertEqual(response_headers["Connection"], "close")
        for headers in [{"Origin": "https://example.com"}, {"Host": "example.com"}]:
            self.assertEqual(self.request("GET", "/api/bootstrap", headers=headers)[0], 403)
        self.assertFalse(self.models)

    def test_invalid_json_content_type_and_requests_have_chinese_errors(self):
        cases = [({"request": "   "}, "非空字符串"), ({"request": "a" * 2001}, "2000"),
                 ({"request": "阅读", "unknown": True}, "unknown"), ({"request": "阅读", "from_run": "../escape"}, "编号")]
        for data, expected in cases:
            status, _, result = self.json_request("POST", "/api/jobs", data)
            self.assertEqual(status, 400)
            self.assertIn(expected, result["error"])
        self.assertEqual(self.request("POST", "/api/jobs", raw=b"{}", headers={"Content-Type": "text/plain"})[0], 415)
        status, _, result = self.json_request("POST", "/api/jobs", raw=b"{")
        self.assertEqual(status, 400)
        self.assertIn("JSON 格式", result["error"])

    def test_generation_refinement_and_rating_work_over_http(self):
        status, _, started = self.json_request("POST", "/api/jobs", {
            "request": "背景更轻一点", "from_run": self.final["run_id"]})
        self.assertEqual(status, 202)
        job = self.wait_job(started["job_id"])
        self.assertEqual(job["status"], "completed", job)
        run = job["run"]
        self.assertEqual(run["parent_run_id"], self.final["run_id"])
        self.assertTrue(run["has_draft"] and run["has_final"])
        status, _, rating = self.json_request("POST", "/api/ratings", {
            "run_id": run["run_id"], "which": "final", "score": 4, "note": "舒服"})
        self.assertEqual(status, 201)
        self.assertEqual(rating["note"], "舒服")
        self.assertIn("保留 seed、layer_id", self.models[0].requests[0]["messages"][1]["content"])
        self.assertIsNone(self.server.app.active_job)

    def test_busy_job_is_rejected_and_model_failure_is_explained(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingModel:
            def complete(self, messages, tools):
                entered.set()
                release.wait(10)
                raise RuntimeError("sensitive provider internals")

            def close(self):
                pass

        self.server.app.model_factory = lambda: (BlockingModel(), {"model": "scripted-failure"})
        try:
            _, _, started = self.json_request("POST", "/api/jobs", {"request": "阅读"})
            self.assertTrue(entered.wait(5))
            status, _, error = self.json_request("POST", "/api/jobs", {"request": "另一个"})
            self.assertEqual(status, 400)
            self.assertIn("已有一个声音", error["error"])
        finally:
            with self.assertLogs(level="ERROR"):
                release.set()
                job = self.wait_job(started["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("未完成", job["error"])
        self.assertNotIn("sensitive", job["error"])
        self.assertEqual(job["run"]["status"], "failed")

    def test_audio_ranges_downloads_and_traversal(self):
        prefix = "/media/" + self.final["run_id"] + "/"
        audio = Path(self.final["audio_file"]).read_bytes()
        status, headers, body = self.request("GET", prefix + "final.wav", headers={"Range": "bytes=0-43"})
        self.assertEqual(status, 206)
        self.assertEqual(body, audio[:44])
        self.assertEqual(headers["Content-Range"], f"bytes 0-43/{len(audio)}")
        self.assertEqual(self.request("GET", prefix + "final.wav", headers={"Range": "bytes=-12"})[2], audio[-12:])
        self.assertEqual(self.request("GET", prefix + "final.wav", headers={"Range": "bytes=999999999-"})[0], 416)
        status, headers, _ = self.request("GET", prefix + "final.json?download=1")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        for path in [prefix + "inputs.json", "/media/%2e%2e/final.wav", "/api/runs/..%2flibrary.json"]:
            self.assertEqual(self.request("GET", path)[0], 400)
        target = Path(self.final["run_directory"]) / "final.wav"
        target.unlink()
        target.symlink_to(self.root / "mono.wav")
        self.assertEqual(self.request("GET", prefix + "final.wav")[0], 400)

    def test_port_configuration_errors_are_chinese(self):
        for value in ["bad", "-1", "65536"]:
            result = subprocess.run([sys.executable, "-m", "yoin.web", "--port", value], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("端口必须", result.stderr)
        result = subprocess.run([sys.executable, "-m", "yoin.web"], text=True, capture_output=True,
                                env={**os.environ, "YOIN_WEB_PORT": "bad"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("端口必须是整数", result.stderr)

    def test_model_configuration_routes_never_return_saved_keys(self):
        _, _, settings = self.json_request("GET", "/api/connections")
        self.assertEqual(settings["active"], "openai")
        self.assertEqual(len(settings["profiles"]), 3)
        for provider in ["claude", "openai", "deepseek"]:
            status, _, settings = self.json_request("POST", "/api/connections/save", {
                "provider": provider, "api_key": "test-web-private-" + provider})
            self.assertEqual(status, 200)
            self.assertNotIn("test-web-private", json.dumps(settings))
        status, _, settings = self.json_request("POST", "/api/connections/select", {"provider": "openai"})
        self.assertEqual(status, 200)
        self.assertEqual(settings["active"], "openai")
        _, _, settings = self.json_request("POST", "/api/connections/save", {"provider": "openai", "model": "changed"})
        self.assertTrue(next(profile for profile in settings["profiles"] if profile["provider"] == "openai")["configured"])
        _, _, settings = self.json_request("POST", "/api/connections/delete", {"provider": "openai"})
        self.assertEqual(settings["active"], "openai")
        _, _, public = self.json_request("GET", "/api/connections")
        self.assertNotIn("test-web-private", json.dumps(public))
        self.assertEqual(self.request("GET", "/.yoin/connections.json")[0], 404)
        for endpoint in ["save", "select", "delete", "test"]:
            status, _, _ = self.json_request("POST", "/api/connections/" + endpoint,
                                             {"provider": "openai"}, headers={"X-Yoin-Token": ""})
            self.assertEqual(status, 403)

    def test_selected_api_is_used_by_generation_and_logged_without_its_key(self):
        self.server.app.model_factory = None
        with LocalProvider([completion(preview()), completion(submit())]) as provider:
            self.json_request("POST", "/api/connections/save", {
                "provider": "deepseek", "api_key": "test-generation-private-key", "base_url": provider.url,
                "model": "scripted-selected-model"})
            self.json_request("POST", "/api/connections/select", {"provider": "deepseek"})
            _, _, started = self.json_request("POST", "/api/jobs", {"request": "阅读"})
            job = self.wait_job(started["job_id"])
            self.assertEqual(job["status"], "completed", job)
            self.assertEqual(job["run"]["provider"], "deepseek")
            self.assertEqual(job["run"]["model"], "scripted-selected-model")
            self.assertEqual(len(provider.requests), 2)
            self.assertEqual(provider.requests[0]["thinking"], {"type": "disabled"})
            for path in (self.root / "runs" / job["run_id"]).iterdir():
                if path.suffix in {".json", ".jsonl", ".md"}:
                    self.assertNotIn("test-generation-private-key", path.read_text())

    def test_switching_and_replacing_credentials_during_a_job_only_affects_the_next_job(self):
        self.server.app.model_factory = None
        store = self.server.app.connections
        store.save({"provider": "openai", "api_key": "original-key", "model": "original-model"})
        store.save({"provider": "deepseek", "api_key": "next-key"})
        store.select({"provider": "openai"})
        entered, release = threading.Event(), threading.Event()
        choices = []

        def build(choice):
            choices.append(choice)
            entered.set()
            release.wait(10)
            return ScriptedModel([completion(preview()), completion(submit())]), {
                "provider": choice.provider, "model": choice.config.model}

        with patch.object(ConnectionChoice, "create_model", build):
            try:
                _, _, started = self.json_request("POST", "/api/jobs", {"request": "阅读"})
                self.assertTrue(entered.wait(5))
                store.save({"provider": "openai", "api_key": "replacement-key", "model": "replacement-model"})
                store.select({"provider": "deepseek"})
            finally:
                release.set()
            job = self.wait_job(started["job_id"])
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["run"]["model"], "original-model")
        self.assertEqual(choices[0].provider, "openai")
        self.assertEqual(choices[0].config.api_key, "original-key")
        self.assertEqual(store.choice().provider, "deepseek")

    def test_web_requires_api_key_and_rejects_legacy_login_options(self):
        self.server.app.model_factory = None
        store = self.server.app.connections
        store.directory.mkdir(parents=True, exist_ok=True)
        with patch("yoin.codex_model.CodexModel") as local_login, patch("yoin.model.create_model") as environment:
            for legacy in ["environment", "codex"]:
                store.path.write_text(json.dumps({"version": 1, "active": legacy, "profiles": {}}))
                status, _, settings = self.json_request("GET", "/api/connections")
                self.assertEqual(status, 200)
                self.assertEqual(settings["active"], "openai")
                self.assertFalse(settings["local_codex_enabled"])
                status, _, bootstrap = self.json_request("GET", "/api/bootstrap")
                self.assertEqual(status, 200)
                self.assertFalse(bootstrap["connection"]["ready"])
                self.assertIn("GPT", bootstrap["connection"]["error"])
                self.assertIn("API Key", bootstrap["connection"]["error"])
                status, _, _ = self.json_request("POST", "/api/jobs", {"request": "阅读"})
                self.assertEqual(status, 400)
                for endpoint in ["select", "test"]:
                    status, _, _ = self.json_request("POST", "/api/connections/" + endpoint, {"provider": legacy})
                    self.assertEqual(status, 400)
            local_login.assert_not_called()
            environment.assert_not_called()
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn(b'<option value="codex">', body)
        self.assertNotIn(b'<option value="environment">', body)
        self.assertIn(b'<option value="openai" selected>GPT', body)

    def test_local_codex_selection_is_process_only_and_api_profiles_stay_independent(self):
        self.restart_server(local_codex=True)
        with patch("yoin.codex_model.CodexModel") as local:
            local.return_value.public_info.return_value = {"provider": "codex", "model": "codex-default"}
            status, _, settings = self.json_request("GET", "/api/connections")
            self.assertEqual(status, 200)
            self.assertTrue(settings["local_codex_enabled"])
            self.assertEqual(settings["active"], "codex")
            self.assertFalse(self.server.app.connections.path.exists())
            _, _, bootstrap = self.json_request("GET", "/api/bootstrap")
            self.assertTrue(bootstrap["connection"]["ready"])
            self.assertEqual(bootstrap["connection"]["provider"], "codex")
            self.assertIn("订阅测试", bootstrap["connection"]["label"])
            status, _, checked = self.json_request("POST", "/api/connections/test", {"provider": "codex"})
            self.assertEqual(status, 200)
            self.assertTrue(checked["ok"])
            self.assertIn("尚未发送模型请求", checked["message"])
            local.return_value.complete.assert_not_called()
            self.assertEqual(local.return_value.close.call_count, 2)
            self.assertFalse(self.server.app.connections.path.exists())

            for provider in ["openai", "deepseek"]:
                status, _, settings = self.json_request("POST", "/api/connections/save", {
                    "provider": provider, "api_key": "local-test-private-" + provider})
                self.assertEqual(status, 200)
                self.assertEqual(settings["active"], "codex")
                self.assertNotIn("local-test-private", json.dumps(settings))
            status, _, settings = self.json_request("POST", "/api/connections/select", {"provider": "deepseek"})
            self.assertEqual(status, 200)
            self.assertEqual(settings["active"], "deepseek")
            saved = self.server.app.connections.path.read_bytes()
            status, _, settings = self.json_request("POST", "/api/connections/select", {"provider": "codex"})
            self.assertEqual(status, 200)
            self.assertEqual(settings["active"], "codex")
            self.assertEqual(self.server.app.connections.path.read_bytes(), saved)
            self.assertEqual(self.server.app.connections.choice().provider, "deepseek")

            # 删除 API 配置不会改变本机订阅选择，也不把订阅选择写回磁盘。
            _, _, settings = self.json_request("POST", "/api/connections/delete", {"provider": "deepseek"})
            self.assertEqual(settings["active"], "codex")
            self.assertEqual(self.server.app.connections.public()["active"], "openai")
            calls = local.call_count
            self.restart_server()
            _, _, settings = self.json_request("GET", "/api/connections")
            self.assertFalse(settings["local_codex_enabled"])
            self.assertEqual(settings["active"], "openai")
            _, _, bootstrap = self.json_request("GET", "/api/bootstrap")
            self.assertEqual(bootstrap["connection"]["provider"], "openai")
            for endpoint in ["select", "test", "save", "delete"]:
                status, _, _ = self.json_request("POST", "/api/connections/" + endpoint, {"provider": "codex"})
                self.assertEqual(status, 400)
            self.assertEqual(local.call_count, calls)

    def test_missing_local_login_never_falls_back_to_a_saved_api_key(self):
        self.restart_server(local_codex=True)
        store = self.server.app.connections
        store.save({"provider": "deepseek", "api_key": "unused-private-key"})
        store.select({"provider": "deepseek"})
        with patch("yoin.codex_model.CodexModel", side_effect=YoinError("请先运行 codex login")), \
                patch("yoin.model.ChatModel") as api_model, patch("yoin.model.create_model") as environment:
            _, _, bootstrap = self.json_request("GET", "/api/bootstrap")
            self.assertFalse(bootstrap["connection"]["ready"])
            self.assertIn("Codex", bootstrap["connection"]["label"])
            self.assertIn("codex login", bootstrap["connection"]["error"])
            status, _, _ = self.json_request("POST", "/api/connections/test", {"provider": "codex"})
            self.assertEqual(status, 400)
            status, _, started = self.json_request("POST", "/api/jobs", {"request": "阅读"})
            self.assertEqual(status, 202)
            job = self.wait_job(started["job_id"])
            self.assertEqual(job["status"], "failed")
            self.assertIsNone(job["run_id"])
            self.assertIn("codex login", job["error"])
            api_model.assert_not_called()
            environment.assert_not_called()

    def test_local_codex_jobs_freeze_selection_and_refinement_uses_the_next_choice(self):
        self.restart_server(local_codex=True)
        store = self.server.app.connections
        store.save({"provider": "deepseek", "api_key": "next-private-key", "model": "next-model"})
        entered, release = threading.Event(), threading.Event()
        choices = []

        def build(choice):
            choices.append(choice)
            if len(choices) == 1:
                entered.set()
                release.wait(10)
            return ScriptedModel([completion(preview()), completion(submit())]), {
                "provider": choice.provider, "model": choice.config.model if choice.config else "local-test-model"}

        with patch.object(ConnectionChoice, "create_model", build):
            try:
                status, _, started = self.json_request("POST", "/api/jobs", {"request": "阅读"})
                self.assertEqual(status, 202)
                self.assertTrue(entered.wait(5))
                status, _, settings = self.json_request("POST", "/api/connections/select", {"provider": "deepseek"})
                self.assertEqual(status, 200)
                self.assertEqual(settings["active"], "deepseek")
            finally:
                release.set()
            first = self.wait_job(started["job_id"])
            self.assertEqual(first["status"], "completed", first)
            self.assertEqual(first["run"]["provider"], "codex")
            self.assertEqual(choices[0].provider, "codex")
            status, _, started = self.json_request("POST", "/api/jobs", {
                "request": "背景轻一点", "from_run": first["run_id"]})
            self.assertEqual(status, 202)
            second = self.wait_job(started["job_id"])
            self.assertEqual(second["status"], "completed", second)
            self.assertEqual(second["run"]["provider"], "deepseek")
            self.assertEqual(second["run"]["parent_run_id"], first["run_id"])
            self.assertEqual(choices[1].config.api_key, "next-private-key")
            self.json_request("POST", "/api/connections/select", {"provider": "codex"})
            _, _, started = self.json_request("POST", "/api/jobs", {
                "request": "再远一点", "from_run": second["run_id"]})
            third = self.wait_job(started["job_id"])
            self.assertEqual(third["status"], "completed", third)
            self.assertEqual(third["run"]["provider"], "codex")
            self.assertEqual(third["run"]["parent_run_id"], second["run_id"])
            self.assertEqual(choices[2].provider, "codex")

    def test_local_codex_http_requests_cannot_enable_or_expand_the_startup_capability(self):
        self.restart_server(local_codex=True)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        with patch("yoin.codex_model.CodexModel") as local:
            for endpoint in ["select", "test"]:
                for headers in [{"Origin": "https://example.com"}, {"Host": "example.com"}, {"X-Yoin-Token": ""}]:
                    status, _, _ = self.json_request("POST", "/api/connections/" + endpoint,
                                                     {"provider": "codex"}, headers=headers)
                    self.assertEqual(status, 403)
                for data in [{"provider": "codex", "local_codex": True}, {"provider": "environment"}]:
                    status, _, _ = self.json_request("POST", "/api/connections/" + endpoint, data)
                    self.assertEqual(status, 400)
            local.assert_not_called()
        self.restart_server()
        for endpoint, data in [("/api/connections/select", {"provider": "codex", "local_codex_enabled": True}),
                               ("/api/jobs", {"request": "阅读", "provider": "codex"})]:
            status, _, _ = self.json_request("POST", endpoint, data)
            self.assertEqual(status, 400)

    def test_cli_enables_local_codex_only_with_the_explicit_startup_flag(self):
        for arguments, enabled in [([], False), (["--local-codex"], True)]:
            server = Mock()
            server.serve_forever.side_effect = KeyboardInterrupt
            with patch.object(sys, "argv", ["yoin.web", "--port", "0", *arguments]), \
                    patch.dict(os.environ, {"YOIN_PROVIDER": "codex", "YOIN_LOCAL_CODEX": "1"}), \
                    patch("yoin.web.project_root", return_value=self.root), \
                    patch("yoin.web.make_server", return_value=server) as build, patch("builtins.print"):
                self.assertEqual(main(), 0)
            build.assert_called_once_with(self.root, 0, local_codex=enabled)
            server.app.close.assert_called_once()
            server.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
