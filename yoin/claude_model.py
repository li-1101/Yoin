"""Claude 原生 Messages 与 Yoin 工具消息之间的适配。"""

import json

import anthropic

from .config import ModelConfig
from .errors import YoinError


class ClaudeModel:
    def __init__(self, config: ModelConfig):
        self._model = config.model
        try:
            self._client = anthropic.Anthropic(api_key=config.api_key, base_url=config.base_url,
                                                timeout=60.0, max_retries=0)
        except (anthropic.AnthropicError, ValueError) as exc:
            raise YoinError("无法创建 Claude 连接，请检查服务地址和 API Key") from exc

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        system, native = [], []
        for message in messages:
            role, content = message["role"], message.get("content")
            if role == "system":
                system.append(content or "")
                continue
            if role == "tool":
                role = "user"
                blocks = [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": content or ""}]
            elif role == "assistant" and "claude_content" in message:
                # 原样回传思考签名及工具块，避免新版 Claude 在后续工具轮次丢失原生上下文。
                blocks = message["claude_content"]
            else:
                blocks = [{"type": "text", "text": content}] if content else []
                for call in message.get("tool_calls", []):
                    function = call["function"]
                    blocks.append({"type": "tool_use", "id": call["id"], "name": function["name"],
                                   "input": json.loads(function["arguments"])})
            if native and native[-1]["role"] == role:
                native[-1]["content"].extend(blocks)
            else:
                native.append({"role": role, "content": list(blocks)})
        definitions = [{"name": tool["function"]["name"], "description": tool["function"].get("description", ""),
                        "input_schema": tool["function"]["parameters"]} for tool in tools]
        try:
            response = self._client.messages.create(model=self._model, max_tokens=4096,
                                                    system="\n\n".join(system), messages=native,
                                                    tools=definitions, tool_choice={"type": "auto"})
            result = response.model_dump(mode="json", exclude_none=True)
            blocks = result["content"]
            content = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
            calls = [{"id": block["id"], "type": "function", "function": {
                "name": block["name"], "arguments": json.dumps(block["input"], ensure_ascii=False)}}
                for block in blocks if block.get("type") == "tool_use"]
            message = {"role": "assistant", "content": content or None, "claude_content": blocks}
            if calls:
                message["tool_calls"] = calls
            return {"id": result["id"], "model": result["model"], "usage": result.get("usage", {}),
                    "choices": [{"index": 0, "message": message,
                                 "finish_reason": "tool_calls" if calls else "stop"}]}
        except anthropic.AuthenticationError as exc:
            raise YoinError("Claude 认证失败，请检查 API Key") from exc
        except anthropic.PermissionDeniedError as exc:
            raise YoinError("Claude 拒绝访问，请检查密钥权限") from exc
        except anthropic.NotFoundError as exc:
            raise YoinError("Claude 模型或接口不存在，请检查模型名称和服务地址") from exc
        except anthropic.RateLimitError as exc:
            raise YoinError("Claude 限流或额度不足，请稍后重试") from exc
        except anthropic.APITimeoutError as exc:
            raise YoinError("Claude 请求超时，请检查服务状态") from exc
        except anthropic.APIConnectionError as exc:
            raise YoinError("无法连接 Claude，请检查服务地址和网络") from exc
        except anthropic.BadRequestError as exc:
            raise YoinError("Claude 不接受当前请求，请检查模型是否支持工具调用") from exc
        except anthropic.APIStatusError as exc:
            raise YoinError(f"Claude 服务返回 HTTP {exc.status_code} 错误") from exc
        except (anthropic.AnthropicError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise YoinError("无法解析 Claude 响应，请检查接口兼容性") from exc

    def close(self):
        self._client.close()
