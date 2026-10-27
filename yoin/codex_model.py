"""使用官方 Codex CLI 和已有 ChatGPT 登录，桥接 Yoin 的工具决策。"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .errors import YoinError
from .schema import DataModel


class ToolDecision(DataModel):
    tool: Literal["render_and_analyze", "submit_recipe", "none"]
    arguments_json: str
    content: str


def _cli_environment() -> dict:
    environment = dict(os.environ)
    # 此入口明确复用已保存的 ChatGPT 登录，避免进程环境中的 API Key 改变计费入口。
    for name in ("CODEX_API_KEY", "OPENAI_API_KEY", "CODEX_ACCESS_TOKEN"):
        environment.pop(name, None)
    return environment


class CodexModel:
    def __init__(self):
        self.executable = shutil.which("codex")
        if self.executable is None:
            raise YoinError("未找到本机 Codex，请安装并运行 codex login 登录 ChatGPT")
        self.model = os.environ.get("YOIN_CODEX_MODEL", "").strip() or None
        try:
            self.timeout = int(os.environ.get("YOIN_CODEX_TIMEOUT", "180"))
        except ValueError as exc:
            raise YoinError("YOIN_CODEX_TIMEOUT 必须是秒数整数") from exc
        if not 1 <= self.timeout <= 600:
            raise YoinError("YOIN_CODEX_TIMEOUT 必须在 1–600 秒之间")
        try:
            status = subprocess.run([self.executable, "login", "status"], capture_output=True,
                                    text=True, timeout=20, env=_cli_environment())
            version = subprocess.run([self.executable, "--version"], capture_output=True,
                                     text=True, timeout=20, env=_cli_environment())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise YoinError("无法检查本机 Codex，请在终端运行 codex login status") from exc
        if status.returncode or "chatgpt" not in (status.stdout + status.stderr).lower():
            raise YoinError("本机 Codex 尚未通过 ChatGPT 登录，请先在终端运行 codex login")
        self.version = version.stdout.strip() if version.returncode == 0 else "unknown"
        self._lock = threading.Lock()
        self._process = None
        self._closed = False

    def public_info(self) -> dict:
        return {"provider": "codex", "transport": "codex_cli", "auth": "chatgpt",
                "model": self.model or "codex-default", "cli_version": self.version}

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        prompt = (
            "你只负责 Yoin 的声音工具决策。不要运行命令、读取文件、调用其他工具或修改项目。\n"
            "下面是完整对话和可用工具。选择下一步工具，按输出 schema 返回 JSON。\n"
            "tool 是工具名；arguments_json 是该工具参数对象编码成的 JSON 字符串；content 是简短中文说明。\n"
            "不用工具时 tool=none，arguments_json={}。程序会执行工具，再把真实结果交回给你。\n"
            "收到混音建议后尝试一次合理调整即可，不必消除所有建议；最后调用 submit_recipe。\n\n"
            + json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False, allow_nan=False)
        )
        with tempfile.TemporaryDirectory(prefix="yoin-codex-") as directory:
            folder = Path(directory)
            schema_file, result_file = folder / "schema.json", folder / "result.json"
            schema_file.write_text(json.dumps(ToolDecision.model_json_schema()), encoding="utf-8")
            command = [self.executable, "exec", "--ignore-user-config", "--ephemeral", "--sandbox", "read-only",
                       "--skip-git-repo-check", "--cd", str(folder), "--disable", "shell_tool",
                       "--disable", "multi_agent", "--disable", "apps", "--disable", "plugins",
                       "--disable", "hooks", "--output-schema", str(schema_file),
                       "--output-last-message", str(result_file), "--json"]
            if self.model:
                command += ["--model", self.model]
            process = None
            try:
                with self._lock:
                    if self._closed:
                        raise YoinError("本次模型连接已停止，已有试听会保留")
                    process = subprocess.Popen(command + ["-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE, text=True, env=_cli_environment(),
                                               start_new_session=True)
                    self._process = process
                stdout, stderr = process.communicate(prompt, timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                self._terminate(process)
                process.communicate()
                raise YoinError("本机 Codex 请求超时，已有试听会保留") from exc
            except KeyboardInterrupt:
                if process is not None:
                    self._terminate(process)
                    process.communicate()
                raise
            except OSError as exc:
                raise YoinError("无法启动本机 Codex，请检查程序路径和登录状态") from exc
            finally:
                with self._lock:
                    self._process = None
            if self._closed:
                raise YoinError("本次模型连接已停止，已有试听会保留")
            if process.returncode:
                error = (stdout + stderr).lower()
                if any(word in error for word in ("usage limit", "rate limit", "quota", "credits")):
                    raise YoinError("本机 Codex 套餐额度受限，请稍后再试或检查套餐用量")
                raise YoinError("本机 Codex 未完成请求，请检查登录、网络和套餐状态")
            try:
                decision = ToolDecision.model_validate_json(result_file.read_text(encoding="utf-8"))
            except (OSError, ValidationError, UnicodeError) as exc:
                raise YoinError("本机 Codex 没有返回有效的工具决策，请重试") from exc
            usage = {}
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("type") == "turn.completed":
                    usage = event.get("usage", {})
            message = {"role": "assistant", "content": decision.content or None}
            if decision.tool != "none":
                message["tool_calls"] = [{"id": "codex_" + uuid.uuid4().hex, "type": "function", "function": {
                    "name": decision.tool, "arguments": decision.arguments_json}}]
            return {"model": self.model or "codex-default", "provider": "codex_cli", "usage": usage,
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if decision.tool != "none" else "stop"}]}

    @staticmethod
    def _terminate(process) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        except ProcessLookupError:
            pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            process = self._process
        if process is not None:
            self._terminate(process)
