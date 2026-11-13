"""Three screening checks on the note, run at the same time.

Hidden instructions are looked for twice: by a model, and by fixed patterns in
code. Either one flags the report, so a model that is fooled by the note
cannot clear the flag.
"""

import asyncio
import re

from app.llm.base import LLMClient
from app.pipeline.model_step import MODEL_TIMEOUT_SECONDS, run_structured_step
from app.pipeline.trace import StepRecord
from app.prompts import check_prompt
from app.schemas import CheckResult

CHECK_NAMES = ("injection", "missing_details", "panic")

_INSTRUCTION_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"\b(ignore|disregard|forget)\b.{0,40}"
        r"\b(instructions?|limits?|rules?|previous|above|prior|checks?)\b",
        r"\b(system|admin|administrator|developer)\s+(override|prompt|message|instructions?)\b",
        r"\boverride\b.{0,40}\b(verdict|limits?|severity|rules?|safety|checks?)\b",
        r"\b(set|mark|change|force|report|make)\b.{0,30}\b(verdict|severity|status)\b",
        r"\byou\s+(must|should|will|are\s+to)\b.{0,40}"
        r"\b(approve|ignore|disregard|classify|respond|output|say)\b",
        r"\b(auto-?approve|approve\s+(this|the)\s+(briefing|report))\b",
        r"\bnew\s+instructions?\b",
    )
]


def scan_note_for_instructions(note: str) -> list[str]:
    """Return the phrases in the note that look like instructions to the system."""
    hits: list[str] = []
    for pattern in _INSTRUCTION_PATTERNS:
        match = pattern.search(note)
        if match:
            hits.append(" ".join(match.group(0).split()))
    return hits


def combine_injection(model_result: CheckResult, rule_hits: list[str]) -> CheckResult:
    """Flag if either the model or the code patterns found instructions."""
    if not rule_hits:
        return model_result
    quoted = "; ".join(f'"{hit}"' for hit in rule_hits)
    reason = f"Instruction-like text found by pattern match: {quoted}."
    if model_result.flagged and model_result.reason:
        reason = f"{model_result.reason} {reason}"
    return CheckResult(flagged=True, reason=reason)


async def _run_check(
    llm: LLMClient, check: str, note: str, timeout: float
) -> tuple[CheckResult, StepRecord]:
    system, user = check_prompt(check, note)
    parsed, step = await run_structured_step(
        llm,
        name=f"check_{check}",
        purpose=f"check_{check}",
        tier="fast",
        system=system,
        user=user,
        reply_model=CheckResult,
        timeout=timeout,
    )
    if parsed is None:
        # Fail safe: a check that could not answer counts as flagged.
        parsed = CheckResult(flagged=True, reason=step.error or "invalid model output")
        step.output = {**(step.output or {}), "fallback": parsed.model_dump()}
    return parsed, step


async def run_checks(
    llm: LLMClient, note: str, timeout: float = MODEL_TIMEOUT_SECONDS
) -> tuple[dict[str, CheckResult], list[StepRecord]]:
    """Run the three model checks concurrently. One failing never stops the others."""
    outcomes = await asyncio.gather(
        *(_run_check(llm, check, note, timeout) for check in CHECK_NAMES)
    )
    results = {check: result for check, (result, _) in zip(CHECK_NAMES, outcomes, strict=True)}
    steps = [step for _, step in outcomes]
    return results, steps
