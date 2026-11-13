"""The real model client: Claude through the Anthropic API.

The fast tier (sorting and the three checks) and the strong tier (drafting and
reviewing the briefing) map to two different Claude models, chosen in settings.
"""

import copy

import anthropic

from app.llm.base import LLMResult, Tier

# Thinking effort and output cap per tier. The fast tier answers short
# classification questions; the strong tier writes and judges a briefing.
_EFFORT: dict[Tier, str] = {"fast": "low", "strong": "medium"}
_MAX_TOKENS: dict[Tier, int] = {"fast": 2048, "strong": 4096}

REQUEST_TIMEOUT_SECONDS = 25.0


class ModelDeclined(RuntimeError):
    """The model returned no usable answer (refused, or was cut off)."""


def strict_schema(schema: dict) -> dict:
    """Shape a Pydantic JSON schema for structured outputs.

    Structured outputs need every property listed as required and no extra
    properties allowed. Titles and defaults are documentation only, so drop them.
    """
    schema = copy.deepcopy(schema)
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
        prop.pop("default", None)
    schema["required"] = list(schema.get("properties", {}))
    schema["additionalProperties"] = False
    return schema


class AnthropicLLM:
    mode = "anthropic"

    def __init__(
        self,
        *,
        model_fast: str,
        model_strong: str,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.models: dict[Tier, str] = {"fast": model_fast, "strong": model_strong}
        # Credentials come from the environment (ANTHROPIC_API_KEY); never from code.
        self._client = client or anthropic.AsyncAnthropic(
            timeout=REQUEST_TIMEOUT_SECONDS, max_retries=1
        )

    async def complete(
        self,
        *,
        purpose: str,
        tier: Tier,
        system: str,
        user: str,
        json_schema: dict | None = None,
    ) -> LLMResult:
        model = self.models[tier]
        output_config: dict = {"effort": _EFFORT[tier]}
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": strict_schema(json_schema)}

        response = await self._client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS[tier],
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )

        # A refusal or a cut-off reply is not an answer; the caller falls back safely.
        if response.stop_reason in {"refusal", "max_tokens"}:
            raise ModelDeclined(f"{purpose}: model stopped with '{response.stop_reason}'")
        text = "".join(block.text for block in response.content if block.type == "text")

        usage = response.usage
        input_tokens = (
            usage.input_tokens
            + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0)
        )
        # Priced by the model we asked for, so the price table key always matches.
        return LLMResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=usage.output_tokens,
            model=model,
        )
