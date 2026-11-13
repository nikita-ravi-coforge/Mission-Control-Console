from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_ok():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_index_page_is_served():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Mission Control" in response.text
