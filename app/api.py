"""HTTP routes for the console."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.db import Database
from app.llm.base import LLMClient
from app.pipeline.briefing import BriefingFacts, render_header
from app.pipeline.runner import STEPS_RECORDED_AT_FILING, file_report, run_pipeline
from app.schemas import ApproveIn, ReportIn, Violation

_LIST_FIELDS = (
    "id",
    "created_at",
    "engineer_name",
    "station",
    "verdict",
    "subsystem",
    "severity_final",
    "brief_by_minutes",
    "status",
    "needs_review",
)


def create_router(db: Database, llm: LLMClient) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict:
        return {"ok": True, "llm_mode": llm.mode, "models": getattr(llm, "models", None)}

    @router.post("/reports", status_code=201)
    def create_report(report: ReportIn, background: BackgroundTasks) -> dict:
        report_id = file_report(db, report)  # verdict is saved before any model runs
        background.add_task(run_pipeline, db, llm, report_id)
        return {"id": report_id, "status": "processing"}

    @router.get("/reports")
    def list_reports() -> list[dict]:
        return [{field: report[field] for field in _LIST_FIELDS} for report in db.list_reports()]

    @router.get("/reports/{report_id}")
    def get_report(report_id: int) -> dict:
        return _report_view(db, _require(db, report_id))

    @router.post("/reports/{report_id}/approve")
    def approve_report(report_id: int, body: ApproveIn) -> dict:
        """The only way a briefing becomes approved: a named person asks for it."""
        report = _require(db, report_id)
        if not db.approve(report_id, body.approver_name):
            raise HTTPException(
                status_code=409,
                detail=f"Only a pending briefing can be approved; this one is {report['status']}.",
            )
        return _report_view(db, _require(db, report_id))

    @router.post("/reports/{report_id}/rerun", status_code=202)
    def rerun_report(report_id: int, background: BackgroundTasks) -> dict:
        report = _require(db, report_id)
        if not db.reset_failed_for_rerun(report_id, keep_steps=STEPS_RECORDED_AT_FILING):
            raise HTTPException(
                status_code=409,
                detail=f"Only a failed report can be re-run; this one is {report['status']}.",
            )
        background.add_task(run_pipeline, db, llm, report_id)
        return {"id": report_id, "status": "processing"}

    return router


def _require(db: Database, report_id: int) -> dict:
    report = db.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} was not found.")
    return report


def _report_view(db: Database, report: dict) -> dict:
    return {
        **report,
        "briefing_header": _header(report),
        "trace": db.list_steps(report["id"]),
    }


def _header(report: dict) -> str:
    """Code-rendered briefing header, from the code-computed columns only."""
    if report["severity_final"] is None:
        verdict = "NO-GO" if report["verdict"] == "no_go" else "GO"
        return f"VERDICT: {verdict}\nSeverity and brief-by time: not yet available"
    return render_header(
        BriefingFacts(
            station=report["station"],
            subsystem=report["subsystem"] or "not yet sorted",
            severity=report["severity_final"],
            verdict=report["verdict"],
            violations=[Violation(**v) for v in report["violations"]],
            brief_by_minutes=report["brief_by_minutes"],
        )
    )


# --- clear validation messages instead of FastAPI's default 422 body ---


def _friendly_error(error: dict) -> dict:
    location = [part for part in error["loc"] if part != "body"]
    field = str(location[0]) if location else "body"
    kind = error["type"]
    context = error.get("ctx", {})

    if kind == "json_invalid":
        return {"field": "body", "message": "Request body must be valid JSON"}
    if kind == "missing":
        message = f"{field} is required"
    elif kind in {"float_type", "float_parsing", "int_type", "int_parsing"}:
        message = f"{field} must be a number"
    elif kind == "finite_number":
        message = f"{field} must be a finite number"
    elif kind == "greater_than_equal":
        message = f"{field} must be at least {context['ge']:g}"
    elif kind == "less_than_equal":
        message = f"{field} must be at most {context['le']:g}"
    elif kind == "string_too_short":
        message = f"{field} must not be blank"
    elif kind == "string_too_long":
        message = f"{field} must be at most {context['max_length']} characters"
    elif kind == "string_type":
        message = f"{field} must be text"
    else:
        message = f"{field}: {error['msg']}"
    return {"field": field, "message": message}


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"errors": [_friendly_error(e) for e in exc.errors()]}
    )
