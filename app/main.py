import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.slack import router as slack_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.correlation import get_correlation_id, set_correlation_id
from app.core.errors import BankReconError
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="2.0")

# PRD section 12: Slack Sign In with OIDC, session cookie. workspace_id is derived
# from the session, never from a request body.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.slack_signing_secret or "dev-only-session-key",
    https_only=not settings.demo_mode,
    same_site="lax",
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    """PRD section 19: every response carries the correlation id it was served under."""
    correlation_id = set_correlation_id(request.headers.get("X-Correlation-ID"))
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    logger.info(
        "request",
        extra={
            "component": "http",
            "action": f"{request.method} {request.url.path}",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "outcome": str(response.status_code),
        },
    )
    return response


@app.exception_handler(BankReconError)
async def bankrecon_error_handler(request: Request, exc: BankReconError) -> JSONResponse:
    """PRD section 12: every 4xx carries {code, message, details}."""
    logger.warning(
        "handled_error",
        extra={"component": "http", "action": "error", "error_code": str(exc.code)},
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_payload(get_correlation_id()),
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)

# Slack posts to fixed URLs configured in the app manifest, so these sit at the
# root rather than under the versioned API prefix.
app.include_router(slack_router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness only. Never touches the database, so it stays up during an outage."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    """Readiness: database reachable, migrations current, Slack auth valid."""
    from app.services.health import readiness_report

    report = await readiness_report()
    status = 200 if report["ready"] else 503
    return JSONResponse(status_code=status, content=report)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)
