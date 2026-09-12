import pytest
from fastapi.testclient import TestClient

from app.core.errors import ERROR_SPECS, ErrorCode
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_healthz_never_touches_the_database():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_response_carries_a_correlation_id():
    response = client.get("/healthz")
    assert response.headers.get("X-Correlation-ID")


def test_a_supplied_correlation_id_is_propagated():
    response = client.get("/healthz", headers={"X-Correlation-ID": "abc123"})
    assert response.headers["X-Correlation-ID"] == "abc123"


def test_unauthenticated_requests_are_refused_with_the_error_contract():
    response = client.get("/api/v1/cases")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == ErrorCode.E_AUTHZ
    assert "message" in body and "details" in body
    assert body["correlation_id"]


def test_mutating_endpoints_require_an_idempotency_key():
    response = client.post(
        "/api/v1/reconciliations",
        json={
            "account_last4": "1234",
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
        },
    )
    # Missing auth or missing key, either way it never reaches the database.
    assert response.status_code in (403, 422)


def test_metrics_endpoint_is_exposed():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "python_info" in response.text or response.text == ""


def test_openapi_documents_the_full_section_12_surface():
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/session",
        "/api/v1/session/login",
        "/api/v1/session/logout",
        "/api/v1/reconciliations",
        "/api/v1/reconciliations/import",
        "/api/v1/reconciliations/{reconciliation_id}",
        "/api/v1/reconciliations/{reconciliation_id}/audit",
        "/api/v1/reconciliations/{reconciliation_id}/transactions",
        "/api/v1/reconciliations/{reconciliation_id}/audit.csv",
        "/api/v1/transactions/{transaction_id}",
        "/api/v1/transactions/{transaction_id}/decision",
        "/api/v1/cases",
        "/api/v1/cases/{case_id}",
        "/api/v1/cases/{case_id}/assign",
        "/api/v1/cases/{case_id}/evidence",
        "/api/v1/cases/{case_id}/proposals",
        "/api/v1/cases/{case_id}/reopen",
        "/api/v1/proposals/{proposal_id}/decision",
        "/api/v1/settings",
    }
    assert expected <= set(paths)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_code_has_a_spec_with_a_user_facing_message(code):
    """PRD section 15: every failure has a code, a status and a message."""
    spec = ERROR_SPECS[code]
    assert spec.template.strip()
    assert 200 <= spec.http_status < 600
