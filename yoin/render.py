"""python -m yoin.render：不经过大模型的配方试听命令。"""

from pathlib import Path

import soundfile as sf

from .cli import ChineseArgumentParser, run_cli, seconds_argument
from .config import project_root, read_json, target_lufs
from .errors import YoinError
from .library import load_library
from .renderer import render


def main() -> int:
    parser = ChineseArgumentParser(description="根据配方离线生成 Yoin 立体声 WAV")
    parser.add_argument("recipe", type=Path, help="配方 JSON 路径")
    parser.add_argument("--seconds", type=seconds_argument, default=30, help="时长，1–300 秒，默认 30")
    parser.add_argument("--out", type=Path, required=True, help="输出 WAV 路径")
    args = parser.parse_args()

    def action():
        root = project_root()
        if args.out.suffix.lower() != ".wav":
            raise YoinError("输出文件必须使用 .wav 后缀")
        recipe_path, output_path = args.recipe.resolve(), args.out.resolve()
        if output_path == recipe_path:
            raise YoinError("输出路径不能覆盖配方文件")
        library = load_library(root / "library.json")
        if any(output_path == (library.root / sound.file).resolve() for sound in library.sounds.values()):
            raise YoinError("输出路径不能覆盖声音库素材")
        result = render(read_json(recipe_path), library, args.seconds, target_lufs=target_lufs(root))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        try:
            sf.write(args.out, result.audio, result.sample_rate, subtype="FLOAT", format="WAV")
        except (RuntimeError, OSError) as exc:
            raise YoinError(f"无法写入 WAV：{args.out}") from exc
        loudness = f"{result.loudness_lufs:.1f} LUFS" if result.loudness_lufs is not None else "无法测量（静音或低于门限）"
        print(f"已生成：{args.out}\n时长：{args.seconds} 秒；采样率：{result.sample_rate} Hz；响度：{loudness}")

    return run_cli(action)


if __name__ == "__main__":
    raise SystemExit(main())
