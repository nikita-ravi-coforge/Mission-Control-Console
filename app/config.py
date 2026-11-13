"""Settings from the environment (and an optional .env file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.llm.base import LLMClient
from app.llm.fake import FakeLLM

DEFAULT_DB_PATH = "data/mission_control.db"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    db_path: str


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        llm_provider=os.environ.get("LLM_PROVIDER", "fake").strip().lower() or "fake",
        db_path=os.environ.get("DB_PATH", DEFAULT_DB_PATH),
    )


def build_llm(settings: Settings) -> LLMClient:
    """Pick the model client. With no real provider configured, run in FAKE MODEL MODE."""
    return FakeLLM()
