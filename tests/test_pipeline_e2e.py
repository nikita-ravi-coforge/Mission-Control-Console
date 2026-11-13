import json
from decimal import Decimal

from app.cost import step_cost
from tests.conftest import report_payload

EXPECTED_STEPS = [
    "validate_input",
    "check_limits",
    "classify",
    "scan_note_patterns",
    "check_injection",
    "check_missing_details",
    "check_panic",
    "compute_brief_by",
    "draft_r1",
    "review_r1",
    "finalize",
]
MODEL_STEPS = {"classify", "check_injection", "check_missing_details", "check_panic"} | {
    "draft_r1",
    "review_r1",
}


def run(client, **overrides) -> dict:
    report_id = client.post("/api/reports", json=report_payload(**overrides)).json()["id"]
    return client.get(f"/api/reports/{report_id}").json()


def test_full_run_records_one_trace_step_per_pipeline_step_in_order(client):
    report = run(client)
    trace = report["trace"]

    assert [step["name"] for step in trace] == EXPECTED_STEPS
    assert [step["seq"] for step in trace] == list(range(1, len(EXPECTED_STEPS) + 1))
    for step in trace:
        if step["name"] in MODEL_STEPS:
            assert step["kind"] == "model"
            assert step["input_tokens"] > 0 and step["output_tokens"] > 0
            assert step["model"] in {"fake-fast", "fake-strong"}
        else:
            assert step["kind"] == "code"
            assert (step["input_tokens"], step["output_tokens"], step["model"]) == (0, 0, None)
            assert Decimal(step["cost_usd"]) == 0


def test_report_cost_is_the_sum_of_its_steps_calculated_in_code(make_client):
    client, _ = make_client(input_tokens=1000, output_tokens=200)
    report = run(client)

    by_step = sum(Decimal(step["cost_usd"]) for step in report["trace"])
    expected = 4 * step_cost("fake-fast", 1000, 200) + 2 * step_cost("fake-strong", 1000, 200)
    assert Decimal(report["total_cost_usd"]) == by_step == expected
    assert expected > 0


def test_extra_review_rounds_add_to_the_cost(make_client):
    reject = json.dumps({"approved": False, "feedback": "tighter"})
    one_round, _ = make_client()
    cheap = run(one_round)
    three_rounds, _ = make_client({"review": reject})
    costly = run(three_rounds)

    assert costly["review_rounds"] == 3
    assert Decimal(costly["total_cost_usd"]) > Decimal(cheap["total_cost_usd"])
    assert costly["needs_review"] is True
    assert costly["status"] == "pending"


def test_clean_report_ends_pending_with_everything_filled_in(client):
    report = run(client)
    assert report["verdict"] == "go"
    assert report["violations"] == []
    assert report["subsystem"] == "propulsion"
    assert report["severity_final"] == report["severity_model"]
    assert report["brief_by_minutes"] in {5, 15, 30}
    assert set(report["flags"]) == {"injection", "missing_details", "panic"}
    assert report["briefing"]
    assert report["briefing_header"].startswith("VERDICT: GO")
    assert report["review_rounds"] == 1
    assert report["needs_review"] is False
    assert report["status"] == "pending"


def test_violation_overrides_a_low_model_severity_end_to_end(make_client):
    client, _ = make_client({"classify": json.dumps({"subsystem": "weather", "severity": "low"})})
    report = run(client, wind_knots=25.1)
    assert (report["severity_model"], report["severity_final"]) == ("low", "high")
    assert report["brief_by_minutes"] == 5


def test_invalid_sorting_reply_falls_back_and_is_shown_in_the_trace(make_client):
    client, _ = make_client({"classify": '{"subsystem": "propulsion", "severity": "catastrophic"}'})
    report = run(client)
    classify = next(step for step in report["trace"] if step["name"] == "classify")

    assert (report["subsystem"], report["severity_final"], report["brief_by_minutes"]) == (
        "unknown",
        "high",
        5,
    )
    assert classify["fallback_used"] is True
    assert report["needs_review"] is True


def test_every_model_failing_still_yields_a_verdict_and_a_pending_report(make_client):
    down = ConnectionError("model endpoint unreachable")
    client, _ = make_client(
        {
            purpose: down
            for purpose in [
                "classify",
                "check_injection",
                "check_missing_details",
                "check_panic",
                "draft",
                "review",
            ]
        }  # fmt: skip
    )
    report = run(client, temp_c=3.9)

    assert report["verdict"] == "no_go"
    assert report["status"] == "pending"
    assert report["severity_final"] == "high"
    assert all(flag["flagged"] for flag in report["flags"].values())
    assert report["needs_review"] is True
    assert Decimal(report["total_cost_usd"]) == 0


def test_list_shows_newest_first_with_summary_fields(client):
    run(client)
    run(client, wind_knots=31)
    listed = client.get("/api/reports").json()
    assert [(r["id"], r["verdict"]) for r in listed] == [(2, "no_go"), (1, "go")]
    assert {"station", "severity_final", "brief_by_minutes", "status", "needs_review"} <= set(
        listed[0]
    )
