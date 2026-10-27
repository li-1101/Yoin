"""把可编辑提示词、完整声音资料和少量模板编入本轮上下文。"""

import json
from dataclasses import dataclass
from pathlib import Path

from .config import read_json
from .errors import YoinError
from .library import SoundLibrary
from .rules import MixingRules
from .schema import validate_recipe


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise YoinError(f"无法读取设计说明：{path}") from exc


@dataclass
class PromptContext:
    system_prompt: str
    guidance: dict[str, str]
    templates: list[dict]


def build_prompt(root: Path, library: SoundLibrary, rules: MixingRules) -> PromptContext:
    base = read_text(root / "prompts" / "system.md")
    guidance = {path.name: read_text(path) for path in sorted((root / "guidance").glob("*.md"))}
    templates = []
    for path in sorted((root / "templates").glob("*.recipe.json")):
        template_id = path.name.removesuffix(".recipe.json")
        description = read_text(path.with_name(template_id + ".md"))
        recipe = validate_recipe(read_json(path), library.sounds)
        templates.append({"id": template_id, "description": description,
                          "recipe": recipe.model_dump(exclude_none=True)})
    catalog = [sound.model_dump(exclude_none=True) for sound in library.sounds.values()]
    parts = [base, "\n完整声音目录：", json.dumps(catalog, ensure_ascii=False),
             "\n本轮混音规则（建议不是提交门槛）：", rules.model_dump_json()]
    for name, text in guidance.items():
        parts.extend((f"\n设计指导 {name}：", text))
    if templates:
        parts.extend(("\n参考模板（请生成具体配方）：", json.dumps(templates, ensure_ascii=False)))
    return PromptContext("\n".join(parts), guidance, templates)
