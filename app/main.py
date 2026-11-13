"""Application factory.

`create_app()` builds a fresh app around a database path and an LLM client, so
tests can point it at a temp database and a fake model.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Mission Control")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "llm_mode": "fake"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
