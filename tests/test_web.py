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

from yoin.agent import run_agent
from yoin.web import make_server

from .agent_helpers import ScriptedModel, completion, create_project, preview, submit


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

    def tearDown(self):
        self.server.shutdown()
        self.server.app.close()
        self.server.server_close()
        self.thread.join(5)
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


if __name__ == "__main__":
    unittest.main()
