import asyncio
import json

import pytest

from app.llm.fake import FakeLLM
from app.pipeline.classify import classify_report

NOTE = "Valve V-12 stuck briefly during chilldown."


async def classify(reply, **kwargs):
    llm = FakeLLM({"classify": reply}, **kwargs.pop("llm_kwargs", {}))
    sorting, step = await classify_report(llm, station="PROP-2", note=NOTE, **kwargs)
    return sorting, step, llm


async def test_valid_reply_is_used():
    reply = json.dumps({"subsystem": "propulsion", "severity": "medium"})
    sorting, step, _ = await classify(reply)
    assert (sorting.subsystem, sorting.severity, sorting.fallback_used) == (
        "propulsion",
        "medium",
        False,
    )
    assert step.fallback_used is False
    assert step.kind == "model"


async def test_reply_wrapped_in_a_code_fence_is_accepted():
    reply = '```json\n{"subsystem": "telemetry", "severity": "low"}\n```'
    sorting, _, _ = await classify(reply)
    assert (sorting.subsystem, sorting.severity) == ("telemetry", "low")


@pytest.mark.parametrize(
    "reply",
    [
        json.dumps({"subsystem": "propulsion", "severity": "catastrophic"}),  # bad severity
        json.dumps({"subsystem": "warp_drive", "severity": "low"}),  # bad subsystem
        json.dumps({"subsystem": "propulsion"}),  # missing field
        "I think this is a propulsion issue.",  # not JSON
        "",
    ],
)
async def test_invalid_reply_falls_back_to_unknown_and_high(reply):
    sorting, step, _ = await classify(reply)
    assert (sorting.subsystem, sorting.severity, sorting.fallback_used) == ("unknown", "high", True)
    assert step.fallback_used is True
    assert step.error == "invalid model output"
    assert step.output["raw"] == reply
    assert step.output["fallback"] == {"subsystem": "unknown", "severity": "high"}


async def test_model_error_falls_back_instead_of_raising():
    sorting, step, _ = await classify(RuntimeError("429 rate limited"))
    assert (sorting.subsystem, sorting.severity) == ("unknown", "high")
    assert step.fallback_used is True
    assert "429 rate limited" in step.error
    assert step.cost_usd == 0


async def test_model_timeout_falls_back():
    reply = json.dumps({"subsystem": "propulsion", "severity": "low"})
    sorting, step, _ = await classify(reply, llm_kwargs={"delay": 0.2}, timeout=0.01)
    assert (sorting.subsystem, sorting.severity) == ("unknown", "high")
    assert asyncio.TimeoutError.__name__ in step.error


async def test_call_asks_for_a_structured_schema_and_wraps_the_note():
    reply = json.dumps({"subsystem": "propulsion", "severity": "medium"})
    _, step, llm = await classify(reply)
    call = llm.calls_for("classify")[0]
    assert call.tier == "fast"
    assert set(call.json_schema["properties"]) == {"subsystem", "severity"}
    assert f"<engineer_note>\n{NOTE}\n</engineer_note>" in call.user
    assert "untrusted" in call.system
    assert (step.input_tokens, step.output_tokens) == (100, 50)
    assert step.cost_usd > 0
