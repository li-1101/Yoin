"""确定性的模型响应和临时项目，供循环及 HTTP 验收复用。"""

import copy
import json
from pathlib import Path

from .helpers import recipe, write_library


def create_project(root: Path):
    library = write_library(root)
    (root / "prompts").mkdir()
    base = Path(__file__).resolve().parents[1] / "prompts" / "system.md"
    (root / "prompts" / "system.md").write_text(base.read_text(), encoding="utf-8")
    (root / "guidance").mkdir()
    (root / "guidance" / "mixing.md").write_text("合作者指导：保持声音稳定，不抢注意。", encoding="utf-8")
    (root / "templates").mkdir()
    (root / "templates" / "quiet.md").write_text("版本：2。主体是持续的背景声。", encoding="utf-8")
    (root / "templates" / "quiet.recipe.json").write_text(json.dumps(recipe()), encoding="utf-8")
    return library


def function_call(name, arguments, call_id="call_1"):
    encoded = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": encoded}}


def completion(*calls, content=None, reasoning=None):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = list(calls)
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"id": "chatcmpl-scripted", "object": "chat.completion", "created": 1, "model": "scripted",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


def preview(data=None, call_id="preview"):
    return function_call("render_and_analyze", {"recipe": data or recipe(), "seconds": 1}, call_id)


def submit(data=None, call_id="submit", explanation="选择平稳的背景声，保持安静。"):
    return function_call("submit_recipe", {"recipe": data or recipe(), "explanation": explanation}, call_id)


class ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(copy.deepcopy({"messages": messages, "tools": tools}))
        response = self.responses.pop(0) if self.responses else completion(content="继续思考。")
        if isinstance(response, BaseException):
            raise response
        return response
