from typing import Literal

from ..internal._result import DBClient, with_tenant_context


async def update_booking_sync_status(
    db: DBClient,
    tenant_id: str,
    booking_id: str,
    provider_event_id: str | None,
    client_event_id: str | None,
    status: Literal["synced", "partial", "pending"],
    retry_count: int,
    error_msg: str | None = None,
) -> None:
    async def operation() -> None:
        # 1. Update Booking
        await db.execute(
            """
            UPDATE bookings
            SET gcal_provider_event_id = COALESCE($1, gcal_provider_event_id),
                gcal_client_event_id = COALESCE($2, gcal_client_event_id),
                gcal_sync_status = $3,
                gcal_retry_count = $4,
                updated_at = NOW()
            WHERE booking_id = $5::uuid
            """,
            provider_event_id,
            client_event_id,
            status,
            retry_count,
            booking_id,
        )

        # 2. Add to Audit if error
        if error_msg:
            await db.execute(
                """
                INSERT INTO booking_audit (booking_id, changed_by, reason, metadata)
                VALUES ($1::uuid, 'system', $2, $3::jsonb)
                """,
                booking_id,
                f"GCal Sync Failure: {status}",
                '{"error": "' + error_msg.replace('"', '\\"') + '"}',
            )

        return

    return await with_tenant_context(db, tenant_id, operation)
