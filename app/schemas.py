"""Shared data shapes: form input, model replies, and enums."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["low", "medium", "high"]
Verdict = Literal["go", "no_go"]
Subsystem = Literal[
    "propulsion", "avionics", "telemetry", "ground_systems", "weather", "structures", "other"
]


class Readings(BaseModel):
    """The three numbers the launch limits are checked against. Nothing else."""

    model_config = ConfigDict(frozen=True)

    wind_knots: float
    temp_c: float
    fuel_pct: float


class Violation(BaseModel):
    field: str
    value: float
    rule: str
    limit: float


class LimitResult(BaseModel):
    verdict: Verdict
    violations: list[Violation] = Field(default_factory=list)
