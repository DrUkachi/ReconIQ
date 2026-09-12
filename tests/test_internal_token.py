import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.internal_auth import INTERNAL_TOKEN_HEADER
from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def api_routes() -> list[tuple[str, str]]:
    # Included routers resolve lazily, so app.routes omits their paths and an empty
    # parametrize would skip silently. The OpenAPI schema lists every route.
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in operations
    )


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_the_api_surface_is_discovered():
    assert len(api_routes()) >= 15


@pytest.mark.parametrize(("method", "path"), api_routes())
def test_every_api_route_refuses_a_request_without_the_token(method, path):
    response = client.request(method, concrete(path))
    assert response.status_code == 401
    assert response.json()["code"] == ErrorCode.E_INTERNAL_AUTH


def test_login_issues_no_session_without_the_token():
    """The attack this guards against: claiming any email to receive its session."""
    response = client.post(
        "/api/v1/session/login", json={"email": "ceo@example.com", "name": "Mallory"}
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_a_wrong_token_is_refused():
    response = client.get("/api/v1/session", headers={INTERNAL_TOKEN_HEADER: "wrong"})
    assert response.status_code == 401


def test_the_correct_token_reaches_normal_authentication():
    response = client.get(
        "/api/v1/session",
        headers={INTERNAL_TOKEN_HEADER: get_settings().internal_api_token},
    )
    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.E_AUTHZ


def test_an_unconfigured_token_refuses_everything(monkeypatch):
    monkeypatch.setattr(get_settings(), "internal_api_token", "")
    response = client.get("/api/v1/session", headers={INTERNAL_TOKEN_HEADER: ""})
    assert response.status_code == 401


def test_health_needs_no_token():
    assert client.get("/healthz").status_code == 200


def test_slack_routes_use_their_signature_not_the_token():
    response = client.post("/slack/events", content=b"{}")
    assert response.status_code == 401
    assert b"E_INTERNAL_AUTH" not in response.content
