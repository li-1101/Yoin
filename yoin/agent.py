"""八轮以内的工具调用循环；模型请求可注入以便离线验收。"""

import json
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .config import MAX_STEPS, RENDERER_VERSION
from .errors import YoinError
from .library import load_library
from .prompts import build_prompt
from .rules import load_rules
from .tools import ToolSession, tool_definitions
from .trace import RunTrace


def _assistant_message(response: dict) -> dict:
    try:
        message = response["choices"][0]["message"]
        if message.get("role") != "assistant" or not isinstance(message.get("content"), (str, type(None))):
            raise ValueError
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list):
            raise ValueError
        ids = set()
        normalized_calls = []
        for call in calls:
            function = call["function"]
            if (call.get("type") != "function" or not isinstance(call["id"], str) or not call["id"]
                    or call["id"] in ids or not isinstance(function["name"], str)
                    or not isinstance(function["arguments"], str)):
                raise ValueError
            ids.add(call["id"])
            normalized_calls.append({"id": call["id"], "type": "function", "function": {
                "name": function["name"], "arguments": function["arguments"]}})
        assistant = {"role": "assistant", "content": message.get("content")}
        if calls:
            assistant["tool_calls"] = normalized_calls
        # 部分兼容推理服务要求原样回传该字段；原始响应仍完整保存在 trace。
        if "reasoning_content" in message:
            assistant["reasoning_content"] = message["reasoning_content"]
        return assistant
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise YoinError("模型返回的消息或工具调用结构无效，请检查服务兼容性") from exc


def run_agent(
    user_request: str,
    root: Path | str,
    complete: Callable[[list[dict], list[dict]], dict],
    *,
    model_info: dict | None = None,
    final_seconds: int = 120,
) -> dict:
    if not isinstance(user_request, str) or not user_request.strip():
        raise YoinError("场景描述不能为空")
    root = Path(root).resolve()
    trace = RunTrace.create(root)
    trace.record("start", user_request=user_request, model=model_info or {})
    try:
        library = load_library(root / "library.json")
        rules = load_rules(root / "mixing_rules.json")
        context = build_prompt(root, library, rules)
        definitions = tool_definitions()
        trace.save_json("inputs.json", {
            "user_request": user_request, "system_prompt": context.system_prompt,
            "guidance": context.guidance, "templates": context.templates,
            "library": [sound.model_dump(exclude_none=True) for sound in library.sounds.values()],
            "sound_files": library.freeze_sources(), "rules": rules.model_dump(), "tools": definitions,
            "model": model_info or {}, "app_version": __version__, "renderer_version": RENDERER_VERSION,
            "final_seconds": final_seconds, "max_steps": MAX_STEPS,
        })
        session = ToolSession(library, rules, trace, final_seconds)
        messages = [{"role": "system", "content": context.system_prompt},
                    {"role": "user", "content": user_request}]
        reason = f"达到 {MAX_STEPS} 轮上限，未主动提交"
        for step in range(1, MAX_STEPS + 1):
            trace.record("llm_request", step=step, messages=messages, tools=definitions)
            try:
                response = complete(messages, definitions)
                trace.record("llm_response", step=step, response=response)
                assistant = _assistant_message(response)
            except YoinError as exc:
                trace.record("error", step=step, error=str(exc))
                reason = "模型请求或响应失败，未主动提交：" + str(exc)
                break
            messages.append(assistant)
            calls = assistant.get("tool_calls", [])
            if not calls:
                reminder = "必须调用 submit_recipe 才能结束。请先试听、按建议尝试调整，再附中文解释提交。"
                messages.append({"role": "user", "content": reminder})
                trace.record("notice", step=step, message=reminder)
                continue
            for call in calls:
                function = call["function"]
                trace.record("tool_call", step=step, tool_call_id=call["id"], **function)
                if session.final_data is not None:
                    result = {"success": False, "error": "运行已结束，后续工具未执行"}
                else:
                    result = session.execute(function["name"], function["arguments"])
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(result, ensure_ascii=False, allow_nan=False)})
                trace.record("tool_result", step=step, tool_call_id=call["id"], result=result)
            if session.final_data is not None:
                break
        if session.final_data is None:
            if session.last_recipe is None:
                raise YoinError(reason + "；本次未产生有效配方")
            explanation = "本次未主动提交，使用最后一份成功试听的配方。\n\n结束原因：" + reason
            session.finish(session.last_recipe, explanation, submitted=False, reason=reason)
        final = {"run_id": trace.directory.name, "run_directory": str(trace.directory), **session.final_data}
        trace.record("final", **final)
        return final
    except (YoinError, OSError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            error = "用户中断了本次运行，已有过程和试听已保留"
        elif isinstance(exc, YoinError):
            error = str(exc)
        else:
            error = "无法保存运行产物，请检查目录权限和磁盘空间"
        trace.record("final", status="failed", error=error)
        raise YoinError(f"{error}；过程目录：{trace.directory}") from exc
