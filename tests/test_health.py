import pytest
from httpx import AsyncClient

from apps.api.routes import health


async def test_health_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_health_reports_redis_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> health.CheckStatus:
        return "error"

    monkeypatch.setattr(health, "check_redis", broken)
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "error", "db": "ok", "redis": "error"}
