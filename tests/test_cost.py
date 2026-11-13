from decimal import Decimal

import pytest

from app.cost import UnknownModelPrice, report_cost, step_cost
from app.pricing import ModelPrice

PRICES = {
    "small": ModelPrice(Decimal("0.15"), Decimal("0.60")),
    "large": ModelPrice(Decimal("2.50"), Decimal("10.00")),
}


def test_step_cost_is_exact_for_known_token_counts():
    # 1000 in * $0.15/M + 500 out * $0.60/M = 0.00015 + 0.0003
    assert step_cost("small", 1000, 500, PRICES) == Decimal("0.00045")
    # 2000 in * $2.50/M + 1000 out * $10/M = 0.005 + 0.01
    assert step_cost("large", 2000, 1000, PRICES) == Decimal("0.015")


def test_input_and_output_tokens_are_priced_separately():
    assert step_cost("small", 1_000_000, 0, PRICES) == Decimal("0.15")
    assert step_cost("small", 0, 1_000_000, PRICES) == Decimal("0.60")


def test_code_step_costs_nothing():
    assert step_cost(None, 0, 0, PRICES) == Decimal(0)


def test_unknown_model_raises_instead_of_costing_zero():
    with pytest.raises(UnknownModelPrice):
        step_cost("mystery-model", 100, 50, PRICES)


def test_report_cost_is_the_sum_of_its_steps():
    steps = [
        step_cost("small", 1000, 500, PRICES),
        step_cost("large", 2000, 1000, PRICES),
        step_cost(None, 0, 0, PRICES),
    ]
    assert report_cost(steps) == Decimal("0.01545")


def test_report_with_no_steps_costs_zero():
    assert report_cost([]) == Decimal(0)
