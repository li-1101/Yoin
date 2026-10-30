"""仅用于验收的本地兼容 HTTP 服务，不属于产品服务。"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


class LocalProvider:
    def __init__(self, responses, *, endpoint="/v1/chat/completions"):
        self.responses = list(responses)
        self.endpoint = endpoint
        self.requests = []
        self.auth_present = []

    def __enter__(self):
        provider = self
        # 本机可能设置全局 HTTP 代理；测试服务只对回环地址暂时绕过，退出后恢复。
        self._environment = patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost,::1",
                                                   "no_proxy": "127.0.0.1,localhost,::1"})
        self._environment.start()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(size))
                provider.requests.append(body)
                provider.auth_present.append(self.headers.get("Authorization", "").startswith("Bearer ")
                                             or bool(self.headers.get("X-Api-Key")))
                if self.path != provider.endpoint or not provider.responses:
                    response = (404, {"error": {"message": "测试响应已用完", "type": "not_found"}})
                else:
                    response = provider.responses.pop(0)
                status, payload = response if isinstance(response, tuple) else (200, response)
                encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        try:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
        finally:
            self._environment.stop()
