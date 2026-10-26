"""项目路径和 v0 的运行约定。"""

import json
import os
from pathlib import Path

from .errors import YoinError

SAMPLE_RATE = 48_000
MAX_SECONDS = 300
RENDERER_VERSION = "yoin-renderer-0.1"


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
