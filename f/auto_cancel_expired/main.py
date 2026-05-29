# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "asyncpg>=0.30.0",
#   "pydantic>=2.10.0",
#   "beartype>=0.19.0",
# ]
# ///
from __future__ import annotations

import json
from typing import Any

from f.internal._db_client import create_db_client
from f.internal._wmill_adapter import log

_EXPIRY_MINUTES: int = 30
_MODULE = "auto_cancel_expired"


async def _main_async() -> dict[str, Any]:
    conn = await create_db_client()
    try:
        await conn.execute("BEGIN")
        try:
            # Atomic batch: UPDATE returning ids + INSERT events in one CTE
            payload = json.dumps({"reason": "expired_pending", "expiry_minutes": _EXPIRY_MINUTES})
            await conn.execute(
                """
                WITH expired AS (
                    UPDATE bookings
                    SET status = 'cancelled',
                        updated_at = NOW(),
                        cancellation_reason = 'expired_pending',
                        cancelled_by = 'system'
                    WHERE status = 'pending'
                      AND created_at < NOW() - ($1 || ' minutes')::interval
                    RETURNING booking_id
                )
                INSERT INTO booking_events
                    (booking_id, event_type, previous_status, new_status,
                     actor_type, idempotency_key, payload)
                SELECT
                    booking_id,
                    'AUTO_CANCEL_EXPIRED',
                    'pending',
                    'cancelled',
                    'system',
                    'auto-cancel-expired-' || booking_id,
                    $2::jsonb
                FROM expired
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                str(_EXPIRY_MINUTES),
                payload,
            )
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

        # Fetch the IDs that were just cancelled (for reporting)
        rows = await conn.fetch(
            """
            SELECT booking_id
            FROM bookings
            WHERE status = 'cancelled'
              AND cancellation_reason = 'expired_pending'
              AND updated_at > NOW() - INTERVAL '1 minute'
            """,
        )
        cancelled_ids = [str(r["booking_id"]) for r in rows]
        log("AUTO_CANCEL_EXPIRED_SUMMARY", count=len(cancelled_ids), module=_MODULE)
        return {"cancelled_count": len(cancelled_ids), "cancelled_ids": cancelled_ids}
    finally:
        await conn.close()


def main() -> dict[str, Any]:
    import asyncio

    return asyncio.run(_main_async())
