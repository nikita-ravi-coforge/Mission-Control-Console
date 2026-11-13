"""Application factory.

`create_app()` builds a fresh app around a database path and an LLM client, so
tests can point it at a temp database and a fake model.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import create_router, validation_error_handler
from app.config import build_llm, load_settings
from app.db import Database
from app.llm.base import LLMClient

STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: str | Path | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = load_settings()
    db = Database(db_path or settings.db_path)
    db.fail_stuck_reports()  # anything mid-pipeline when the app last stopped
    llm = llm or build_llm(settings)

    app = FastAPI(title="Mission Control")
    app.state.db = db
    app.state.llm = llm
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(create_router(db, llm))

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
