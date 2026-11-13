"""Settings from the environment (and an optional .env file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.llm.base import LLMClient
from app.llm.fake import FakeLLM
from app.pricing import PRICES

DEFAULT_DB_PATH = "data/mission_control.db"
DEFAULT_MODEL_FAST = "claude-haiku-5-5"
DEFAULT_MODEL_STRONG = "claude-sonnet-5-5"


class ConfigError(RuntimeError):
    """The app is misconfigured and must not start."""


@dataclass(frozen=True)
class Settings:
    llm_provider: str  # "fake", "anthropic", or "auto"
    db_path: str
    model_fast: str
    model_strong: str
    has_anthropic_key: bool


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        llm_provider=os.environ.get("LLM_PROVIDER", "auto").strip().lower() or "auto",
        db_path=os.environ.get("DB_PATH", DEFAULT_DB_PATH),
        model_fast=os.environ.get("MODEL_FAST", "").strip() or DEFAULT_MODEL_FAST,
        model_strong=os.environ.get("MODEL_STRONG", "").strip() or DEFAULT_MODEL_STRONG,
        has_anthropic_key=bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
    )


def build_llm(settings: Settings) -> LLMClient:
    """Pick the model client.

    `auto` uses Claude when an API key is present and FAKE MODEL MODE otherwise,
    so the app starts with one command whether or not a key is configured.
    """
    provider = settings.llm_provider
    if provider == "auto":
        provider = "anthropic" if settings.has_anthropic_key else "fake"

    if provider == "fake":
        return FakeLLM()
    if provider != "anthropic":
        raise ConfigError(f"LLM_PROVIDER must be fake, anthropic, or auto; got '{provider}'")

    # Refuse to start with a model we cannot price: cost must never silently be wrong.
    for name, model in (
        ("MODEL_FAST", settings.model_fast),
        ("MODEL_STRONG", settings.model_strong),
    ):
        if model not in PRICES:
            known = ", ".join(sorted(m for m in PRICES if not m.startswith("fake-")))
            raise ConfigError(
                f"{name}='{model}' has no price in app/pricing.py. Known models: {known}"
            )

    from app.llm.anthropic_client import AnthropicLLM  # imported only when used

    return AnthropicLLM(model_fast=settings.model_fast, model_strong=settings.model_strong)
