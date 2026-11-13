"""Shared data shapes: form input, model replies, and enums."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

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


class Classification(BaseModel):
    """The model's sorting reply. Any other value fails validation."""

    subsystem: Subsystem
    severity: Severity


class CheckResult(BaseModel):
    """One screening check's reply: was it flagged, and why."""

    flagged: StrictBool
    reason: str = ""


class Review(BaseModel):
    """The evaluator's reply on a draft briefing."""

    approved: StrictBool
    feedback: str = ""


# Sanity ranges for the form are deliberately wider than the launch limits:
# an out-of-limit reading (fuel 100.1) must be accepted and then judged no_go.
class ReportIn(BaseModel):
    """A report as filed by an engineer."""

    model_config = ConfigDict(str_strip_whitespace=True)

    engineer_name: str = Field(min_length=1, max_length=80)
    station: str = Field(min_length=1, max_length=40)
    wind_knots: float = Field(strict=True, ge=0, le=300, allow_inf_nan=False)
    temp_c: float = Field(strict=True, ge=-100, le=100, allow_inf_nan=False)
    fuel_pct: float = Field(strict=True, ge=0, le=150, allow_inf_nan=False)
    note: str = Field(min_length=1, max_length=2000)

    def readings(self) -> Readings:
        return Readings(wind_knots=self.wind_knots, temp_c=self.temp_c, fuel_pct=self.fuel_pct)


class ApproveIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    approver_name: str = Field(min_length=1, max_length=80)
