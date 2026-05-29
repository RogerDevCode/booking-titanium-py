from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg

from ._result import DBClient  # noqa: TC001


class _AsyncpgConn(Protocol):
    """Internal protocol to contain Any leakage from asyncpg."""

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]: ...
    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None: ...
    async def fetchval(self, query: str, *args: object) -> object | None: ...
    async def execute(self, query: str, *args: object) -> str: ...
    async def close(self) -> None: ...


type _AsyncpgOptionValue = int | str


def _split_asyncpg_connect_options(db_url: str) -> tuple[str, dict[str, _AsyncpgOptionValue]]:
    parsed = urlparse(db_url)
    if not parsed.query:
        return db_url, {}

    params = parse_qs(parsed.query, keep_blank_values=True)
    asyncpg_params = frozenset({"statement_cache_size", "max_cached_statement_lifetime"})

    connect_kwargs: dict[str, _AsyncpgOptionValue] = {}
    remaining: dict[str, list[str]] = {}

    for key, values in params.items():
        if key in asyncpg_params and values:
            raw_value = values[0]
            connect_kwargs[key] = int(raw_value) if raw_value.isdigit() else raw_value
            continue
        remaining[key] = values

    cleaned_query = urlencode([(key, value) for key, values in remaining.items() for value in values])
    cleaned_url = urlunparse(parsed._replace(query=cleaned_query))
    return cleaned_url, connect_kwargs


def _resolve_db_url() -> str | None:
    local_url = os.getenv("DATABASE_URL")
    if local_url and local_url.strip():
        return local_url
    return None


_global_pool: Any = None
_global_loop: Any = None


async def _get_pool(db_url: str, connect_kwargs: dict[str, _AsyncpgOptionValue]) -> Any:  # noqa: ANN401
    global _global_pool, _global_loop

    current_loop = asyncio.get_running_loop()

    if _global_pool is not None:
        if _global_loop is current_loop and not _global_pool.is_closing():
            return _global_pool
        with contextlib.suppress(Exception):
            await _global_pool.close()
        _global_pool = None

    _global_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=10, **connect_kwargs)
    _global_loop = current_loop
    return _global_pool


async def create_db_client(db_url: str | None = None) -> DBClient:
    # Handle empty strings as None
    if db_url is not None and not db_url.strip():
        db_url = None
    db_url = db_url or _resolve_db_url()
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL is required. Set it in .env or as environment variable."
        )

    clean_db_url, connect_kwargs = _split_asyncpg_connect_options(db_url)
    connect_kwargs.pop("statement_cache_size", None)

    pool = await _get_pool(clean_db_url, connect_kwargs)
    conn = await pool.acquire()

    class AsyncpgPoolWrapper:
        def __init__(self, pool_conn: _AsyncpgConn, pool_ref: Any) -> None:  # noqa: ANN401
            self.conn = pool_conn
            self.pool = pool_ref

        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            rows = await self.conn.fetch(query, *args)
            return [dict(r) for r in rows]

        async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
            row = await self.conn.fetchrow(query, *args)
            return dict(row) if row else None

        async def fetchval(self, query: str, *args: object) -> object | None:
            return await self.conn.fetchval(query, *args)

        async def execute(self, query: str, *args: object) -> str:
            return await self.conn.execute(query, *args)

        async def close(self) -> None:
            await self.pool.release(self.conn)

    wrapped_conn = cast("_AsyncpgConn", cast("object", conn))
    return cast("DBClient", AsyncpgPoolWrapper(wrapped_conn, pool))
