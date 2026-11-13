import json

import pytest

from app.db import Database
from app.limits import evaluate_limits
from app.schemas import ReportIn
from tests.conftest import report_payload

APPROVER = {"approver_name": "FD Reyes"}


def file(client, **overrides) -> int:
    return client.post("/api/reports", json=report_payload(**overrides)).json()["id"]


def test_pipeline_leaves_the_briefing_pending_even_when_the_evaluator_approves(make_client):
    client, llm = make_client({"review": json.dumps({"approved": True, "feedback": ""})})
    report = client.get(f"/api/reports/{file(client)}").json()

    assert len(llm.calls_for("review")) == 1  # the evaluator approved in round one
    assert report["status"] == "pending"
    assert report["approved_by"] is None
    assert report["approved_at"] is None


def test_a_person_approves_a_pending_briefing(client):
    report_id = file(client)
    response = client.post(f"/api/reports/{report_id}/approve", json=APPROVER)

    assert response.status_code == 200
    report = client.get(f"/api/reports/{report_id}").json()
    assert report["status"] == "approved"
    assert report["approved_by"] == "FD Reyes"
    assert report["approved_at"] is not None


def test_approving_twice_is_rejected(client):
    report_id = file(client)
    client.post(f"/api/reports/{report_id}/approve", json=APPROVER)
    response = client.post(f"/api/reports/{report_id}/approve", json={"approver_name": "Other"})

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]
    assert client.get(f"/api/reports/{report_id}").json()["approved_by"] == "FD Reyes"


@pytest.mark.parametrize("status", ["processing", "failed"])
def test_only_a_pending_briefing_can_be_approved(client, db_path, status):
    report = ReportIn(**report_payload())
    db = Database(db_path)
    report_id = db.insert_report(
        report, evaluate_limits(report.readings()), severity_final=None, brief_by_minutes=None
    )
    if status == "failed":
        db.update_report(report_id, status="failed")

    response = client.post(f"/api/reports/{report_id}/approve", json=APPROVER)
    assert response.status_code == 409
    assert client.get(f"/api/reports/{report_id}").json()["status"] == status


def test_unknown_report_is_404(client):
    assert client.post("/api/reports/999/approve", json=APPROVER).status_code == 404
    assert client.get("/api/reports/999").status_code == 404


@pytest.mark.parametrize("body", [{}, {"approver_name": ""}, {"approver_name": "   "}])
def test_approver_name_is_required(client, body):
    report_id = file(client)
    response = client.post(f"/api/reports/{report_id}/approve", json=body)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "approver_name"
    assert client.get(f"/api/reports/{report_id}").json()["status"] == "pending"


def test_no_code_path_but_approve_can_write_the_approved_status(client, db_path):
    report_id = file(client)
    with pytest.raises(ValueError, match="approve"):
        Database(db_path).update_report(report_id, status="approved")
    with pytest.raises(ValueError, match="cannot be updated"):
        Database(db_path).update_report(report_id, approved_by="the pipeline")
