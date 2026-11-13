"""Shared fixtures. Every test runs on FakeLLM and a temp database: no network, no API key."""

import pytest
from fastapi.testclient import TestClient

from app.llm.fake import FakeLLM
from app.main import create_app

VALID_REPORT = {
    "engineer_name": "Ada Okafor",
    "station": "PROP-2",
    "wind_knots": 12.0,
    "temp_c": 18.0,
    "fuel_pct": 99.5,
    "note": "Valve V-12 stuck for two seconds during chilldown at T-95, then cycled normally.",
}


def report_payload(**overrides) -> dict:
    return {**VALID_REPORT, **overrides}


@pytest.fixture(autouse=True)
def _no_real_model(monkeypatch):
    """Force fake mode even if the developer's shell or .env configures a real provider.

    Building the real Anthropic client raises, so an accidental real call fails loudly.
    """
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _refuse(*args, **kwargs):
        raise AssertionError("Tests must not build a real Anthropic client")

    monkeypatch.setattr("anthropic.AsyncAnthropic", _refuse)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "mission_control.db"


@pytest.fixture
def make_client(db_path):
    """Build an app on the temp database. Returns (client, fake_llm)."""

    def _make(script: dict | None = None, **fake_kwargs) -> tuple[TestClient, FakeLLM]:
        llm = FakeLLM(script, **fake_kwargs)
        return TestClient(create_app(db_path=db_path, llm=llm)), llm

    return _make


@pytest.fixture
def client(make_client):
    return make_client()[0]
