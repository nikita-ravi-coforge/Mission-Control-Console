"""Per-model token prices in USD per one million tokens.

Claude prices are Anthropic's list prices (checked 2026-11). Haiku 5.5's price
is for prompts up to 100K tokens, which every prompt in this app is far below.
The fake prices are illustrative, so the console shows a non-zero cost in
FAKE MODEL MODE.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal


PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": ModelPrice(Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": ModelPrice(Decimal("4.00"), Decimal("20.00")),
    "claude-fable-5-2": ModelPrice(Decimal("8.00"), Decimal("40.00")),
    "fake-fast": ModelPrice(Decimal("0.10"), Decimal("0.50")),
    "fake-strong": ModelPrice(Decimal("2.00"), Decimal("10.00")),
}
