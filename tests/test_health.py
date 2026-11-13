def test_health_reports_ok_and_the_model_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "llm_mode": "fake"}


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Mission Control" in response.text
