"""The real client, tested against a stub SDK client: no network, no API key."""

from types import SimpleNamespace

import pytest

from app.config import ConfigError, Settings, build_llm
from app.cost import step_cost
from app.llm.anthropic_client import AnthropicLLM, ModelDeclined, strict_schema
from app.llm.fake import FakeLLM
from app.pipeline.classify import classify_report
from app.schemas import CheckResult, Classification


class StubMessages:
    def __init__(self, text="ok", stop_reason="end_turn", input_tokens=120, output_tokens=30):
        self.requests: list[dict] = []
        self._reply = SimpleNamespace(
            stop_reason=stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=text),
            ],
            usage=SimpleNamespace(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=None,
                cache_read_input_tokens=None,
            ),
        )

    async def create(self, **request):
        self.requests.append(request)
        return self._reply


def make_llm(**reply) -> tuple[AnthropicLLM, StubMessages]:
    messages = StubMessages(**reply)
    llm = AnthropicLLM(
        model_fast="claude-haiku-5-5",
        model_strong="claude-sonnet-5-5",
        client=SimpleNamespace(messages=messages),
    )
    return llm, messages


async def test_each_tier_goes_to_its_own_model():
    llm, messages = make_llm()
    fast = await llm.complete(purpose="classify", tier="fast", system="s", user="u")
    strong = await llm.complete(purpose="draft", tier="strong", system="s", user="u")

    assert [r["model"] for r in messages.requests] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert (fast.model, strong.model) == ("claude-haiku-5-5", "claude-sonnet-5-5")


async def test_request_carries_the_prompts_and_reply_carries_text_and_tokens():
    llm, messages = make_llm(text="hello", input_tokens=120, output_tokens=30)
    result = await llm.complete(purpose="draft", tier="strong", system="SYS", user="USER")

    request = messages.requests[0]
    assert request["system"] == "SYS"
    assert request["messages"] == [{"role": "user", "content": "USER"}]
    assert "format" not in request["output_config"]
    assert (result.text, result.input_tokens, result.output_tokens) == ("hello", 120, 30)


async def test_structured_call_sends_a_strict_json_schema():
    llm, messages = make_llm(text='{"subsystem": "weather", "severity": "low"}')
    await llm.complete(
        purpose="classify",
        tier="fast",
        system="s",
        user="u",
        json_schema=Classification.model_json_schema(),
    )
    fmt = messages.requests[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["required"] == ["subsystem", "severity"]
    assert fmt["schema"]["properties"]["severity"]["enum"] == ["low", "medium", "high"]


def test_strict_schema_requires_every_property_and_leaves_the_original_alone():
    original = CheckResult.model_json_schema()
    strict = strict_schema(original)
    assert strict["required"] == ["flagged", "reason"]
    assert "default" not in strict["properties"]["reason"]
    assert "default" in original["properties"]["reason"]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
async def test_refused_or_cut_off_reply_raises(stop_reason):
    llm, _ = make_llm(stop_reason=stop_reason)
    with pytest.raises(ModelDeclined, match=stop_reason):
        await llm.complete(purpose="classify", tier="fast", system="s", user="u")


async def test_refusal_becomes_the_safe_fallback_in_the_pipeline():
    llm, _ = make_llm(stop_reason="refusal")
    sorting, step = await classify_report(llm, station="PROP-2", note="Valve stuck.")
    assert (sorting.subsystem, sorting.severity) == ("unknown", "high")
    assert step.fallback_used is True


async def test_real_model_step_is_priced_from_the_price_table():
    llm, _ = make_llm(
        text='{"subsystem": "weather", "severity": "low"}', input_tokens=1000, output_tokens=200
    )
    _, step = await classify_report(llm, station="WX-1", note="Gusts rising.")
    assert step.model == "claude-haiku-5-5"
    assert step.cost_usd == step_cost("claude-haiku-5-5", 1000, 200) > 0


# --- choosing the client from settings ---


def settings(**overrides) -> Settings:
    base = {
        "llm_provider": "auto",
        "db_path": "unused.db",
        "model_fast": "claude-haiku-5-5",
        "model_strong": "claude-sonnet-5-5",
        "has_anthropic_key": False,
    }
    return Settings(**{**base, **overrides})


def test_auto_without_a_key_runs_the_fake_model():
    assert isinstance(build_llm(settings()), FakeLLM)


def test_fake_is_used_when_forced_even_with_a_key():
    assert isinstance(build_llm(settings(llm_provider="fake", has_anthropic_key=True)), FakeLLM)


def test_auto_with_a_key_builds_the_real_client(monkeypatch):
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kwargs: SimpleNamespace())
    llm = build_llm(settings(has_anthropic_key=True, model_strong="claude-fable-5-2"))
    assert isinstance(llm, AnthropicLLM)
    assert llm.models == {"fast": "claude-haiku-5-5", "strong": "claude-fable-5-2"}


def test_unpriced_model_stops_the_app_from_starting():
    with pytest.raises(ConfigError, match="MODEL_STRONG='claude-mystery-9'"):
        build_llm(settings(llm_provider="anthropic", model_strong="claude-mystery-9"))


def test_unknown_provider_is_rejected():
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        build_llm(settings(llm_provider="openai"))
