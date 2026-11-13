"""Run one model call safely and record it for the trace.

Model output is never trusted: a reply is validated here, and a call that
errors, times out, or returns an invalid reply yields `None` so the caller
applies its safe fallback. Nothing a model does can raise out of this function.
"""

import asyncio
import re
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.cost import step_cost
from app.llm.base import LLMClient, Tier
from app.pipeline.trace import StepRecord

MODEL_TIMEOUT_SECONDS = 30.0

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1) if match else text


async def _call(
    llm: LLMClient,
    *,
    name: str,
    purpose: str,
    tier: Tier,
    system: str,
    user: str,
    json_schema: dict | None,
    timeout: float,
) -> tuple[str | None, StepRecord]:
    record = StepRecord(name=name, kind="model")
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            llm.complete(
                purpose=purpose, tier=tier, system=system, user=user, json_schema=json_schema
            ),
            timeout,
        )
    except Exception as exc:  # timeouts, rate limits, network errors: all fall back
        record.latency_ms = round((time.perf_counter() - started) * 1000)
        record.fallback_used = True
        record.error = f"model call failed: {type(exc).__name__}: {exc}".rstrip(": ")
        return None, record

    record.latency_ms = round((time.perf_counter() - started) * 1000)
    record.model = result.model
    record.input_tokens = result.input_tokens
    record.output_tokens = result.output_tokens
    record.cost_usd = step_cost(result.model, result.input_tokens, result.output_tokens)
    return result.text, record


async def run_structured_step[T: BaseModel](
    llm: LLMClient,
    *,
    name: str,
    purpose: str,
    tier: Tier,
    system: str,
    user: str,
    reply_model: type[T],
    timeout: float = MODEL_TIMEOUT_SECONDS,
) -> tuple[T | None, StepRecord]:
    """Ask for a JSON reply shaped like `reply_model` and validate it in code."""
    text, record = await _call(
        llm,
        name=name,
        purpose=purpose,
        tier=tier,
        system=system,
        user=user,
        json_schema=reply_model.model_json_schema(),
        timeout=timeout,
    )
    if text is None:
        return None, record
    try:
        parsed = reply_model.model_validate_json(_strip_code_fence(text))
    except ValidationError:
        record.fallback_used = True
        record.error = "invalid model output"
        record.output = {"raw": text}
        return None, record
    record.output = parsed.model_dump()
    return parsed, record


async def run_text_step(
    llm: LLMClient,
    *,
    name: str,
    purpose: str,
    tier: Tier,
    system: str,
    user: str,
    timeout: float = MODEL_TIMEOUT_SECONDS,
) -> tuple[str | None, StepRecord]:
    """Ask for a free-text reply. An empty reply counts as invalid."""
    text, record = await _call(
        llm,
        name=name,
        purpose=purpose,
        tier=tier,
        system=system,
        user=user,
        json_schema=None,
        timeout=timeout,
    )
    if text is None:
        return None, record
    if not text.strip():
        record.fallback_used = True
        record.error = "invalid model output"
        record.output = {"raw": text}
        return None, record
    record.output = {"text": text.strip()}
    return text.strip(), record
