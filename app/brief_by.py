"""Brief-by time: how soon the Flight Director must be briefed."""

from collections.abc import Sequence

from app.schemas import Severity, Violation

BRIEF_BY_MINUTES: dict[str, int] = {"high": 5, "medium": 15, "low": 30}


def final_severity(model_severity: Severity, violations: Sequence[Violation]) -> Severity:
    """Any limit violation counts as high, whatever the model said."""
    return "high" if violations else model_severity


def brief_by_minutes(severity: Severity) -> int:
    return BRIEF_BY_MINUTES[severity]
