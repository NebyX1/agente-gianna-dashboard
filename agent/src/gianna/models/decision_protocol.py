import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def distribution(self):
        if self.choice not in self.probabilities or not all(
            math.isfinite(v) and 0 <= v <= 1 for v in self.probabilities.values()
        ):
            raise ValueError("Invalid choice distribution")
        if abs(sum(self.probabilities.values()) - 1) > 0.025:
            raise ValueError("Distribution does not sum to one")
        return self


class Noul(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1, allow_inf_nan=False)


class Score(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["score"]
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def finite(self):
        if (
            not all(math.isfinite(v) and 0 <= v <= 1 for v in self.probabilities.values())
            or abs(sum(self.probabilities.values()) - 1) > 0.025
        ):
            raise ValueError("Invalid score distribution")
        return self
