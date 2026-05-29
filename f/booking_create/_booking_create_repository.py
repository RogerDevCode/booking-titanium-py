from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from datetime import date, datetime

    from ..internal._result import DBClient
    from ._booking_create_models import (
        BookingContext,
        BookingCreated,
        ClientContext,
        InputSchema,
        ProviderContext,
        ServiceContext,
    )


class BookingCreateRepository(Protocol):
    async def get_client_context(self, client_id: str) -> ClientContext | None: ...
    async def get_provider_context(self, provider_id: str) -> ProviderContext | None: ...
    async def get_service_context(self, service_id: str, provider_id: str) -> ServiceContext | None: ...
    async def get_booking_context(self, client_id: str, provider_id: str, service_id: str) -> BookingContext | None: ...
    async def is_provider_blocked(self, provider_id: str, target_date: date) -> bool: ...
    async def is_provider_scheduled(self, provider_id: str, day_of_week: int) -> bool: ...
    async def has_overlapping_booking(self, provider_id: str, start_time: datetime, end_time: datetime) -> bool: ...
    async def has_active_booking_for_client_provider(self, client_id: str, provider_id: str) -> bool: ...
    async def has_client_overlap(self, client_id: str, start_time: datetime, end_time: datetime) -> bool: ...
    async def insert_booking(
        self,
        input_data: InputSchema,
        end_time: datetime,
        target_status: str,
        provider_name: str,
        service_name: str,
        client_name: str,
    ) -> BookingCreated: ...


