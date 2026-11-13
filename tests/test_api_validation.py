import json

import pytest

from tests.conftest import report_payload


def errors_for(response) -> dict:
    assert response.status_code == 422, response.text
    return {e["field"]: e["message"] for e in response.json()["errors"]}


def test_valid_report_is_accepted(client):
    response = client.post("/api/reports", json=report_payload())
    assert response.status_code == 201
    assert response.json()["id"] == 1


@pytest.mark.parametrize(
    "field", ["engineer_name", "station", "wind_knots", "temp_c", "fuel_pct", "note"]
)
def test_each_field_is_required(client, field):
    payload = report_payload()
    del payload[field]
    assert errors_for(client.post("/api/reports", json=payload)) == {field: f"{field} is required"}


@pytest.mark.parametrize("field", ["wind_knots", "temp_c", "fuel_pct"])
@pytest.mark.parametrize("bad_value", ["abc", "12", "", True, None, [1]])
def test_reading_must_be_a_number(client, field, bad_value):
    errors = errors_for(client.post("/api/reports", json=report_payload(**{field: bad_value})))
    assert errors == {field: f"{field} must be a number"}


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_reading_must_be_finite(client, token):
    body = json.dumps(report_payload(fuel_pct=0)).replace('"fuel_pct": 0', f'"fuel_pct": {token}')
    response = client.post(
        "/api/reports", content=body, headers={"Content-Type": "application/json"}
    )
    assert errors_for(response) == {"fuel_pct": "fuel_pct must be a finite number"}


@pytest.mark.parametrize("field", ["engineer_name", "station", "note"])
@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_text_fields_must_not_be_blank(client, field, blank):
    errors = errors_for(client.post("/api/reports", json=report_payload(**{field: blank})))
    assert errors == {field: f"{field} must not be blank"}


def test_note_has_a_maximum_length(client):
    errors = errors_for(client.post("/api/reports", json=report_payload(note="x" * 2001)))
    assert errors == {"note": "note must be at most 2000 characters"}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("wind_knots", -1, "wind_knots must be at least 0"),
        ("wind_knots", 301, "wind_knots must be at most 300"),
        ("temp_c", -101, "temp_c must be at least -100"),
        ("fuel_pct", 151, "fuel_pct must be at most 150"),
    ],
)
def test_impossible_readings_are_rejected(client, field, value, message):
    errors = errors_for(client.post("/api/reports", json=report_payload(**{field: value})))
    assert errors == {field: message}


def test_several_bad_fields_are_all_reported(client):
    payload = report_payload(engineer_name=" ", wind_knots="fast", note="")
    errors = errors_for(client.post("/api/reports", json=payload))
    assert set(errors) == {"engineer_name", "wind_knots", "note"}


def test_malformed_json_gets_a_clear_message(client):
    response = client.post(
        "/api/reports", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert errors_for(response) == {"body": "Request body must be valid JSON"}


def test_rejected_report_is_not_saved(client):
    client.post("/api/reports", json=report_payload(note=""))
    assert client.get("/api/reports").json() == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("wind_knots", 25.1), ("temp_c", 3.9), ("fuel_pct", 97.9), ("fuel_pct", 100.1)],
)
def test_out_of_limit_reading_is_accepted_then_judged_no_go(client, field, value):
    """Sanity ranges are wider than the launch limits, so a no_go can be filed."""
    response = client.post("/api/reports", json=report_payload(**{field: value}))
    assert response.status_code == 201
    report = client.get(f"/api/reports/{response.json()['id']}").json()
    assert report["verdict"] == "no_go"
    assert [v["field"] for v in report["violations"]] == [field]


def test_whole_number_readings_and_padded_text_are_accepted(client):
    payload = report_payload(wind_knots=25, temp_c=4, fuel_pct=100, engineer_name="  Ada  ")
    report_id = client.post("/api/reports", json=payload).json()["id"]
    report = client.get(f"/api/reports/{report_id}").json()
    assert report["verdict"] == "go"
    assert report["engineer_name"] == "Ada"
