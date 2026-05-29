from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from datetime import datetime

    from ..internal._result import DBClient
    from ..internal._state_machine import BookingStatus
    from ._reschedule_models import BookingRow, RescheduleInput, RescheduleWriteResult, ServiceRow


class RescheduleRepository(Protocol):
    async def fetch_booking(self, booking_id: str) -> BookingRow | None: ...
    async def fetch_service(self, service_id: str) -> ServiceRow | None: ...
    async def check_overlap(
        self, provider_id: str, exclude_booking_id: str, new_start: datetime, new_end: datetime
    ) -> bool: ...
    async def check_client_overlap(
        self, client_id: str, exclude_booking_id: str, new_start: datetime, new_end: datetime
    ) -> bool: ...
    async def execute_reschedule(
        self, input_data: RescheduleInput, old_booking: BookingRow, service: ServiceRow, new_end: datetime, new_key: str
    ) -> RescheduleWriteResult | None: ...


class PostgresRescheduleRepository:
    def __init__(self, client: DBClient) -> None:
        self._client = client

    async def fetch_booking(self, booking_id: str) -> BookingRow | None:
        row = await self._client.fetchrow(
            """
            SELECT booking_id, provider_id, client_id, service_id, status, start_time, end_time, idempotency_key
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
            "provider_id": str(row["provider_id"]),
            "client_id": str(row["client_id"]),
            "service_id": str(row["service_id"]),
            "status": cast("BookingStatus", str(row["status"])),
            "start_time": cast("datetime", row["start_time"]),
            "end_time": cast("datetime", row["end_time"]),
            "idempotency_key": str(row["idempotency_key"]),
        }

    async def fetch_service(self, service_id: str) -> ServiceRow | None:
        row = await self._client.fetchrow(
            """
            SELECT service_id, duration_minutes
            FROM services
            WHERE service_id = $1::uuid
            LIMIT 1
            """,
            service_id,
        )
        if not row:
            return None
        return cast(
            "ServiceRow",
            {"service_id": str(row["service_id"]), "duration_minutes": int(cast("Any", row["duration_minutes"]))},
        )

    async def check_overlap(
        self, provider_id: str, exclude_booking_id: str, new_start: datetime, new_end: datetime
    ) -> bool:
        row = await self._client.fetchrow(
            """
            SELECT booking_id FROM bookings
            WHERE provider_id = $1::uuid
              AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
              AND booking_id != $2::uuid
              AND start_time < $3::timestamptz
              AND end_time > $4::timestamptz
            LIMIT 1
            """,
            provider_id,
            exclude_booking_id,
            new_end.isoformat(),
            new_start.isoformat(),
        )
        return row is not None

    async def check_client_overlap(
        self, client_id: str, exclude_booking_id: str, new_start: datetime, new_end: datetime
    ) -> bool:
        row = await self._client.fetchrow(
            """
            SELECT booking_id FROM bookings
            WHERE client_id = $1::uuid
              AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
              AND booking_id != $2::uuid
              AND start_time < $3::timestamptz
              AND end_time > $4::timestamptz
            LIMIT 1
            """,
            client_id,
            exclude_booking_id,
            new_end.isoformat(),
            new_start.isoformat(),
        )
        return row is not None

    async def execute_reschedule(
        self, input_data: RescheduleInput, old_booking: BookingRow, service: ServiceRow, new_end: datetime, new_key: str
    ) -> RescheduleWriteResult | None:
        # Create new booking
        new_row = await self._client.fetchrow(
            """
            INSERT INTO bookings (
              client_id, provider_id, service_id,
              start_time, end_time, status, idempotency_key, rescheduled_from,
              gcal_sync_status
            ) VALUES (
              $1::uuid, $2::uuid, $3::uuid,
              $4::timestamptz, $5::timestamptz,
              'confirmed', $6, $7::uuid,
              'pending'
            )
            RETURNING booking_id, status, start_time, end_time
            """,
            old_booking["client_id"],
            old_booking["provider_id"],
            service["service_id"],
            input_data.new_start_time.isoformat(),
            new_end.isoformat(),
            new_key,
            old_booking["booking_id"],
        )

        if not new_row:
            return None

        nb_id = str(new_row["booking_id"])
        nb_status = str(new_row["status"])
        nb_start = str(new_row["start_time"])
        nb_end = str(new_row["end_time"])

        # Update old booking
        upd_row = await self._client.fetchrow(
            """
            UPDATE bookings
            SET status = 'rescheduled', updated_at = NOW()
            WHERE booking_id = $1::uuid
            RETURNING booking_id, status
            """,
            old_booking["booking_id"],
        )

        if not upd_row:
            # If update fails, it will rollback via with_tenant_context
            return None

        ub_id = str(upd_row["booking_id"])
        ub_status = str(upd_row["status"])

        # Audit rows
        await self._client.execute(
            """
            INSERT INTO booking_audit (booking_id, from_status, to_status, changed_by, actor_id, reason, metadata)
            VALUES (
                $1::uuid, $2, 'rescheduled', 
                $3, $4::uuid, 
                $5, 
                $6::jsonb
            )
            """,
            old_booking["booking_id"],
            old_booking["status"],
            input_data.actor,
            input_data.actor_id,
            input_data.reason or "Rescheduled",
            json.dumps({"new_booking_id": nb_id}),
        )

        await self._client.execute(
            """
            INSERT INTO booking_audit (booking_id, from_status, to_status, changed_by, actor_id, reason, metadata)
            VALUES (
                $1::uuid, null, 'confirmed', 
                $2, $3::uuid, 
                'Created via reschedule', 
                $4::jsonb
            )
            """,
            nb_id,
            input_data.actor,
            input_data.actor_id,
            json.dumps({"old_booking_id": old_booking["booking_id"]}),
        )

        return {
            "new_booking_id": nb_id,
            "new_status": nb_status,
            "new_start_time": nb_start,
            "new_end_time": nb_end,
            "old_booking_id": ub_id,
            "old_status": ub_status,
        }
