"""python -m yoin.render：不经过大模型的配方试听命令。"""

from pathlib import Path

from .analysis import analyze
from .cli import ChineseArgumentParser, run_cli, seconds_argument
from .config import project_root, read_json
from .errors import YoinError
from .files import write_json, write_wav
from .library import load_library
from .renderer import render
from .rules import load_rules


def main() -> int:
    parser = ChineseArgumentParser(description="根据配方离线生成 Yoin 立体声 WAV")
    parser.add_argument("recipe", type=Path, help="配方 JSON 路径")
    parser.add_argument("--seconds", type=seconds_argument, default=30, help="时长，1–300 秒，默认 30")
    parser.add_argument("--out", type=Path, required=True, help="输出 WAV 路径")
    parser.add_argument("--analysis", type=Path, help="可选：保存测量与混音建议的 JSON 路径")
    args = parser.parse_args()

    def action():
        root = project_root()
        if args.out.suffix.lower() != ".wav":
            raise YoinError("输出文件必须使用 .wav 后缀")
        recipe_path, output_path = args.recipe.resolve(), args.out.resolve()
        if output_path == recipe_path:
            raise YoinError("输出路径不能覆盖配方文件")
        library = load_library(root / "library.json")
        sound_paths = {(library.root / sound.file).resolve() for sound in library.sounds.values()}
        if output_path in sound_paths:
            raise YoinError("输出路径不能覆盖声音库素材")
        if args.analysis is not None:
            protected = sound_paths | {recipe_path, output_path, root / "library.json", root / "mixing_rules.json"}
            if args.analysis.suffix.lower() != ".json" or args.analysis.resolve() in protected:
                raise YoinError("分析输出必须是 .json，且不能覆盖输入、素材、规则或音频输出")
        rules = load_rules(root / "mixing_rules.json")
        result = render(read_json(recipe_path), library, args.seconds, target_lufs=rules.target_lufs)
        report = analyze(result, rules) if args.analysis is not None else None
        write_wav(args.out, result.audio, result.sample_rate)
        if report is not None:
            write_json(args.analysis, report)
            print(f"分析已保存：{args.analysis}；混音建议：{len(report['warnings'])} 条")
        loudness = f"{result.loudness_lufs:.1f} LUFS" if result.loudness_lufs is not None else "无法测量（静音或低于门限）"
        print(f"已生成：{args.out}\n时长：{args.seconds} 秒；采样率：{result.sample_rate} Hz；响度：{loudness}")

    return run_cli(action)


if __name__ == "__main__":
    raise SystemExit(main())
