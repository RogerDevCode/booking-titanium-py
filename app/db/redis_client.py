import redis.asyncio as redis_async
import redis.exceptions
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from app.core.config import settings
from app.core.logging import logger

class RedisClient:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis = None

    async def connect(self) -> None:
        if self._redis is None:
            self._redis = redis_async.from_url(self._redis_url, decode_responses=True)
            logger.info("Connected to Redis", url=self._redis_url)

    async def disconnect(self):
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    @property
    def client(self) -> redis_async.Redis:
        if self._redis is None:
            raise RuntimeError("RedisClient not connected")
        return self._redis

    @asynccontextmanager
    async def get_chat_lock(self, chat_id: int, timeout: int = 30) -> AsyncGenerator[None, None]:
        """
        Acquires a distributed lock for a given chat_id using Redis.
        Replaces pg_advisory_xact_lock to avoid blocking DB connections.
        """
        lock_name = f"chat_lock:{chat_id}"
        # We use a blocking lock that will wait to acquire
        # timeout sets the maximum life of the lock (prevent deadlocks if worker crashes)
        # blocking_timeout controls how long we wait to acquire before giving up
        lock = self.client.lock(name=lock_name, timeout=timeout, blocking_timeout=60)
        acquired = await lock.acquire()
        
        if not acquired:
            logger.error("Failed to acquire Redis lock", chat_id=chat_id)
            raise TimeoutError(f"Could not acquire lock for chat_id {chat_id}")
            
        try:
            yield
        finally:
            try:
                await lock.release()
            except redis.exceptions.LockError:
                # Lock might have expired if task took too long, that's fine
                logger.warning("Lock was already released or expired", chat_id=chat_id)

redis_client = RedisClient(redis_url=settings.REDIS_URL)
