"""File a report and run the pipeline on it.

Filing is synchronous and model-free: the verdict is computed and saved before
any model is called, so it never waits on, or depends on, a model. The
pipeline that follows can add sorting, flags, and a briefing, but it has no
way to change the verdict and no way to approve.
"""

import logging
from decimal import Decimal

from app.brief_by import brief_by_minutes, final_severity
from app.cost import report_cost
from app.db import Database
from app.limits import evaluate_limits
from app.llm.base import LLMClient
from app.pipeline.briefing import BriefingFacts, run_briefing_loop
from app.pipeline.checks import combine_injection, run_checks, scan_note_for_instructions
from app.pipeline.classify import classify_report
from app.pipeline.model_step import MODEL_TIMEOUT_SECONDS
from app.pipeline.trace import code_step
from app.schemas import ReportIn, Violation

logger = logging.getLogger(__name__)

# validate_input and check_limits are recorded when the report is filed.
STEPS_RECORDED_AT_FILING = 2


def file_report(db: Database, report: ReportIn) -> int:
    """Check the readings against the launch limits in code and save the report."""
    limits = evaluate_limits(report.readings())
    # A violation already fixes severity and brief-by time, whatever a model says later.
    severity = "high" if limits.violations else None
    report_id = db.insert_report(
        report,
        limits,
        severity_final=severity,
        brief_by_minutes=brief_by_minutes(severity) if severity else None,
    )
    db.add_step(report_id, code_step("validate_input", {"valid": True}))
    db.add_step(report_id, code_step("check_limits", limits.model_dump()))
    return report_id


def total_cost(db: Database, report_id: int) -> Decimal:
    return report_cost(Decimal(step["cost_usd"]) for step in db.list_steps(report_id))


async def run_pipeline(
    db: Database, llm: LLMClient, report_id: int, timeout: float = MODEL_TIMEOUT_SECONDS
) -> None:
    """Run every model step for a filed report. Ends in `pending`, or `failed` on a crash."""
    try:
        await _run(db, llm, report_id, timeout)
    except Exception as exc:
        logger.exception("Pipeline crashed for report %s", report_id)
        error = f"{type(exc).__name__}: {exc}"
        step = code_step("pipeline_error", {"status": "failed"})
        step.error = error
        db.add_step(report_id, step)
        db.update_report(
            report_id,
            status="failed",
            error=error,
            total_cost_usd=str(total_cost(db, report_id)),
        )


async def _run(db: Database, llm: LLMClient, report_id: int, timeout: float) -> None:
    report = db.get_report(report_id)
    if report is None:
        raise LookupError(f"Report {report_id} does not exist")
    note = report["note"]
    violations = [Violation(**v) for v in report["violations"]]  # computed by code at filing

    # Sort by subsystem and severity (model, validated in code).
    sorting, step = await classify_report(
        llm, station=report["station"], note=note, timeout=timeout
    )
    db.add_step(report_id, step)

    # Hidden instructions: fixed patterns in code, plus three concurrent model checks.
    rule_hits = scan_note_for_instructions(note)
    db.add_step(report_id, code_step("scan_note_patterns", {"hits": rule_hits}))
    checks, steps = await run_checks(llm, note, timeout=timeout)
    for step in steps:
        db.add_step(report_id, step)
    flags = {name: result.model_dump() for name, result in checks.items()}
    flags["injection"] = combine_injection(checks["injection"], rule_hits).model_dump()

    # Brief-by time (code). Any violation counts as high.
    severity = final_severity(sorting.severity, violations)
    minutes = brief_by_minutes(severity)
    db.add_step(
        report_id,
        code_step(
            "compute_brief_by",
            {
                "severity_model": sorting.severity,
                "violations": len(violations),
                "severity_final": severity,
                "brief_by_minutes": minutes,
            },
        ),
    )

    # Draft and review the briefing (models), up to three rounds.
    facts = BriefingFacts(
        station=report["station"],
        subsystem=sorting.subsystem,
        severity=severity,
        verdict=report["verdict"],
        violations=violations,
        brief_by_minutes=minutes,
    )
    outcome = await run_briefing_loop(llm, facts, note, timeout=timeout)
    for step in outcome.steps:
        db.add_step(report_id, step)

    review_reasons = []
    if flags["injection"]["flagged"]:
        review_reasons.append("Possible injected instructions in the note")
    if not outcome.evaluator_approved:
        review_reasons.append(
            f"Briefing was not approved by the evaluator after {outcome.rounds} round(s)"
        )
    if sorting.fallback_used:
        review_reasons.append("Sorting fell back to unknown / high")

    # Finalize (code). The report waits for a person; the pipeline cannot approve it.
    cost = total_cost(db, report_id)
    db.add_step(
        report_id,
        code_step(
            "finalize",
            {
                "status": "pending",
                "needs_review": bool(review_reasons),
                "total_cost_usd": str(cost),
            },
        ),
    )
    db.update_report(
        report_id,
        subsystem=sorting.subsystem,
        severity_model=sorting.severity,
        severity_final=severity,
        brief_by_minutes=minutes,
        flags=flags,
        needs_review=int(bool(review_reasons)),
        review_reasons=review_reasons,
        briefing=outcome.body,
        review_rounds=outcome.rounds,
        total_cost_usd=str(cost),
        status="pending",
    )
