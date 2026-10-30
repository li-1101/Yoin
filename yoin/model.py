"""兼容 Chat Completions 的薄适配器，不引入 agent 框架。"""

import os

import openai

from .config import ModelConfig
from .errors import YoinError


class ChatModel:
    def __init__(self, config: ModelConfig, *, extra_body: dict | None = None):
        self._model = config.model
        self._extra_body = extra_body
        try:
            self._client = openai.OpenAI(
                api_key=config.api_key, base_url=config.base_url, timeout=60.0, max_retries=0,
            )
        except (openai.OpenAIError, ValueError) as exc:
            raise YoinError("无法创建模型客户端，请检查服务地址和环境配置") from exc

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        try:
            response = self._client.chat.completions.create(
                model=self._model, messages=messages, tools=tools, tool_choice="auto",
                **({"extra_body": self._extra_body} if self._extra_body else {}),
            )
            if not hasattr(response, "model_dump"):
                raise YoinError("模型服务没有返回兼容的 Chat Completions 响应")
            return response.model_dump(mode="json", exclude_none=True)
        except openai.AuthenticationError as exc:
            raise YoinError("模型认证失败，请检查 API Key") from exc
        except openai.PermissionDeniedError as exc:
            raise YoinError("模型服务拒绝访问，请检查账户权限") from exc
        except openai.NotFoundError as exc:
            raise YoinError("找不到模型或接口，请检查模型名称和服务地址") from exc
        except openai.RateLimitError as exc:
            raise YoinError("模型服务限流或额度不足，请稍后重试") from exc
        except openai.APITimeoutError as exc:
            raise YoinError("模型请求超时，请检查服务状态") from exc
        except openai.APIConnectionError as exc:
            raise YoinError("无法连接模型服务，请检查服务地址和网络") from exc
        except openai.BadRequestError as exc:
            raise YoinError("模型服务不接受当前请求，请检查模型是否支持工具调用") from exc
        except openai.APIStatusError as exc:
            raise YoinError(f"模型服务返回 HTTP {exc.status_code} 错误") from exc
        except (openai.OpenAIError, ValueError) as exc:
            raise YoinError("模型客户端无法解析服务响应，请检查兼容接口配置") from exc

    def close(self) -> None:
        self._client.close()


def create_model():
    """完整 API 配置优先；未配置 API 时复用本机 Codex。可用 YOIN_PROVIDER 显式选择。"""
    provider = os.environ.get("YOIN_PROVIDER", "auto").strip().lower()
    if provider == "auto":
        provider = "api" if any(os.environ.get(name) for name in ("YOIN_API_KEY", "YOIN_BASE_URL", "YOIN_MODEL")) else "codex"
    if provider == "api":
        config = ModelConfig.from_env()
        return ChatModel(config), {"provider": "api", **config.public_info()}
    if provider == "codex":
        from .codex_model import CodexModel
        model = CodexModel()
        return model, model.public_info()
    raise YoinError("YOIN_PROVIDER 只能是 auto、codex 或 api")
