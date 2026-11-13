"""Sort a report by subsystem and severity with a model, validated in code."""

from dataclasses import dataclass

from app.llm.base import LLMClient
from app.pipeline.model_step import MODEL_TIMEOUT_SECONDS, run_structured_step
from app.pipeline.trace import StepRecord
from app.prompts import classify_prompt
from app.schemas import Classification, Severity

FALLBACK_SUBSYSTEM = "unknown"
FALLBACK_SEVERITY: Severity = "high"


@dataclass(frozen=True)
class Sorting:
    subsystem: str
    severity: Severity
    fallback_used: bool


async def classify_report(
    llm: LLMClient, *, station: str, note: str, timeout: float = MODEL_TIMEOUT_SECONDS
) -> tuple[Sorting, StepRecord]:
    """Return the model's sorting, or unknown/high if its reply cannot be trusted."""
    system, user = classify_prompt(station, note)
    parsed, step = await run_structured_step(
        llm,
        name="classify",
        purpose="classify",
        tier="fast",
        system=system,
        user=user,
        reply_model=Classification,
        timeout=timeout,
    )
    if parsed is None:
        sorting = Sorting(FALLBACK_SUBSYSTEM, FALLBACK_SEVERITY, fallback_used=True)
        step.output = {
            **(step.output or {}),
            "fallback": {"subsystem": sorting.subsystem, "severity": sorting.severity},
        }
    else:
        sorting = Sorting(parsed.subsystem, parsed.severity, fallback_used=False)
    return sorting, step
