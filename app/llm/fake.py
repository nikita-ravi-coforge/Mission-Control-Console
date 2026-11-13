"""A scripted stand-in for a real model: no network, no API key.

Used by every test, and by the app itself in FAKE MODEL MODE.
"""

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.llm.base import LLMResult, Tier

Reply = str | Exception | Callable[[str], str]


@dataclass
class FakeCall:
    purpose: str
    tier: Tier
    system: str
    user: str
    json_schema: dict | None
    started: float
    ended: float | None = None


class FakeLLM:
    """Replies come from `script`: {purpose: reply or list of replies}.

    A reply is a string, a callable taking the user prompt, or an exception to
    raise. A list is played in order and its last entry repeats. Purposes not in
    the script use a keyword-based default so the app is usable without a key.
    """

    mode = "fake"

    def __init__(
        self,
        script: dict[str, Reply | list[Reply]] | None = None,
        *,
        delay: float = 0.0,
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        self._script: dict[str, Reply | list[Reply]] = {**DEFAULT_SCRIPT, **(script or {})}
        self._position: dict[str, int] = {}
        self._delay = delay
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls: list[FakeCall] = []

    def calls_for(self, purpose: str) -> list[FakeCall]:
        return [call for call in self.calls if call.purpose == purpose]

    async def complete(
        self,
        *,
        purpose: str,
        tier: Tier,
        system: str,
        user: str,
        json_schema: dict | None = None,
    ) -> LLMResult:
        call = FakeCall(purpose, tier, system, user, json_schema, started=time.monotonic())
        self.calls.append(call)
        reply = self._next_reply(purpose)
        if self._delay:
            await asyncio.sleep(self._delay)
        call.ended = time.monotonic()

        if isinstance(reply, Exception):
            raise reply
        text = reply(user) if callable(reply) else reply
        return LLMResult(
            text=text,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            model=f"fake-{tier}",
        )

    def _next_reply(self, purpose: str) -> Reply:
        if purpose not in self._script:
            raise KeyError(f"FakeLLM has no reply scripted for purpose '{purpose}'")
        entry = self._script[purpose]
        if not isinstance(entry, list):
            return entry
        index = min(self._position.get(purpose, 0), len(entry) - 1)
        self._position[purpose] = index + 1
        return entry[index]


# --- Default replies, so FAKE MODEL MODE behaves plausibly in the console ---


def _note(user_prompt: str) -> str:
    match = re.search(r"<engineer_note>(.*?)</engineer_note>", user_prompt, re.DOTALL)
    return (match.group(1) if match else user_prompt).strip()


def _has(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def _default_classify(user_prompt: str) -> str:
    note = _note(user_prompt)
    subsystem = "other"
    for name, words in {
        "propulsion": ("valve", "engine", "fuel", "pressure", "tank", "lox"),
        "telemetry": ("telemetry", "link", "downlink", "signal"),
        "avionics": ("avionics", "gyro", "computer", "sensor", "imu"),
        "weather": ("wind", "weather", "lightning", "cloud", "gust"),
        "ground_systems": ("pad", "umbilical", "ground", "crane", "generator"),
        "structures": ("crack", "fairing", "strut", "structure", "weld"),
    }.items():
        if _has(note, *words):
            subsystem = name
            break
    if _has(note, "leak", "fire", "fail", "lost", "stuck", "abort", "critical"):
        severity = "high"
    elif _has(note, "dropped", "odd", "intermittent", "briefly", "drift", "unexpected"):
        severity = "medium"
    else:
        severity = "low"
    return json.dumps({"subsystem": subsystem, "severity": severity})


def _default_check_injection(user_prompt: str) -> str:
    flagged = _has(_note(user_prompt), "ignore", "override", "disregard", "set verdict")
    reason = "Note contains text addressed to the system." if flagged else "No instructions found."
    return json.dumps({"flagged": flagged, "reason": reason})


def _default_check_missing_details(user_prompt: str) -> str:
    flagged = len(_note(user_prompt).split()) < 8
    reason = "Note is too short to act on." if flagged else "Note names what happened."
    return json.dumps({"flagged": flagged, "reason": reason})


def _default_check_panic(user_prompt: str) -> str:
    note = _note(user_prompt)
    letters = [c for c in note if c.isalpha()]
    shouting = bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.5
    flagged = shouting or "!!" in note or _has(note, "disaster", "we're doomed", "panic")
    reason = "Tone is alarmed." if flagged else "Tone is calm."
    return json.dumps({"flagged": flagged, "reason": reason})


def _default_draft(user_prompt: str) -> str:
    note = " ".join(_note(user_prompt).split())
    return (
        f"Engineer reports: {note[:240]} "
        "Impact on the count is under assessment. "
        "Recommended action: station lead to confirm status before the next poll."
    )


DEFAULT_SCRIPT: dict[str, Reply | list[Reply]] = {
    "classify": _default_classify,
    "check_injection": _default_check_injection,
    "check_missing_details": _default_check_missing_details,
    "check_panic": _default_check_panic,
    "draft": _default_draft,
    "review": json.dumps({"approved": True, "feedback": ""}),
}