class PostgresBookingCreateRepository:
    def __init__(self, client: DBClient) -> None:
        self._client = client

    async def get_client_context(self, client_id: str) -> ClientContext | None:
        row = await self._client.fetchrow(
            "SELECT client_id, name FROM clients WHERE client_id = $1::uuid LIMIT 1", client_id
        )
        if not row:
            return None
        return {"id": str(row["client_id"]), "name": str(row["name"])}

    async def get_provider_context(self, provider_id: str) -> ProviderContext | None:
        row = await self._client.fetchrow(
            """
            SELECT provider_id, name FROM providers
            WHERE provider_id = $1::uuid AND is_active = true
            LIMIT 1
            FOR UPDATE
            """,
            provider_id,
        )
        if not row:
            return None
        return {"id": str(row["provider_id"]), "name": str(row["name"])}

    async def get_service_context(self, service_id: str, provider_id: str) -> ServiceContext | None:
        row = await self._client.fetchrow(
            """
            SELECT service_id, name, duration_minutes FROM services
            WHERE service_id = $1::uuid
              AND provider_id = $2::uuid
              AND is_active = true
            LIMIT 1
            """,
            service_id,
            provider_id,
        )
        if not row:
            return None
        return cast(
            "ServiceContext",
            {
                "id": str(row["service_id"]),
                "name": str(row["name"]),
                "duration": int(cast("Any", row["duration_minutes"])),
            },
        )

    async def get_booking_context(self, client_id: str, provider_id: str, service_id: str) -> BookingContext | None:
        row = await self._client.fetchrow(
            """
            SELECT
              (SELECT jsonb_build_object('id', client_id, 'name', name)
               FROM clients WHERE client_id = $1::uuid LIMIT 1) as client,
              (SELECT jsonb_build_object('id', provider_id, 'name', name)
               FROM providers WHERE provider_id = $2::uuid AND is_active = true LIMIT 1) as provider,
              (SELECT jsonb_build_object('id', service_id, 'name', name, 'duration', duration_minutes)
               FROM services WHERE service_id = $3::uuid AND provider_id = $4::uuid
                 AND is_active = true LIMIT 1) as service
            """,
            client_id,
            provider_id,
            service_id,
            provider_id,
        )
        if not row:
            return None
        client_raw = row.get("client")
        provider_raw = row.get("provider")
        service_raw = row.get("service")
        if client_raw is None or provider_raw is None or service_raw is None:
            return None
        client = cast("dict[str, Any]", client_raw)
        provider = cast("dict[str, Any]", provider_raw)
        service = cast("dict[str, Any]", service_raw)
        return {
            "client": {"id": str(client["id"]), "name": str(client["name"])},
            "provider": {"id": str(provider["id"]), "name": str(provider["name"])},
            "service": {
                "id": str(service["id"]),
                "name": str(service["name"]),
                "duration": int(service["duration"]),
            },
        }

    async def is_provider_blocked(self, provider_id: str, target_date: date) -> bool:
        row = await self._client.fetchrow(
            """
            SELECT is_blocked FROM schedule_overrides
            WHERE provider_id = $1::uuid
              AND override_date = $2::date
              AND is_blocked = true
            LIMIT 1
            """,
            provider_id,
            target_date,
        )
        return row is not None

    async def is_provider_scheduled(self, provider_id: str, day_of_week: int) -> bool:
        row = await self._client.fetchrow(
            """
            SELECT id FROM provider_schedules
            WHERE provider_id = $1::uuid
              AND day_of_week = $2
            LIMIT 1
            """,
            provider_id,
            day_of_week,
        )
        return row is not None

    async def has_client_overlap(self, client_id: str, start_time: datetime, end_time: datetime) -> bool:
        row = await self._client.fetchrow(
            """
            SELECT booking_id FROM bookings
            WHERE client_id = $1::uuid
              AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
              AND start_time < $2::timestamptz
              AND end_time > $3::timestamptz
            LIMIT 1
            """,
            client_id,
            end_time,
            start_time,
        )
        return row is not None

    async def has_active_booking_for_client_provider(self, client_id: str, provider_id: str) -> bool:
        """BE-02: check if client already has an active booking with this specific provider."""
        row = await self._client.fetchrow(
            """
            SELECT booking_id FROM bookings
            WHERE client_id = $1::uuid
              AND provider_id = $2::uuid
              AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
              AND start_time > NOW()
            LIMIT 1
            """,
            client_id,
            provider_id,
        )
        return row is not None

    async def has_overlapping_booking(self, provider_id: str, start_time: datetime, end_time: datetime) -> bool:
        row = await self._client.fetchrow(
            """
            SELECT booking_id FROM bookings
            WHERE provider_id = $1::uuid
              AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
              AND start_time < $2::timestamptz
              AND end_time > $3::timestamptz
            LIMIT 1
            """,
            provider_id,
            end_time,
            start_time,
        )
        return row is not None

    async def insert_booking(
        self,
        input_data: InputSchema,
        end_time: datetime,
        target_status: str,
        provider_name: str,
        service_name: str,
        client_name: str,
    ) -> BookingCreated:
        row = await self._client.fetchrow(
            """
            INSERT INTO bookings (
              client_id, provider_id, service_id,
              start_time, end_time, status, idempotency_key, notes,
              gcal_sync_status, notification_sent,
              reminder_24h_sent, reminder_2h_sent, reminder_30min_sent
            ) VALUES (
              $1::uuid, $2::uuid, $3::uuid,
              $4::timestamptz, $5::timestamptz,
              $6, $7, $8,
              'pending', false,
              false, false, false
            )
            ON CONFLICT (idempotency_key)
            DO UPDATE SET updated_at = NOW(), status = EXCLUDED.status
            RETURNING booking_id, status, start_time, end_time
            """,
            input_data.client_id,
            input_data.provider_id,
            input_data.service_id,
            input_data.start_time,
            end_time,
            target_status,
            input_data.idempotency_key,
            input_data.notes,
        )

        if not row:
            raise RuntimeError("INSERT returned no rows")

        booking_id_str = str(row["booking_id"])

        await self._client.execute(
            """
            INSERT INTO booking_audit (
              booking_id, from_status, to_status, changed_by, actor_id, reason, metadata
            ) VALUES (
              $1::uuid, $2, $3, $4, $5::uuid, $6, $7::jsonb
            )
            """,
            booking_id_str,
            "pending",
            target_status,
            input_data.actor,
            input_data.client_id,
            "Booking created",
            json.dumps({"channel": input_data.channel}),
        )

        return {
            "booking_id": booking_id_str,
            "status": str(row["status"]),
            "start_time": str(row["start_time"]),
            "end_time": str(row["end_time"]),
            "provider_name": provider_name,
            "service_name": service_name,
            "client_name": client_name,
        }
