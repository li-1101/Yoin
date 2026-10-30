"""仅绑定回环地址的本地试听网页，复用同一 agent 和运行存储。"""

import argparse
import json
import logging
import os
import re
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import Field, ValidationError

from .agent import run_agent
from .cli import ChineseArgumentParser, run_cli
from .config import project_root
from .connections import ConnectionStore
from .errors import YoinError
from .runs import RunStore
from .schema import DataModel, chinese_validation_error
from .trace import RunTrace

ASSETS = Path(__file__).with_name("web_assets")


class JobRequest(DataModel):
    request: Annotated[str, Field(min_length=1, max_length=2000)]
    from_run: str | None = None


class AppState:
    def __init__(self, root: Path, model_factory=None):
        self.root = root
        self.store = RunStore(root)
        self.connections = ConnectionStore(root)
        self.model_factory = model_factory
        self.token = secrets.token_urlsafe(32)
        self.jobs = {}
        self.active_job = None
        self.lock = threading.Lock()
        self._model = None
        self._worker = None
        self._closed = False

    def connection(self) -> dict:
        try:
            factory = self.model_factory or self.connections.choice(api_only=True).create_model
            model, info = factory()
            model.close()
            label = info.get("label", "模型") + " API Key · 已配置"
            return {"ready": True, "label": label, "provider": info.get("provider", "api")}
        except YoinError as exc:
            return {"ready": False, "label": "API Key 尚未配置或不可用", "error": str(exc)}

    def start(self, data: dict) -> dict:
        try:
            request = JobRequest.model_validate(data)
        except ValidationError as exc:
            raise chinese_validation_error(exc, "生成请求") from exc
        if not request.request.strip():
            raise YoinError("场景描述不能为空")
        if request.from_run is not None:
            detail = self.store.get(request.from_run)
            if not detail["can_refine"]:
                raise YoinError("该版本还不能继续微调")
        with self.lock:
            if self._closed:
                raise YoinError("本地服务正在停止")
            if self.active_job is not None:
                raise YoinError("已有一个声音正在调配，请等它完成后再试")
            # 固定任务开始时的配置；在网页切换或替换密钥只影响下一次任务。
            factory = self.model_factory or self.connections.choice(api_only=True).create_model
            job_id = uuid.uuid4().hex
            job = {"job_id": job_id, "status": "running", "run_id": None, "error": ""}
            self.jobs[job_id] = job
            self.active_job = job_id
            self._worker = threading.Thread(target=self._generate, args=(job_id, request, factory), daemon=True, name="yoin-generate")
            self._worker.start()
        return dict(job)

    def _generate(self, job_id: str, request: JobRequest, factory):
        model = None
        try:
            model, info = factory()
            with self.lock:
                self._model = model
                if self._closed:
                    raise YoinError("本地服务已停止，已有过程已保留")

            def started(directory):
                with self.lock:
                    self.jobs[job_id]["run_id"] = directory.name

            final = run_agent(request.request, self.root, model.complete, model_info=info,
                              from_run=request.from_run, on_started=started)
            with self.lock:
                self.jobs[job_id].update(status="completed", run_id=final["run_id"])
        except Exception as exc:
            error = str(exc).split("；过程目录：")[0] if isinstance(exc, YoinError) else "这次生成未完成，已有过程已保留，请重试"
            if not isinstance(exc, YoinError):
                logging.error("Yoin worker failed (%s)", type(exc).__name__)
            with self.lock:
                self.jobs[job_id].update(status="failed", error=error)
                run_id = self.jobs[job_id]["run_id"]
            if run_id is not None:
                try:
                    if self.store.get(run_id)["status"] == "unfinished":
                        RunTrace(self.store.directory(run_id)).record("final", status="failed", error=error)
                except (YoinError, OSError):
                    logging.error("Yoin could not save the interrupted run status")
        finally:
            try:
                if model is not None:
                    model.close()
            finally:
                with self.lock:
                    self._model = None
                    self.active_job = None

    def close(self):
        with self.lock:
            self._closed = True
            model, worker = self._model, self._worker
        if model is not None:
            model.close()
        if worker is not None:
            worker.join(timeout=5)

    def job(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.jobs:
                raise YoinError("找不到该生成任务")
            result = dict(self.jobs[job_id])
        result["run"] = None
        if result["run_id"]:
            try:
                result["run"] = self.store.get(result["run_id"])
            except (YoinError, OSError):
                pass  # 首个快照正在落盘，下一次轮询读取完整版本。
        return result


def make_server(root: Path | str, port: int = 8787, *, model_factory=None):
    app = AppState(Path(root).resolve(), model_factory)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

        def _allowed(self):
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            return host in allowed_hosts and (origin is None or origin in {"http://" + name for name in allowed_hosts})

        def _json(self, status, data):
            payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status >= 400:
                # 拒绝请求时可能尚未读取正文，关闭连接避免把残余正文当成下一次请求。
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(payload)

        def _file(self, path, content_type, *, download=False):
            if not path.is_file() or path.is_symlink():
                self._json(404, {"error": "文件不存在或尚未生成"})
                return
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            header = self.headers.get("Range")
            if header:
                matched = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
                valid = matched is not None and bool(matched[1] or matched[2])
                if valid:
                    if matched[1]:
                        start, end = int(matched[1]), min(int(matched[2]) if matched[2] else size - 1, size - 1)
                    else:
                        start = max(0, size - int(matched[2]))
                    valid = 0 <= start <= end < size and (matched[1] or int(matched[2]) > 0)
                if not valid:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            with path.open("rb") as file:
                file.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = file.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_GET(self):
            if not self._allowed():
                self._json(403, {"error": "仅允许本机页面访问"})
                return
            url = urlsplit(self.path)
            path = unquote(url.path)
            try:
                static = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}
                if path in static:
                    name, content_type = static[path]
                    self._file(ASSETS / name, content_type)
                elif path == "/api/bootstrap":
                    self._json(200, {"token": app.token, "connection": app.connection(),
                                     "active_job": app.active_job})
                elif path == "/api/runs":
                    self._json(200, {"runs": app.store.list()})
                elif path == "/api/connections":
                    self._json(200, app.connections.public())
                elif path.startswith("/api/runs/"):
                    self._json(200, app.store.get(path.removeprefix("/api/runs/")))
                elif path.startswith("/api/jobs/"):
                    self._json(200, app.job(path.removeprefix("/api/jobs/")))
                elif path.startswith("/media/"):
                    parts = path.split("/")
                    allowed = {"draft.wav", "final.wav", "final.json", "explanation.md", "draft.credits.md", "final.credits.md"}
                    if len(parts) != 4 or parts[3] not in allowed:
                        raise YoinError("该文件不能通过页面访问")
                    directory = app.store.directory(parts[2])
                    file = directory / parts[3]
                    if file.resolve().parent != directory.resolve():
                        raise YoinError("文件路径不正确")
                    content_type = "audio/wav" if file.suffix == ".wav" else "application/json" if file.suffix == ".json" else "text/plain; charset=utf-8"
                    self._file(file, content_type, download="download" in parse_qs(url.query))
                else:
                    self._json(404, {"error": "找不到该页面"})
            except (BrokenPipeError, ConnectionResetError):
                pass  # 播放器切换音频或拖动进度时会主动中断旧下载。
            except YoinError as exc:
                self._json(400, {"error": str(exc)})
            except (OSError, UnicodeError):
                self._json(500, {"error": "暂时无法读取本地记录，请稍后重试"})

        def do_POST(self):
            if not self._allowed() or not secrets.compare_digest(self.headers.get("X-Yoin-Token", ""), app.token):
                self._json(403, {"error": "请从本机 Yoin 页面发起操作"})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "请求必须使用 JSON"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise YoinError("请求为空或内容过长")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise YoinError("请求必须是 JSON 对象")
                if self.path == "/api/jobs":
                    self._json(202, app.start(data))
                elif self.path == "/api/ratings":
                    run_id = data.pop("run_id", None)
                    self._json(201, app.store.rate(run_id, data))
                elif self.path == "/api/connections/save":
                    self._json(200, app.connections.save(data))
                elif self.path == "/api/connections/select":
                    self._json(200, app.connections.select(data))
                elif self.path == "/api/connections/delete":
                    self._json(200, app.connections.delete(data))
                elif self.path == "/api/connections/test":
                    self._json(200, app.connections.test(data))
                else:
                    self._json(404, {"error": "找不到该操作"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (ValueError, UnicodeError) as exc:
                error = str(exc) if isinstance(exc, YoinError) else "请求 JSON 格式不正确"
                self._json(400, {"error": error})
            except OSError:
                self._json(500, {"error": "无法保存本地结果，请检查磁盘空间与目录权限"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app
    return server


def port_argument(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("端口必须是整数") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 0–65535 之间")
    return port


def main():
    parser = ChineseArgumentParser(description="启动 Yoin 本地试听页面")
    parser.add_argument("--port", type=port_argument, default=os.environ.get("YOIN_WEB_PORT", "8787"), help="本机端口，默认 8787")
    args = parser.parse_args()

    def action():
        try:
            server = make_server(project_root(), args.port)
        except OSError as exc:
            raise YoinError("本机端口无法使用，请换一个 --port") from exc
        print(f"Yoin 已启动：http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n本地页面服务已停止")
        finally:
            server.app.close()
            server.server_close()

    return run_cli(action)


if __name__ == "__main__":
    raise SystemExit(main())
