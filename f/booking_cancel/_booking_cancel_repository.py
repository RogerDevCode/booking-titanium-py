import json
from typing import Protocol, cast

from ..internal._result import DBClient
from ..internal._state_machine import BookingStatus
from ._booking_cancel_models import BookingLookup, CancelBookingInput, UpdatedBooking


class BookingCancelRepository(Protocol):
    async def fetch_booking(self, booking_id: str) -> BookingLookup | None: ...
    async def lock_booking(self, booking_id: str) -> BookingStatus | None: ...
    async def update_booking_status(self, input_data: CancelBookingInput) -> UpdatedBooking | None: ...
    async def insert_audit_trail(self, input_data: CancelBookingInput, booking: BookingLookup) -> None: ...
    async def trigger_gcal_sync(self, booking_id: str) -> None: ...


class PostgresBookingCancelRepository:
    def __init__(self, client: DBClient) -> None:
        self._client = client

    async def fetch_booking(self, booking_id: str) -> BookingLookup | None:
        row = await self._client.fetchrow(
            """
            SELECT booking_id, status, client_id, provider_id,
                   gcal_provider_event_id, gcal_client_event_id
            FROM bookings
            WHERE booking_id = $1::uuid
            LIMIT 1
            """,
            booking_id,
        )
        if not row:
            return None
        return {
            "booking_id": str(row["booking_id"]),
            "status": cast("BookingStatus", str(row["status"])),
            "client_id": str(row["client_id"]),
            "provider_id": str(row["provider_id"]),
            "gcal_provider_event_id": str(row["gcal_provider_event_id"]) if row.get("gcal_provider_event_id") else None,
            "gcal_client_event_id": str(row["gcal_client_event_id"]) if row.get("gcal_client_event_id") else None,
        }

    async def lock_booking(self, booking_id: str) -> BookingStatus | None:
        row = await self._client.fetchrow(
            """
            SELECT status FROM bookings 
            WHERE booking_id = $1::uuid 
            FOR UPDATE
            """,
            booking_id,
        )
        if not row:
            return None
        return cast("BookingStatus", str(row["status"]))

    async def update_booking_status(self, input_data: CancelBookingInput) -> UpdatedBooking | None:
        row = await self._client.fetchrow(
            """
            UPDATE bookings
            SET status = 'cancelled',
                cancelled_by = $1,
                cancellation_reason = $2,
                updated_at = NOW()
            WHERE booking_id = $3::uuid
            RETURNING booking_id, status, cancelled_by, cancellation_reason
            """,
            input_data.actor,
            input_data.reason,
            input_data.booking_id,
        )
        if not row:
            return None

        return {
            "booking_id": str(row["booking_id"]),
            "status": str(row["status"]),
            "cancelled_by": str(row["cancelled_by"]),
            "cancellation_reason": str(row["cancellation_reason"]) if row.get("cancellation_reason") else None,
        }

    async def insert_audit_trail(self, input_data: CancelBookingInput, booking: BookingLookup) -> None:
        metadata = {
            "gcal_provider_event_id": booking["gcal_provider_event_id"],
            "gcal_client_event_id": booking["gcal_client_event_id"],
        }

        await self._client.execute(
            """
            INSERT INTO booking_audit (
                booking_id, from_status, to_status, changed_by, actor_id, reason, metadata
            ) VALUES (
                $1::uuid, 
                $2, 
                'cancelled', 
                $3, 
                $4::uuid, 
                $5, 
                $6::jsonb
            )
            """,
            input_data.booking_id,
            booking["status"],
            input_data.actor,
            input_data.actor_id,
            input_data.reason or "Cancelled via API",
            json.dumps(metadata),
        )

    async def trigger_gcal_sync(self, booking_id: str) -> None:
        await self._client.execute(
            """
            UPDATE bookings
            SET gcal_sync_status = 'pending', gcal_retry_count = 0
            WHERE booking_id = $1::uuid
            """,
            booking_id,
        )
