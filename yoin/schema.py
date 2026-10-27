"""配方和声音描述；跨声音库的约束在 validate_recipe 中统一检查。"""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from .errors import YoinError

UnitFloat = Annotated[float, Field(ge=0, le=1, strict=True)]
PanFloat = Annotated[float, Field(ge=-1, le=1, strict=True)]
NonemptyString = Annotated[str, Field(min_length=1)]


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Sound(DataModel):
    id: NonemptyString
    name: NonemptyString
    description: NonemptyString
    kind: Literal["loop", "event"]
    channels: Literal["mono", "stereo"]
    file: NonemptyString
    tags: list[str] = Field(default_factory=list)
    mood: list[str] = Field(default_factory=list)
    good_for: list[str] = Field(default_factory=list)
    placeholder: bool = False
    source: str = ""
    license: str = ""
    gain_db: Annotated[float, Field(ge=-60, le=24, strict=True)] = 0.0
    tonal: bool | None = None
    musical_key: str | None = None
    bpm: Annotated[float, Field(gt=0, strict=True)] | None = None


class Layer(DataModel):
    layer_id: NonemptyString | None = None
    sound_id: NonemptyString
    volume: UnitFloat
    pan: PanFloat
    distance: UnitFloat
    brightness: UnitFloat
    events_per_minute: Annotated[float, Field(ge=0, le=30, strict=True)] | None = None
    randomness: UnitFloat | None = None


class Room(DataModel):
    type: Literal["none", "small_room", "wooden_cabin", "hall"]
    amount: UnitFloat


class Recipe(DataModel):
    schema_version: Literal[1] = 1
    title: NonemptyString
    seed: StrictInt
    layers: list[Layer] = Field(min_length=1)
    room: Room

    @model_validator(mode="after")
    def assign_layer_ids(self):
        used = {layer.layer_id for layer in self.layers if layer.layer_id is not None}
        explicit = [layer.layer_id for layer in self.layers if layer.layer_id is not None]
        if len(explicit) != len(used):
            raise ValueError("layer_id 必须唯一")
        for layer in self.layers:
            if layer.layer_id is not None:
                continue
            candidate = layer.sound_id
            suffix = 1
            while candidate in used:
                suffix += 1
                candidate = f"{layer.sound_id}_{suffix}"
            layer.layer_id = candidate
            used.add(candidate)
        return self


def chinese_validation_error(exc: ValidationError, label: str) -> YoinError:
    messages = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"])
        kind, context = error["type"], error.get("ctx", {})
        if kind == "missing":
            message = "此字段必填"
        elif kind == "greater_than_equal":
            message = f"必须大于或等于 {context['ge']}"
        elif kind == "less_than_equal":
            message = f"必须小于或等于 {context['le']}"
        elif kind == "greater_than":
            message = f"必须大于 {context['gt']}"
        elif kind == "less_than":
            message = f"必须小于 {context['lt']}"
        elif kind == "literal_error":
            message = "取值不在允许范围内"
        elif kind == "extra_forbidden":
            message = "不支持此字段"
        elif kind == "value_error":
            message = str(context.get("error", "字段组合无效"))
        elif kind in {"float_type", "float_parsing", "finite_number"}:
            message = "必须是有限数值"
        elif kind in {"int_type", "int_parsing", "int_from_float"}:
            message = "必须是整数"
        elif kind in {"string_type", "string_too_short"}:
            message = "必须是非空字符串"
        elif kind == "string_too_long":
            message = f"长度不能超过 {context['max_length']} 个字符"
        elif kind in {"list_type", "too_short"}:
            message = "必须是非空列表"
        elif kind in {"bool_type", "bool_parsing"}:
            message = "必须是真或假"
        else:
            message = "数据类型或结构不正确"
        messages.append(f"{location or label}：{message}")
    return YoinError(f"{label}校验失败：" + "；".join(messages))


def validate_recipe(data: Recipe | dict, sounds: Mapping[str, Sound]) -> Recipe:
    try:
        # 即使调用方传入模型，也重新校验，防止模型创建后被改成非法状态。
        recipe = Recipe.model_validate(data.model_dump() if isinstance(data, Recipe) else data)
    except ValidationError as exc:
        raise chinese_validation_error(exc, "配方") from exc
    for layer in recipe.layers:
        sound = sounds.get(layer.sound_id)
        if sound is None:
            raise YoinError(f"声音不存在：{layer.sound_id}，请使用 library.json 中的 sound_id")
        if sound.kind == "event":
            if layer.events_per_minute is None:
                raise YoinError(f"偶发声音『{layer.sound_id}』必须填写 events_per_minute")
            if layer.randomness is None:
                layer.randomness = 0.5
        elif layer.events_per_minute is not None or layer.randomness is not None:
            raise YoinError(f"循环声音『{layer.sound_id}』不能填写 events_per_minute 或 randomness")
    return recipe
