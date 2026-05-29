from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    Protocol,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class DBClient(Protocol):
    """Protocol for database client operations."""

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]: ...

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None: ...

    async def fetchval(self, query: str, *args: object) -> object | None: ...

    async def execute(self, query: str, *args: object) -> str: ...

    async def close(self) -> None: ...


async def with_tenant_context[T](client: DBClient, tenant_id: str, operation: Callable[[], Awaitable[T]]) -> T:
    """Executes DB logic within a tenant context. Raises on any error."""
    if not _UUID_RE.match(tenant_id):
        raise ValueError(f'invalid_tenant_id: "{tenant_id}"')

    try:
        await client.execute("BEGIN")
        await client.execute("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
        result = await operation()
        await client.execute("COMMIT")
        return result
    except Exception:
        try:
            await client.execute("ROLLBACK")
        except Exception as rb_err:
            from ._wmill_adapter import log

            log("ROLLBACK_FAILED", error=str(rb_err), module="transaction_wrapper")
            raise
        raise


async def with_admin_context[T](client: DBClient, operation: Callable[[], Awaitable[T]]) -> T:
    """Executes DB logic with app.admin_override = 'true' to bypass RLS. Raises on any error."""
    try:
        await client.execute("BEGIN")
        await client.execute("SELECT set_config('app.admin_override', 'true', true)")
        result = await operation()
        await client.execute("COMMIT")
        return result
    except Exception:
        try:
            await client.execute("ROLLBACK")
        except Exception as rb_err:
            from ._wmill_adapter import log

            log("ROLLBACK_FAILED", error=str(rb_err), module="transaction_wrapper")
            raise
        raise
