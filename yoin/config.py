"""项目路径和 v0 的运行约定。"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .errors import YoinError

SAMPLE_RATE = 48_000
MAX_SECONDS = 300
RENDERER_VERSION = "yoin-renderer-0.1"
MAX_STEPS = 8
MAX_PREVIEWS = 4


def project_root() -> Path:
    return Path(os.environ.get("YOIN_PROJECT_DIR", Path.cwd())).expanduser().resolve()


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise YoinError(f"找不到文件：{path}") from exc
    except (OSError, UnicodeError) as exc:
        raise YoinError(f"无法读取文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise YoinError(f"JSON 格式错误：{path}，第 {exc.lineno} 行第 {exc.colno} 列") from exc


@dataclass(frozen=True)
class ModelConfig:
    api_key: str = field(repr=False)
    base_url: str = field(repr=False)
    model: str

    @classmethod
    def from_env(cls):
        names = ("YOIN_API_KEY", "YOIN_BASE_URL", "YOIN_MODEL")
        values = [os.environ.get(name, "").strip() for name in names]
        missing = [name for name, value in zip(names, values) if not value]
        if missing:
            raise YoinError("缺少模型环境变量：" + "、".join(missing))
        config = cls(*values)
        config.public_info()  # 在开始运行前校验 URL，同时避免把带凭据的 URL 记入日志。
        return config

    def public_info(self) -> dict:
        try:
            url = urlsplit(self.base_url)
            if url.scheme not in {"http", "https"} or not url.hostname:
                raise ValueError
            host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
            if url.port is not None:
                host += f":{url.port}"
            public_url = urlunsplit((url.scheme, host, url.path, "", ""))
        except ValueError as exc:
            raise YoinError("YOIN_BASE_URL 必须是有效的 HTTP(S) 服务地址") from exc
        return {"model": self.model, "base_url": public_url}
