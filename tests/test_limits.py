import pytest

from app.limits import evaluate_limits
from app.schemas import Readings

IN_LIMITS = {"wind_knots": 10.0, "temp_c": 15.0, "fuel_pct": 99.0}


def readings(**overrides) -> Readings:
    return Readings(**{**IN_LIMITS, **overrides})


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        # wind: 25 knots or less
        ("wind_knots", 24.9, "go"),
        ("wind_knots", 25, "go"),
        ("wind_knots", 25.01, "no_go"),
        ("wind_knots", 25.1, "no_go"),
        # temperature: 4 C or more
        ("temp_c", 4.1, "go"),
        ("temp_c", 4, "go"),
        ("temp_c", 3.99, "no_go"),
        ("temp_c", 3.9, "no_go"),
        # fuel: 98 to 100 percent
        ("fuel_pct", 98, "go"),
        ("fuel_pct", 97.99, "no_go"),
        ("fuel_pct", 97.9, "no_go"),
        ("fuel_pct", 100, "go"),
        ("fuel_pct", 100.01, "no_go"),
        ("fuel_pct", 100.1, "no_go"),
    ],
)
def test_verdict_exactly_on_and_just_past_each_limit(field, value, expected):
    result = evaluate_limits(readings(**{field: value}))
    assert result.verdict == expected
    assert [v.field for v in result.violations] == ([field] if expected == "no_go" else [])


def test_all_readings_in_limits_is_go_with_no_violations():
    result = evaluate_limits(readings())
    assert result.verdict == "go"
    assert result.violations == []


def test_violation_describes_the_broken_limit():
    result = evaluate_limits(readings(wind_knots=25.1))
    assert result.violations[0].model_dump() == {
        "field": "wind_knots",
        "value": 25.1,
        "rule": "<=",
        "limit": 25.0,
    }


def test_fuel_violations_name_the_side_that_was_broken():
    low = evaluate_limits(readings(fuel_pct=97.9)).violations[0]
    high = evaluate_limits(readings(fuel_pct=100.1)).violations[0]
    assert (low.rule, low.limit) == (">=", 98.0)
    assert (high.rule, high.limit) == ("<=", 100.0)


def test_multiple_violations_are_all_listed():
    result = evaluate_limits(Readings(wind_knots=31, temp_c=-2, fuel_pct=90))
    assert result.verdict == "no_go"
    assert [v.field for v in result.violations] == ["wind_knots", "temp_c", "fuel_pct"]


def test_limits_take_readings_only():
    """The note has no way in: Readings has exactly the three numeric fields."""
    assert set(Readings.model_fields) == {"wind_knots", "temp_c", "fuel_pct"}
