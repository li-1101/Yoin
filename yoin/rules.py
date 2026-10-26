"""可编辑的混音规则；数值测量与审美建议分离。"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from .config import SAMPLE_RATE, read_json
from .schema import DataModel, chinese_validation_error

Nonnegative = Annotated[float, Field(ge=0, strict=True)]
Band = tuple[Nonnegative, Nonnegative]


class FrequencyBands(DataModel):
    low: Band = (20.0, 250.0)
    mid: Band = (250.0, 4000.0)
    high: Band = (4000.0, 16000.0)

    @model_validator(mode="after")
    def check_ranges(self):
        previous_high = 0
        for low, high in (self.low, self.mid, self.high):
            if not previous_high <= low < high <= SAMPLE_RATE / 2:
                raise ValueError("频段必须递增、互不重叠，且满足 0 ≤ 下限 < 上限 ≤ 24000 Hz")
            previous_high = high
        return self


class CheckOptions(DataModel):
    enabled: Annotated[bool, Field(strict=True)] = True
    severity: Literal["info", "warning"] = "warning"


class Checks(DataModel):
    masking: CheckOptions = Field(default_factory=CheckOptions)
    dominance: CheckOptions = Field(default_factory=CheckOptions)
    layer_count: CheckOptions = Field(default_factory=CheckOptions)
    event_rate: CheckOptions = Field(default_factory=CheckOptions)
    stereo_imbalance: CheckOptions = Field(default_factory=CheckOptions)


class MixingRules(DataModel):
    target_lufs: Annotated[float, Field(lt=0, strict=True)] = -24.0
    max_layers: Annotated[int, Field(ge=1, strict=True)] = 5
    masking_db: Nonnegative = 6.0
    dominance_share_pct: Annotated[float, Field(ge=0, le=100, strict=True)] = 80.0
    max_event_rate_focus: Nonnegative = 6.0
    stereo_imbalance_db: Nonnegative = 6.0
    bands_hz: FrequencyBands = Field(default_factory=FrequencyBands)
    checks: Checks = Field(default_factory=Checks)


def load_rules(path: Path | str) -> MixingRules:
    try:
        return MixingRules.model_validate(read_json(Path(path)))
    except ValidationError as exc:
        raise chinese_validation_error(exc, "混音规则") from exc
