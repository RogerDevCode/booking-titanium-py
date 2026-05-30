import asyncpg
import contextvars
from typing import Optional
from contextlib import asynccontextmanager

# Context variable to hold the active transaction connection
_transaction_conn: contextvars.ContextVar[Optional[asyncpg.pool.PoolConnectionProxy]] = contextvars.ContextVar("_transaction_conn", default=None)

class DatabaseClient:
    def __init__(self, dsn: str, pool_size: int = 10) -> None:
        self._dsn = dsn
        self._pool_size = pool_size
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=1,
                max_size=self._pool_size,
            )

    async def disconnect(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DatabaseClient not connected")
        return self._pool

    @asynccontextmanager
    async def transaction(self):
        """
        Manages a database transaction block. 
        Propagates the connection via contextvars so inner queries use the same transaction.
        """
        # If we are already in a transaction, just yield (nested transaction unsupported but harmless)
        if _transaction_conn.get() is not None:
            yield
            return

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                token = _transaction_conn.set(conn)
                try:
                    yield conn
                finally:
                    _transaction_conn.reset(token)

    async def execute(self, query: str, *args):
        conn = _transaction_conn.get()
        if conn:
            return await conn.execute(query, *args)
        async with self.pool.acquire() as conn_new:
            return await conn_new.execute(query, *args)

    async def fetch(self, query: str, *args):
        conn = _transaction_conn.get()
        if conn:
            return await conn.fetch(query, *args)
        async with self.pool.acquire() as conn_new:
            return await conn_new.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        conn = _transaction_conn.get()
        if conn:
            return await conn.fetchrow(query, *args)
        async with self.pool.acquire() as conn_new:
            return await conn_new.fetchrow(query, *args)

