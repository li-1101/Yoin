"""python -m yoin.run：中文场景到配方、音频和完整过程。"""

from .agent import run_agent
from .cli import ChineseArgumentParser, run_cli
from .config import project_root
from .model import create_model


def main() -> int:
    parser = ChineseArgumentParser(description="用 Yoin agent 调配专注背景声音")
    parser.add_argument("request", help="中文场景描述")
    parser.add_argument("--from", dest="from_run", help="从已有运行编号继续微调")
    args = parser.parse_args()

    def action():
        model, model_info = create_model()
        try:
            final = run_agent(args.request, project_root(), model.complete, model_info=model_info, from_run=args.from_run)
        finally:
            model.close()
        state = "模型已提交" if final["submitted"] else "未主动提交，已保存最后有效配方"
        print(f"{state}\n运行：{final['run_id']}\n音频：{final['audio_file']}\n解释：{final['explanation_file']}")

    return run_cli(action)


if __name__ == "__main__":
    raise SystemExit(main())
