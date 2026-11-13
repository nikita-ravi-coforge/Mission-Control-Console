"""Cost of a report, calculated in code from token counts."""

from collections.abc import Iterable, Mapping
from decimal import Decimal

from app.pricing import PRICES, ModelPrice

TOKENS_PER_MTOK = Decimal(1_000_000)


class UnknownModelPrice(KeyError):
    """Raised instead of silently pricing an unknown model at zero."""


def step_cost(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    prices: Mapping[str, ModelPrice] = PRICES,
) -> Decimal:
    """Cost of one step. Code steps have no model and cost nothing."""
    if model is None:
        return Decimal(0)
    if model not in prices:
        raise UnknownModelPrice(f"No price configured for model '{model}'")
    price = prices[model]
    return (
        Decimal(input_tokens) * price.input_per_mtok
        + Decimal(output_tokens) * price.output_per_mtok
    ) / TOKENS_PER_MTOK


def report_cost(step_costs: Iterable[Decimal]) -> Decimal:
    return sum(step_costs, Decimal(0))
