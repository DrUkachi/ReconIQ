import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def readiness_report() -> dict[str, Any]:
    """PRD section 21: readyz fails if migrations are pending.

    Each check degrades independently so the report names the failure rather than
    returning a bare 503.
    """
    settings = get_settings()
    checks: dict[str, Any] = {}

    checks["database"] = await _check_database()
    checks["migrations"] = await _check_migrations()
    checks["slack"] = _check_configured(settings.slack_bot_token, "SLACK_BOT_TOKEN")
    checks["anthropic"] = _check_configured(settings.anthropic_api_key, "ANTHROPIC_API_KEY")

    return {"ready": all(c["ok"] for c in checks.values()), "checks": checks}


async def _check_database() -> dict[str, Any]:
    try:
        from sqlalchemy import text

        from app.core.db import get_engine

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


async def _check_migrations() -> dict[str, Any]:
    try:
        from sqlalchemy import text

        from app.core.db import get_engine

        async with get_engine().connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            version = result.scalar_one_or_none()
        return {"ok": version is not None, "version": version}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def _check_configured(value: str, name: str) -> dict[str, Any]:
    return {"ok": bool(value), "detail": f"{name} not set" if not value else None}
