from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from redis.asyncio import Redis


class CalendarPort(Protocol):
    async def sync(self, booking: dict[str, Any]) -> None: ...


class NotifierPort(Protocol):
    async def send(self, booking: dict[str, Any]) -> None: ...


class RedisBookingRepo:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def get_state(self, chat_id: str) -> dict[str, Any]:
        data = await self.redis.get(f"booking:conv:{chat_id}")
        return cast("dict[str, Any]", json.loads(data)) if data else {}

    async def set_state(self, chat_id: str, state: dict[str, Any]) -> None:
        await self.redis.set(f"booking:conv:{chat_id}", json.dumps(state), ex=1800)

    async def is_duplicate(self, key: str, ttl: int = 60) -> bool:
        res = await self.redis.set(f"booking:idem:{key}", "1", nx=True, ex=ttl)
        return res is None


class GCalClient:
    async def sync(self, booking: dict[str, Any]) -> None:
        pass


class TelegramClient:
    async def send(self, booking: dict[str, Any]) -> None:
        pass
