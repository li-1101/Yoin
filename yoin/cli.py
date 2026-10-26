"""命令行共用的中文错误处理。"""

import argparse
import re
import sys
from collections.abc import Callable

from .config import MAX_SECONDS
from .errors import YoinError


class ChineseArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, allow_abbrev=False, **kwargs)
        self.add_argument("-h", "--help", action="help", help="显示帮助并退出")
        self._positionals.title = "位置参数"
        self._optionals.title = "可选参数"

    def format_usage(self):
        return super().format_usage().replace("usage:", "用法:", 1)

    def format_help(self):
        return super().format_help().replace("usage:", "用法:", 1)

    def error(self, message):
        message = message.replace("the following arguments are required:", "缺少必填参数：")
        message = message.replace("unrecognized arguments:", "无法识别的参数：")
        message = message.replace("expected one argument", "需要提供一个值")
        message = message.replace("ignored explicit argument", "此开关不接受值")
        message = re.sub(r"\bargument\b", "参数", message)
        self.print_usage(sys.stderr)
        self.exit(2, f"参数错误：{message}\n")


def seconds_argument(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("时长必须是整数") from exc
    if not 1 <= seconds <= MAX_SECONDS:
        raise argparse.ArgumentTypeError(f"时长必须在 1–{MAX_SECONDS} 秒之间")
    return seconds


def run_cli(action: Callable[[], None]) -> int:
    try:
        action()
    except YoinError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except OSError:
        print("错误：无法写入输出，请检查目标路径、权限和磁盘空间", file=sys.stderr)
        return 2
    return 0
