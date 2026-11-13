import json

from app.llm.fake import FakeLLM
from app.pipeline.briefing import (
    FALLBACK_BODY,
    INVALID_REVIEW_FEEDBACK,
    BriefingFacts,
    render_header,
    run_briefing_loop,
)
from app.schemas import Violation

NOTE = "Valve V-12 stuck briefly during chilldown."
APPROVE = json.dumps({"approved": True, "feedback": ""})


def reject(feedback: str) -> str:
    return json.dumps({"approved": False, "feedback": feedback})


def facts(**overrides) -> BriefingFacts:
    base = {
        "station": "PROP-2",
        "subsystem": "propulsion",
        "severity": "medium",
        "verdict": "go",
        "violations": [],
        "brief_by_minutes": 15,
    }
    return BriefingFacts(**{**base, **overrides})


async def test_loop_stops_at_three_rounds_when_reviewer_always_rejects():
    llm = FakeLLM({"draft": "a draft", "review": reject("too vague")})
    outcome = await run_briefing_loop(llm, facts(), NOTE)

    assert outcome.rounds == 3
    assert outcome.evaluator_approved is False
    assert len(llm.calls_for("draft")) == 3
    assert len(llm.calls_for("review")) == 3
    assert [s.name for s in outcome.steps] == [
        "draft_r1", "review_r1", "draft_r2", "review_r2", "draft_r3", "review_r3",
    ]  # fmt: skip


async def test_loop_stops_as_soon_as_the_reviewer_approves():
    llm = FakeLLM({"draft": ["first draft", "second draft"], "review": [reject("fix"), APPROVE]})
    outcome = await run_briefing_loop(llm, facts(), NOTE)

    assert outcome.rounds == 2
    assert outcome.evaluator_approved is True
    assert outcome.body == "second draft"
    assert len(llm.calls_for("draft")) == 2
    assert len(llm.calls_for("review")) == 2


async def test_approval_in_round_one_uses_one_round():
    llm = FakeLLM({"draft": "good draft", "review": APPROVE})
    outcome = await run_briefing_loop(llm, facts(), NOTE)
    assert (outcome.rounds, outcome.evaluator_approved, outcome.body) == (1, True, "good draft")


async def test_reviewer_feedback_goes_into_the_next_draft():
    llm = FakeLLM(
        {
            "draft": "a draft",
            "review": [reject("Name the affected valve."), reject("State the action."), APPROVE],
        }
    )
    await run_briefing_loop(llm, facts(), NOTE)
    drafts = llm.calls_for("draft")

    assert "Reviewer feedback to address" not in drafts[0].user
    assert "Reviewer feedback to address:\nName the affected valve." in drafts[1].user
    assert "Reviewer feedback to address:\nState the action." in drafts[2].user
    assert "Name the affected valve." not in drafts[2].user  # only the latest round's feedback


async def test_invalid_review_reply_counts_as_rejection():
    llm = FakeLLM({"draft": "a draft", "review": ["looks fine to me!", APPROVE]})
    outcome = await run_briefing_loop(llm, facts(), NOTE)

    assert outcome.rounds == 2
    assert outcome.steps[1].fallback_used is True
    assert INVALID_REVIEW_FEEDBACK in llm.calls_for("draft")[1].user


async def test_draft_failure_every_round_leaves_the_fallback_body():
    llm = FakeLLM({"draft": TimeoutError("model timed out"), "review": APPROVE})
    outcome = await run_briefing_loop(llm, facts(), NOTE)

    assert outcome.rounds == 3
    assert outcome.evaluator_approved is False
    assert outcome.body == FALLBACK_BODY
    assert llm.calls_for("review") == []


async def test_draft_and_review_use_the_strong_model_and_see_the_code_facts():
    llm = FakeLLM({"draft": "a draft", "review": APPROVE})
    wind = Violation(field="wind_knots", value=31, rule="<=", limit=25)
    await run_briefing_loop(llm, facts(verdict="no_go", violations=[wind], severity="high"), NOTE)

    for call in llm.calls:
        assert call.tier == "strong"
        assert "VERDICT: NO-GO" in call.user
    assert "<engineer_note>" in llm.calls_for("draft")[0].user
    assert "<draft>\na draft\n</draft>" in llm.calls_for("review")[0].user


def test_header_is_rendered_by_code_from_the_facts():
    wind = Violation(field="wind_knots", value=31, rule="<=", limit=25)
    header = render_header(
        facts(verdict="no_go", violations=[wind], severity="high", brief_by_minutes=5)
    )
    assert header.splitlines()[0] == "VERDICT: NO-GO"
    assert "Severity: HIGH | Brief by: 5 min" in header
    assert "wind_knots = 31 (limit <= 25)" in header


def test_header_for_a_clean_report():
    header = render_header(facts())
    assert header.splitlines()[0] == "VERDICT: GO"
    assert "Limit violations: none" in header
