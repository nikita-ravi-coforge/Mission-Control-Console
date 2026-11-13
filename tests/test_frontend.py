"""The console is plain static files served by the same app."""

import re

from app.schemas import ReportIn


def test_form_has_an_input_for_every_report_field(client):
    html = client.get("/").text
    form_fields = set(re.findall(r'<(?:input|textarea) name="(\w+)"', html))
    assert form_fields == set(ReportIn.model_fields)


def test_form_has_an_error_slot_for_every_report_field(client):
    html = client.get("/").text
    slots = set(re.findall(r'data-error-for="(\w+)"', html))
    assert set(ReportIn.model_fields) <= slots


def test_static_assets_are_served(client):
    for path in ("/static/app.js", "/static/styles.css"):
        assert client.get(path).status_code == 200


def test_console_script_sends_every_field_and_never_uses_inner_html(client):
    script = client.get("/static/app.js").text
    for field in ReportIn.model_fields:
        assert f'"{field}"' in script
    assert "innerHTML" not in script.replace("never innerHTML", "")
