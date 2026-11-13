import pytest

from app.brief_by import brief_by_minutes, final_severity
from app.schemas import Violation

WIND_VIOLATION = Violation(field="wind_knots", value=31, rule="<=", limit=25)


@pytest.mark.parametrize(("severity", "minutes"), [("high", 5), ("medium", 15), ("low", 30)])
def test_minutes_follow_severity(severity, minutes):
    assert brief_by_minutes(severity) == minutes


@pytest.mark.parametrize("model_severity", ["low", "medium", "high"])
def test_any_violation_counts_as_high(model_severity):
    severity = final_severity(model_severity, [WIND_VIOLATION])
    assert severity == "high"
    assert brief_by_minutes(severity) == 5


@pytest.mark.parametrize("model_severity", ["low", "medium", "high"])
def test_no_violation_keeps_the_model_severity(model_severity):
    assert final_severity(model_severity, []) == model_severity
