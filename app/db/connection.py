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
            # Ensure outbox table exists
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS outbox_messages (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        text TEXT NOT NULL,
                        reply_markup JSONB,
                        status VARCHAR(20) DEFAULT 'PENDING',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    );
                    
                    ALTER TABLE users 
                    ADD COLUMN IF NOT EXISTS address VARCHAR(255),
                    ADD COLUMN IF NOT EXISTS rut VARCHAR(20);
                    
                    ALTER TABLE providers 
                    ADD COLUMN IF NOT EXISTS waitlist_batch_size INT DEFAULT 3,
                    ADD COLUMN IF NOT EXISTS waitlist_delay_minutes INT DEFAULT 15;
                    
                    ALTER TABLE slots
                    DROP CONSTRAINT IF EXISTS unique_provider_start_time,
                    ADD CONSTRAINT unique_provider_start_time UNIQUE (provider_id, start_time);
                    
                    CREATE TABLE IF NOT EXISTS waitlist (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id BIGINT NOT NULL REFERENCES users(id),
                        provider_id UUID NOT NULL REFERENCES providers(id),
                        status VARCHAR(50) DEFAULT 'ACTIVE',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        UNIQUE (user_id, provider_id, status)
                    );
                    
                    CREATE TABLE IF NOT EXISTS waitlist_notifications (
                        id SERIAL PRIMARY KEY,
                        waitlist_id UUID NOT NULL REFERENCES waitlist(id) ON DELETE CASCADE,
                        slot_id UUID NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
                        notified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        UNIQUE (waitlist_id, slot_id)
                    );
                    
                    ALTER TABLE providers 
                    ADD COLUMN IF NOT EXISTS slot_duration_minutes INT DEFAULT 30,
                    ADD COLUMN IF NOT EXISTS buffer_time_minutes INT DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS notice_period_hours INT DEFAULT 4;
                    
                    CREATE TABLE IF NOT EXISTS provider_schedules (
                        id SERIAL PRIMARY KEY,
                        provider_id UUID NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
                        day_of_week INT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Monday, 6=Sunday
                        start_time TIME NOT NULL,
                        end_time TIME NOT NULL,
                        is_active BOOLEAN DEFAULT true,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    );
                    
                    CREATE TABLE IF NOT EXISTS provider_exceptions (
                        id SERIAL PRIMARY KEY,
                        provider_id UUID NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
                        start_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
                        end_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
                        reason VARCHAR(255),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    );
                """)

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

