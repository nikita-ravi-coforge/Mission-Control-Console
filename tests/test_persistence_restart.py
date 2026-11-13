from fastapi.testclient import TestClient

from app.db import Database
from app.limits import evaluate_limits
from app.llm.fake import FakeLLM
from app.main import create_app
from app.schemas import ReportIn
from tests.conftest import report_payload


def test_reports_and_traces_survive_a_restart(db_path):
    # First run of the app: file two reports, then shut down.
    with TestClient(create_app(db_path=db_path, llm=FakeLLM())) as first:
        go_id = first.post("/api/reports", json=report_payload()).json()["id"]
        no_go_id = first.post("/api/reports", json=report_payload(wind_knots=31)).json()["id"]
        before = first.get(f"/api/reports/{no_go_id}").json()
    del first

    # Second run: a brand-new app object on the same database file.
    with TestClient(create_app(db_path=db_path, llm=FakeLLM())) as second:
        listed = second.get("/api/reports").json()
        after = second.get(f"/api/reports/{no_go_id}").json()

    assert [r["id"] for r in listed] == [no_go_id, go_id]  # newest first
    assert after == before
    assert after["verdict"] == "no_go"
    assert after["note"] == report_payload()["note"]
    assert after["status"] == "pending"
    assert len(after["trace"]) > 0


def test_approval_survives_a_restart(db_path):
    with TestClient(create_app(db_path=db_path, llm=FakeLLM())) as first:
        report_id = first.post("/api/reports", json=report_payload()).json()["id"]
        first.post(f"/api/reports/{report_id}/approve", json={"approver_name": "FD Reyes"})

    with TestClient(create_app(db_path=db_path, llm=FakeLLM())) as second:
        report = second.get(f"/api/reports/{report_id}").json()
    assert (report["status"], report["approved_by"]) == ("approved", "FD Reyes")


def test_report_stuck_in_processing_is_marked_failed_on_startup(db_path):
    # Simulate a crash mid-pipeline: the report was filed but never finished.
    report = ReportIn(**report_payload(wind_knots=31))
    stuck_id = Database(db_path).insert_report(
        report, evaluate_limits(report.readings()), severity_final="high", brief_by_minutes=5
    )

    with TestClient(create_app(db_path=db_path, llm=FakeLLM())) as client:
        restarted = client.get(f"/api/reports/{stuck_id}").json()
        assert restarted["status"] == "failed"
        assert restarted["verdict"] == "no_go"  # the code verdict is still there

        # A failed report can be re-run, and only a failed one.
        assert client.post(f"/api/reports/{stuck_id}/rerun").status_code == 202
        assert client.get(f"/api/reports/{stuck_id}").json()["status"] == "pending"
        assert client.post(f"/api/reports/{stuck_id}/rerun").status_code == 409


def test_database_folder_is_created_if_missing(tmp_path):
    nested = tmp_path / "data" / "nested" / "mc.db"
    with TestClient(create_app(db_path=nested, llm=FakeLLM())) as client:
        assert client.get("/api/reports").json() == []
    assert nested.exists()
