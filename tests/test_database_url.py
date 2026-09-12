import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://user:pw@dpg-abc123-a/reconiq",
            "postgresql+asyncpg://user:pw@dpg-abc123-a/reconiq",
        ),
        (
            "postgres://user:pw@dpg-abc123-a:5432/reconiq",
            "postgresql+asyncpg://user:pw@dpg-abc123-a:5432/reconiq",
        ),
        (
            "postgresql+asyncpg://user:pw@localhost:5432/reconiq",
            "postgresql+asyncpg://user:pw@localhost:5432/reconiq",
        ),
    ],
)
def test_hosted_postgres_urls_use_the_async_driver(raw, expected):
    assert Settings(database_url=raw).database_url == expected
