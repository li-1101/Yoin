"""本机模型配置：私有持久化、公开状态和固定的一次运行选择。"""

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator

from .config import ModelConfig
from .errors import YoinError
from .schema import DataModel, chinese_validation_error

ApiProvider = Literal["claude", "openai", "deepseek"]
Provider = Literal["claude", "openai", "deepseek", "codex", "environment"]
DEFAULTS = {
    "claude": {"label": "Claude（CC）", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5-5"},
    "openai": {"label": "GPT", "base_url": "https://api.openai.com/v1", "model": "gpt-5-mini"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
}
LABELS = {**{key: value["label"] for key, value in DEFAULTS.items()},
          "codex": "本机 Codex", "environment": "原有环境配置"}


class Profile(DataModel):
    api_key: Annotated[str, Field(min_length=1, max_length=4096, repr=False)]
    base_url: Annotated[str, Field(min_length=1, max_length=2000)]
    model: Annotated[str, Field(min_length=1, max_length=160)]

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value):
        if not value.isascii() or any(character.isspace() or ord(character) < 33 for character in value):
            raise ValueError("API Key 不能包含空格、换行或非 ASCII 字符")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        try:
            url = urlsplit(value)
            if (url.scheme not in {"http", "https"} or not url.hostname
                    or url.username is not None or url.password is not None or url.query or url.fragment
                    or any(character.isspace() for character in value)):
                raise ValueError
            url.port
        except ValueError as exc:
            raise ValueError("服务地址须为 HTTP(S) 地址，不能包含账户、密码、查询参数或片段") from exc
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def valid_model(cls, value):
        if any(character.isspace() for character in value):
            raise ValueError("模型名称不能包含空格或换行")
        return value


class Settings(DataModel):
    version: Literal[1] = 1
    active: Provider = "environment"
    profiles: dict[ApiProvider, Profile] = Field(default_factory=dict)


class SaveConnection(DataModel):
    provider: ApiProvider
    api_key: Annotated[str | None, Field(max_length=4096, repr=False)] = None
    base_url: Annotated[str, Field(max_length=2000)] | None = None
    model: Annotated[str, Field(max_length=160)] | None = None


class SelectConnection(DataModel):
    provider: ApiProvider


@dataclass(frozen=True)
class ConnectionChoice:
    provider: str
    config: ModelConfig | None = None

    def create_model(self):
        if self.provider == "environment":
            from .model import create_model
            return create_model()
        if self.provider == "codex":
            from .codex_model import CodexModel
            model = CodexModel()
            return model, model.public_info()
        if self.provider == "claude":
            from .claude_model import ClaudeModel
            model = ClaudeModel(self.config)
        else:
            from .model import ChatModel
            extra = {"thinking": {"type": "disabled"}} if self.provider == "deepseek" else None
            model = ChatModel(self.config, extra_body=extra)
        return model, {"provider": self.provider, "label": LABELS[self.provider], **self.config.public_info()}


class ConnectionStore:
    _lock = threading.RLock()

    def __init__(self, root: Path | str):
        self.directory = Path(root).resolve() / ".yoin"
        self.path = self.directory / "connections.json"

    def _read(self) -> Settings:
        if self.directory.is_symlink() or self.path.is_symlink():
            raise YoinError("模型配置目录或文件不能是符号链接")
        if not self.path.exists():
            return Settings()
        try:
            return Settings.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError) as exc:
            raise YoinError("无法读取本地模型配置，请检查 .yoin/connections.json") from exc

    def _write(self, settings: Settings):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix="connections-", delete=False) as file:
                temporary = Path(file.name)
                os.fchmod(file.fileno(), 0o600)
                file.write(settings.model_dump_json(indent=2) + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise YoinError("无法保存本地模型配置，请检查目录权限与磁盘空间") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def public(self) -> dict:
        with self._lock:
            settings = self._read()
        profiles = []
        for provider, defaults in DEFAULTS.items():
            profile = settings.profiles.get(provider)
            profiles.append({"provider": provider, **defaults, "configured": profile is not None,
                             "base_url": profile.base_url if profile else defaults["base_url"],
                             "model": profile.model if profile else defaults["model"]})
        active = settings.active if settings.active in DEFAULTS else "openai"
        return {"active": active, "active_label": LABELS[active] + " · API Key", "profiles": profiles}

    def save(self, data: dict) -> dict:
        try:
            request = SaveConnection.model_validate(data)
            with self._lock:
                settings = self._read()
                previous = settings.profiles.get(request.provider)
                defaults = DEFAULTS[request.provider]
                values = {key: getattr(request, key) if getattr(request, key) is not None
                          else getattr(previous, key) if previous else defaults.get(key, "")
                          for key in ("api_key", "base_url", "model")}
                # 空白密钥表示沿用已保存的密钥，页面从不回填它。
                if not values["api_key"]:
                    values["api_key"] = previous.api_key if previous else ""
                if request.provider == "claude":
                    values["base_url"] = values["base_url"].rstrip("/").removesuffix("/v1")
                settings.profiles[request.provider] = Profile.model_validate(values)
                self._write(settings)
        except ValidationError as exc:
            raise chinese_validation_error(exc, "模型配置") from exc
        return self.public()

    def select(self, data: dict) -> dict:
        try:
            request = SelectConnection.model_validate(data)
        except ValidationError as exc:
            raise chinese_validation_error(exc, "模型选择") from exc
        with self._lock:
            settings = self._read()
            if request.provider not in settings.profiles:
                raise YoinError("请先保存这家的 API Key")
            settings.active = request.provider
            self._write(settings)
        return self.public()

    def delete(self, data: dict) -> dict:
        try:
            request = SaveConnection.model_validate(data)
            if set(data) != {"provider"}:
                raise YoinError("删除连接时只需提供 provider")
        except ValidationError as exc:
            raise chinese_validation_error(exc, "模型配置") from exc
        with self._lock:
            settings = self._read()
            settings.profiles.pop(request.provider, None)
            if settings.active == request.provider:
                settings.active = "openai"
            self._write(settings)
        return self.public()

    def choice(self, provider: str | None = None, *, api_only: bool = False) -> ConnectionChoice:
        """网页只使用 API Key；CLI 仍可读取历史环境选择。"""
        with self._lock:
            settings = self._read()
        provider = settings.active if provider is None else provider
        if provider not in LABELS:
            raise YoinError("不支持的模型入口")
        if api_only and provider not in DEFAULTS:
            provider = "openai"
        profile = settings.profiles.get(provider)
        if provider in DEFAULTS and profile is None:
            raise YoinError(f"请先在「模型设置」保存 {LABELS[provider]} 的 API Key，并使用此入口")
        config = ModelConfig(profile.api_key, profile.base_url, profile.model) if profile else None
        return ConnectionChoice(provider, config)

    def test(self, data: dict) -> dict:
        try:
            request = SelectConnection.model_validate(data)
        except ValidationError as exc:
            raise chinese_validation_error(exc, "连接测试") from exc
        choice = self.choice(request.provider)
        model, _ = choice.create_model()
        try:
            check = {"type": "function", "function": {"name": "yoin_connection_check",
                     "description": "验证工具调用连接，不执行任何操作。",
                     "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                    "required": ["ok"], "additionalProperties": False}}}
            response = model.complete([{"role": "user", "content":
                                       "只调用 yoin_connection_check，参数 ok=true，不要回复文字。"}], [check])
            try:
                calls = response["choices"][0]["message"]["tool_calls"]
                function = calls[0]["function"]
                arguments = json.loads(function["arguments"])
                valid = (len(calls) == 1 and function["name"] == "yoin_connection_check"
                         and isinstance(arguments, dict) and set(arguments) == {"ok"} and arguments["ok"] is True)
            except (KeyError, IndexError, TypeError, ValueError):
                valid = False
            if not valid:
                raise YoinError("模型已响应，但未通过工具调用检查；请确认模型支持工具调用后重试")
            return {"ok": True, "message": "连接与工具调用检查通过", "provider": request.provider}
        finally:
            model.close()
