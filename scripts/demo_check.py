"""PRD section 21: verify the system is presentable, in under 30 seconds.

Green output or a named failure. Run immediately before presenting.
"""

import asyncio
import pathlib
import sys

from app.core.config import get_settings

REPO = pathlib.Path(__file__).resolve().parent.parent

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


async def main() -> int:
    settings = get_settings()
    results: list[tuple[str, bool, str]] = []

    results.append(await _database())
    results.append(await _migrations())
    results.append(_configured("Slack bot token", settings.slack_bot_token))
    results.append(_configured("Slack signing secret", settings.slack_signing_secret))
    results.append(_configured("Anthropic API key", settings.anthropic_api_key))
    results.append(_fixtures())
    results.append(await _no_failed_jobs())
    results.append(await _outbox_drained())

    for name, ok, detail in results:
        mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))

    failures = [name for name, ok, _ in results if not ok]
    if failures:
        print(f"\n{RED}{len(failures)} check(s) failed:{RESET} {', '.join(failures)}")
        return 1
    print(f"\n{GREEN}All checks green. Ready to present.{RESET}")
    return 0


async def _database() -> tuple[str, bool, str]:
    try:
        from sqlalchemy import text

        from app.core.db import get_engine

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return ("Database reachable", True, "")
    except Exception as exc:
        return ("Database reachable", False, type(exc).__name__)


async def _migrations() -> tuple[str, bool, str]:
    try:
        from sqlalchemy import text

        from app.core.db import get_engine

        async with get_engine().connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        return ("Migrations applied", version is not None, f"at {version}" if version else "")
    except Exception as exc:
        return ("Migrations applied", False, type(exc).__name__)


async def _no_failed_jobs() -> tuple[str, bool, str]:
    try:
        from sqlalchemy import text

        from app.core.db import get_engine

        async with get_engine().connect() as conn:
            count = (
                await conn.execute(text("SELECT count(*) FROM job WHERE state = 'FAILED'"))
            ).scalar_one()
        return ("No failed jobs", count == 0, f"{count} failed" if count else "")
    except Exception as exc:
        return ("No failed jobs", False, type(exc).__name__)


async def _outbox_drained() -> tuple[str, bool, str]:
    try:
        from sqlalchemy import text

        from app.core.db import get_engine

        async with get_engine().connect() as conn:
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM slack_outbox WHERE state <> 'SENT'")
                )
            ).scalar_one()
        return ("Outbox drained", count == 0, f"{count} pending" if count else "")
    except Exception as exc:
        return ("Outbox drained", False, type(exc).__name__)


def _configured(name: str, value: str) -> tuple[str, bool, str]:
    return (name, bool(value), "" if value else "not set")


def _fixtures() -> tuple[str, bool, str]:
    required = ["ledger_march.csv"]
    fixtures = REPO / "tests" / "fixtures"
    missing = [f for f in required if not (fixtures / f).exists()]
    return ("Fixtures present", not missing, f"missing {', '.join(missing)}" if missing else "")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
