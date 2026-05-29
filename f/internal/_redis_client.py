from __future__ import annotations

import os
from typing import Final

from redis.asyncio import ConnectionPool, Redis

from ._wmill_adapter import get_variable

# ============================================================================
# REDIS CLIENT — Single Source of Truth for Redis connections
# ============================================================================

REDIS_TTL: Final[int] = 1800  # 30 minutes

_VALID_SCHEMES: Final[tuple[str, ...]] = ("redis://", "rediss://", "unix://")

_POOLS: dict[str, ConnectionPool] = {}


def _resolve_redis_url() -> str | None:
    # 1. Local environment
    local_url = os.getenv("REDIS_URL")
    if local_url:
        return local_url

    # 2. Windmill variables (Priority order)
    paths = ["g/all/REDIS_URL", "u/admin/REDIS_URL", "REDIS_URL"]
    for path in paths:
        res = get_variable(path)
        if res is not None:
            return res

    return None


def _ensure_scheme(url: str) -> str:
    """Inject redis:// scheme if the URL is a bare hostname or missing a valid scheme."""
    if any(url.startswith(s) for s in _VALID_SCHEMES):
        return url
    return f"redis://{url}"


async def create_redis_client(redis_url: str | None = None) -> Redis:
    """
    Factory for Redis client. Accepts an explicit URL (preferred — callers should
    pass the value received from flow input) and falls back to environment/variable
    resolution. Scheme injection handles bare hostnames like 'redis:6379'.

    Uses a global ConnectionPool cache to prevent connection churn across modules
    in long-running processes (like Arq workers). Calling .aclose() on the returned
    client will gracefully release the connection back to the pool without destroying
    the underlying shared pool.
    """
    if not redis_url:
        redis_url = _resolve_redis_url()
    if not redis_url:
        redis_url = "redis://redis:6379"

    final_url = _ensure_scheme(redis_url)

    import asyncio

    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0

    cache_key = f"{final_url}:{loop_id}"

    if cache_key not in _POOLS:
        _POOLS[cache_key] = ConnectionPool.from_url(
            final_url,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
            health_check_interval=30,
            max_connections=20,
        )

    return Redis(connection_pool=_POOLS[cache_key])
