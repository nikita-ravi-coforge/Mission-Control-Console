"""Launch limits in plain code.

The verdict comes from the three readings only. `evaluate_limits` takes a
`Readings` object, so the engineer's free-text note cannot reach this code.
"""

from app.schemas import LimitResult, Readings, Violation

WIND_MAX_KNOTS = 25.0
TEMP_MIN_C = 4.0
FUEL_MIN_PCT = 98.0
FUEL_MAX_PCT = 100.0


def evaluate_limits(readings: Readings) -> LimitResult:
    """Return `no_go` with every violated limit, or `go` if all readings are in limits.

    Limits are inclusive: wind 25, temp 4, and fuel 98 or 100 all pass.
    Values are compared as given, with no rounding.
    """
    violations: list[Violation] = []

    if not readings.wind_knots <= WIND_MAX_KNOTS:
        violations.append(
            Violation(
                field="wind_knots", value=readings.wind_knots, rule="<=", limit=WIND_MAX_KNOTS
            )
        )
    if not readings.temp_c >= TEMP_MIN_C:
        violations.append(
            Violation(field="temp_c", value=readings.temp_c, rule=">=", limit=TEMP_MIN_C)
        )
    if not readings.fuel_pct >= FUEL_MIN_PCT:
        violations.append(
            Violation(field="fuel_pct", value=readings.fuel_pct, rule=">=", limit=FUEL_MIN_PCT)
        )
    if not readings.fuel_pct <= FUEL_MAX_PCT:
        violations.append(
            Violation(field="fuel_pct", value=readings.fuel_pct, rule="<=", limit=FUEL_MAX_PCT)
        )

    return LimitResult(verdict="no_go" if violations else "go", violations=violations)
