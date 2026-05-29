from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from ._result import DBClient


class ActiveBookingInfo(TypedDict):
    booking_id: str
    start_time: object
    provider_name: str
    service_name: str


async def get_active_booking_for_provider(conn: DBClient, client_id: str, provider_id: str) -> ActiveBookingInfo | None:
    """
    Checks if a client has an active (confirmed/pending) booking with a specific provider.
    """
    query = """
        SELECT b.booking_id, b.start_time, p.name as provider_name, s.name as service_name
        FROM bookings b
        JOIN providers p ON p.provider_id = b.provider_id
        JOIN services s ON s.service_id = b.service_id
        WHERE b.client_id = $1::uuid
          AND b.provider_id = $2::uuid
          AND b.status NOT IN ('cancelled', 'no_show', 'rescheduled')
          AND b.start_time > NOW()
        ORDER BY b.start_time ASC
        LIMIT 1
    """
    try:
        row = await conn.fetchrow(query, client_id, provider_id)
        if not row:
            return None

        res: ActiveBookingInfo = {
            "booking_id": str(row["booking_id"]),
            "start_time": row["start_time"],
            "provider_name": str(row["provider_name"]),
            "service_name": str(row["service_name"]),
        }
        return res
    except Exception as e:
        raise RuntimeError(f"Error checking active bookings: {e}") from e
