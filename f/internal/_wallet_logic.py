# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "asyncpg>=0.30.0",
# ]
# ///
from __future__ import annotations

from typing import Final, TypedDict, cast

from ._wmill_adapter import log

MODULE: Final[str] = "wallet_logic"


class FastTrackOption(TypedDict):
    provider_id: str
    service_id: str
    provider_name: str
    service_name: str
    count: int


async def get_fast_track_option(client_id: str, pg_url: str) -> FastTrackOption | None:
    """Calculates the most common booking for a client to offer as Fast-Track."""
    from ._db_client import create_db_client

    db = await create_db_client(pg_url)
    try:
        # Find the most frequent provider/service pair for this client
        row = await db.fetchrow(
            """
            SELECT
                b.provider_id::text,
                b.service_id::text,
                p.name AS provider_name,
                s.name AS service_name,
                COUNT(*) as booking_count
            FROM bookings b
            JOIN providers p ON p.provider_id = b.provider_id
            JOIN services s ON s.service_id = b.service_id
            WHERE b.client_id = $1::uuid
              AND b.status NOT IN ('cancelled', 'error')
            GROUP BY b.provider_id, b.service_id, p.name, s.name
            ORDER BY booking_count DESC
            LIMIT 1
            """,
            client_id,
        )
        if not row:
            return None

        return {
            "provider_id": str(row["provider_id"]),
            "service_id": str(row["service_id"]),
            "provider_name": str(row["provider_name"]),
            "service_name": str(row["service_name"]),
            "count": int(cast("int", row["booking_count"])),
        }
    except Exception as e:
        log("WALLET_FAST_TRACK_ERROR", error=str(e), client_id=client_id, module=MODULE)
        return None
    finally:
        await db.close()
