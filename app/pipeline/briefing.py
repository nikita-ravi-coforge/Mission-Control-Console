"""Draft a briefing with one model call and review it with a second, up to three rounds.

The header (verdict, violations, severity, brief-by) is rendered by code from
code-computed facts. The model writes only the summary body, so nothing in the
note or in a model reply can change what the header says.
"""

from dataclasses import dataclass, field

from app.llm.base import LLMClient
from app.pipeline.model_step import MODEL_TIMEOUT_SECONDS, run_structured_step, run_text_step
from app.pipeline.trace import StepRecord
from app.prompts import draft_prompt, review_prompt
from app.schemas import Review, Severity, Verdict, Violation

MAX_ROUNDS = 3
INVALID_REVIEW_FEEDBACK = "Reviewer output invalid; tighten format."
FALLBACK_BODY = "Automatic summary unavailable. Read the engineer's note directly."


@dataclass(frozen=True)
class BriefingFacts:
    station: str
    subsystem: str
    severity: Severity
    verdict: Verdict
    violations: list[Violation]
    brief_by_minutes: int


@dataclass
class BriefingOutcome:
    body: str
    rounds: int
    evaluator_approved: bool
    steps: list[StepRecord] = field(default_factory=list)


def render_header(facts: BriefingFacts) -> str:
    """The authoritative part of the briefing, built by code only."""
    verdict = "NO-GO" if facts.verdict == "no_go" else "GO"
    lines = [
        f"VERDICT: {verdict}",
        f"Severity: {facts.severity.upper()} | Brief by: {facts.brief_by_minutes} min",
        f"Station: {facts.station} | Subsystem: {facts.subsystem}",
    ]
    if facts.violations:
        lines.append("Limit violations:")
        lines += [
            f"  - {v.field} = {v.value:g} (limit {v.rule} {v.limit:g})" for v in facts.violations
        ]
    else:
        lines.append("Limit violations: none")
    return "\n".join(lines)


async def run_briefing_loop(
    llm: LLMClient,
    facts: BriefingFacts,
    note: str,
    *,
    max_rounds: int = MAX_ROUNDS,
    timeout: float = MODEL_TIMEOUT_SECONDS,
) -> BriefingOutcome:
    """Draft, review, and redraft with the reviewer's feedback until approved or out of rounds.

    Evaluator approval only ends the loop. It is not the Flight Director's approval.
    """
    header = render_header(facts)
    outcome = BriefingOutcome(body=FALLBACK_BODY, rounds=0, evaluator_approved=False)
    feedback: str | None = None

    for round_number in range(1, max_rounds + 1):
        outcome.rounds = round_number

        system, user = draft_prompt(header, note, feedback)
        draft, draft_step = await run_text_step(
            llm,
            name=f"draft_r{round_number}",
            purpose="draft",
            tier="strong",
            system=system,
            user=user,
            timeout=timeout,
        )
        outcome.steps.append(draft_step)
        if draft is None:
            continue  # nothing to review; try again next round
        outcome.body = draft

        system, user = review_prompt(header, draft)
        review, review_step = await run_structured_step(
            llm,
            name=f"review_r{round_number}",
            purpose="review",
            tier="strong",
            system=system,
            user=user,
            reply_model=Review,
            timeout=timeout,
        )
        outcome.steps.append(review_step)
        if review is None:
            review = Review(approved=False, feedback=INVALID_REVIEW_FEEDBACK)
            review_step.output = {**(review_step.output or {}), "fallback": review.model_dump()}

        if review.approved:
            outcome.evaluator_approved = True
            break
        feedback = review.feedback or "Reviewer rejected the draft without feedback."

    return outcome
