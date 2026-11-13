"""Per-model token prices in USD per one million tokens.

The fake prices are illustrative so the console shows a non-zero cost in
FAKE MODEL MODE. Real prices are added alongside the real model client.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal


PRICES: dict[str, ModelPrice] = {
    "fake-fast": ModelPrice(Decimal("0.15"), Decimal("0.60")),
    "fake-strong": ModelPrice(Decimal("2.50"), Decimal("10.00")),
}
