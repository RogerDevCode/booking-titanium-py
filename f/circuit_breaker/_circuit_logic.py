from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._circuit_models import CircuitState


async def get_state(db: DBClient, service_id: str) -> CircuitState | None:
    rows = await db.fetch(
        """
        SELECT service_id, state, failure_count, success_count,
               failure_threshold, success_threshold, timeout_seconds,
               opened_at, half_open_at, last_failure_at, last_success_at,
               last_error_message
        FROM circuit_breaker_state
        WHERE service_id = $1
        LIMIT 1
        """,
        service_id,
    )
    if not rows:
        return None

    r = rows[0]

    # Helper to convert potential datetime/str to isoformat str
    def to_iso(val: object) -> str | None:
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, str):
            return val
        return None

    res: CircuitState = {
        "service_id": str(r["service_id"]),
        "state": cast("Literal['closed', 'open', 'half-open']", str(r["state"])),
        "failure_count": int(cast("Any", r["failure_count"])),
        "success_count": int(cast("Any", r["success_count"])),
        "failure_threshold": int(cast("Any", r["failure_threshold"])),
        "success_threshold": int(cast("Any", r["success_threshold"])),
        "timeout_seconds": int(cast("Any", r["timeout_seconds"])),
        "opened_at": to_iso(r.get("opened_at")),
        "half_open_at": to_iso(r.get("half_open_at")),
        "last_failure_at": to_iso(r.get("last_failure_at")),
        "last_success_at": to_iso(r.get("last_success_at")),
        "last_error_message": str(r["last_error_message"]) if r.get("last_error_message") else None,
    }
    return res


async def init_service(db: DBClient, service_id: str) -> None:
    await db.execute(
        """
        INSERT INTO circuit_breaker_state (service_id, state, failure_count, success_count)
        VALUES ($1, 'closed', 0, 0)
        ON CONFLICT (service_id) DO NOTHING
        """,
        service_id,
    )
