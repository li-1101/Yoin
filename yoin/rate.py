"""python -m yoin.rate：追加保存初稿或终稿的评分。"""

import argparse

from .cli import ChineseArgumentParser, run_cli
from .config import project_root
from .runs import RunStore


def _which(value):
    if value not in {"draft", "final"}:
        raise argparse.ArgumentTypeError("试听版本必须是 draft 或 final")
    return value


def _score(value):
    try:
        score = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("评分必须是 1–5 的整数") from exc
    if not 1 <= score <= 5:
        raise argparse.ArgumentTypeError("评分必须在 1–5 之间")
    return score


def main() -> int:
    parser = ChineseArgumentParser(description="记录 Yoin 初稿或终稿的试听评分")
    parser.add_argument("run_id", help="运行编号")
    parser.add_argument("--which", type=_which, required=True, help="draft 为初稿，final 为终稿")
    parser.add_argument("--score", type=_score, required=True, help="1–5 分")
    parser.add_argument("--note", default="", help="可选的试听备注")
    args = parser.parse_args()

    def action():
        record = RunStore(project_root()).rate(args.run_id, {"which": args.which, "score": args.score, "note": args.note})
        print(f"已记录：{record['run_id']}，{record['which']}，{record['score']} 分")

    return run_cli(action)


if __name__ == "__main__":
    raise SystemExit(main())
