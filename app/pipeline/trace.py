"""One record per pipeline step; the console shows each as a trace card."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class StepRecord:
    name: str
    kind: Literal["code", "model"]
    started_at: str = field(default_factory=utc_now_iso)
    latency_ms: int = 0
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    output: Any = None
    fallback_used: bool = False
    error: str | None = None


def code_step(name: str, output: Any) -> StepRecord:
    """A step done by plain code: no model, no tokens, no cost."""
    return StepRecord(name=name, kind="code", output=output)
