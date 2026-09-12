from fastapi.testclient import TestClient

from app.slack_gateway import app

client = TestClient(app)


def test_gateway_exposes_only_liveness_and_signed_events():
    assert client.get("/healthz").status_code == 200
    assert client.post("/slack/events", json={"type": "url_verification"}).status_code == 401
    for path in ("/docs", "/openapi.json", "/api/v1/reconciliations", "/metrics", "/slack/interactions"):
        assert client.get(path).status_code == 404
