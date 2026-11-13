"""The one interface every model call goes through."""

from dataclasses import dataclass
from typing import Literal, Protocol

Tier = Literal["fast", "strong"]


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient(Protocol):
    mode: str  # "fake" or the real provider's name; shown in the console

    async def complete(
        self,
        *,
        purpose: str,
        tier: Tier,
        system: str,
        user: str,
        json_schema: dict | None = None,
    ) -> LLMResult:
        """Run one model call.

        `purpose` names the step (classify, check_injection, draft, review).
        `tier` picks the fast or the strong model. `json_schema`, when given,
        asks the model for a JSON reply of that shape; the caller still
        validates the reply itself.
        """
        ...
