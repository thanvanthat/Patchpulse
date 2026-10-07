from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.db.session import get_session

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: CheckStatus
    db: CheckStatus
    redis: CheckStatus


async def check_db(session: AsyncSession) -> CheckStatus:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return "error"
    return "ok"


async def check_redis() -> CheckStatus:
    client = Redis.from_url(get_settings().redis_url, socket_timeout=2)
    try:
        await client.ping()
    except Exception:
        return "error"
    finally:
        await client.aclose()
    return "ok"


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> HealthResponse:
    db, redis = await check_db(session), await check_redis()
    ok = db == "ok" and redis == "ok"
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if ok else "error", db=db, redis=redis)
