from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeVar, cast

from f.booking_orchestrator._get_entity import get_entity
from f.internal._config import DEFAULT_TIMEZONE
from f.internal._date_resolver import resolve_date, resolve_time
from f.internal._state_machine import BookingStatus, validate_transition
from f.services.booking._booking_errors import BookingSlotUnavailableError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from f.internal._result import DBClient

_T = TypeVar("_T")

_STATUS_TO_EVENT: Final[dict[str, str]] = {
    "confirmed": "CONFIRM",
    "cancelled": "CANCEL",
    "rescheduled": "RESCHEDULE",
    "in_service": "START",
    "completed": "COMPLETE",
    "no_show": "MARK_NO_SHOW",
}


class BookingRepo(Protocol):
    async def resolve_context(self, intent: dict[str, Any]) -> dict[str, Any]: ...
    async def exists(self, idempotency_key: str) -> bool: ...
    async def get_by_key(self, idempotency_key: str) -> dict[str, Any]: ...
    async def is_available(self, data: dict[str, Any]) -> bool: ...
    async def insert(self, data: dict[str, Any]) -> dict[str, Any]: ...
    async def get_specialties_for_booking(self) -> list[dict[str, Any]]: ...
    async def get_active_booking_for_client(self, client_id: str, provider_id: str) -> dict[str, Any] | None: ...
    async def get_booking(self, booking_id: str) -> dict[str, Any] | None: ...
    async def update_status(
        self,
        booking_id: str,
        status: str,
        actor_id: str | None,
        reason: str | None,
        actor_type: str | None = None,
    ) -> dict[str, Any]: ...
    async def reschedule(self, old_booking_id: str, new_data: dict[str, Any]) -> dict[str, Any]: ...


class PgBookingRepo:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def _run_in_transaction(self, operation: Callable[[], Awaitable[_T]]) -> _T:
        """Transaction management is delegated to the caller context (e.g., with_tenant_context)."""
        return await operation()

    async def resolve_context(self, intent: dict[str, Any]) -> dict[str, Any]:
        entities = intent.get("entities", {})
        telegram_chat_id = intent.get("telegram_chat_id") or intent.get("chat_id")

        client_id = get_entity(entities, "client_id")
        provider_id = get_entity(entities, "provider_id")
        service_id = get_entity(entities, "service_id")
        date_str = get_entity(entities, "date")
        time_str = get_entity(entities, "time")

        specialty_id = get_entity(entities, "specialty_id")
        provider_name = get_entity(entities, "provider_name")
        specialty_name = get_entity(entities, "specialty_name")

        if not provider_id and provider_name:
            rows = await self.db.fetch(
                "SELECT provider_id FROM providers WHERE name ILIKE $1 LIMIT 1",
                f"%{provider_name}%",
            )
            if rows:
                provider_id = str(rows[0]["provider_id"])
        elif not provider_id and specialty_id:
            rows = await self.db.fetch(
                ("SELECT provider_id FROM providers WHERE specialty_id = $1::uuid AND is_active=true LIMIT 1"),
                specialty_id,
            )
            if rows:
                provider_id = str(rows[0]["provider_id"])

        if not service_id and specialty_name:
            rows = await self.db.fetch(
                (
                    "SELECT s.service_id FROM services s "
                    "JOIN specialties sp ON s.specialty_id = sp.specialty_id "
                    "WHERE sp.name ILIKE $1 LIMIT 1"
                ),
                f"%{specialty_name}%",
            )
            if rows:
                service_id = str(rows[0]["service_id"])

        if not service_id and provider_id:
            rows = await self.db.fetch(
                ("SELECT service_id FROM services WHERE provider_id = $1::uuid AND is_active=true LIMIT 1"),
                provider_id,
            )
            if rows:
                service_id = str(rows[0]["service_id"])

        timezone = DEFAULT_TIMEZONE
        if not client_id and telegram_chat_id:
            rows = await self.db.fetch(
                (
                    "SELECT c.client_id, t.name as timezone "
                    "FROM clients c "
                    "LEFT JOIN timezones t ON c.timezone_id = t.id "
                    "WHERE c.telegram_chat_id = $1 LIMIT 1"
                ),
                str(telegram_chat_id),
            )
            if rows:
                client_id = str(rows[0]["client_id"])
                if rows[0]["timezone"]:
                    timezone = str(rows[0]["timezone"])
            else:
                name = intent.get("telegram_name") or "Usuario"
                rows = await self.db.fetch(
                    (
                        "INSERT INTO clients (name, telegram_chat_id, timezone_id) "
                        "VALUES ($1, $2, 2) RETURNING client_id"
                    ),
                    name,
                    str(telegram_chat_id),
                )
                if rows:
                    client_id = str(rows[0]["client_id"])

        if date_str:
            abs_date = resolve_date(date_str, {"timezone": timezone})
            if abs_date:
                date_str = abs_date
        if time_str:
            abs_time = resolve_time(time_str)
            if abs_time:
                time_str = abs_time

        return {
            "client_id": client_id,
            "provider_id": provider_id,
            "service_id": service_id,
            "date": date_str,
            "time": time_str,
            "specialty_name": specialty_name,
            "provider_name": provider_name,
        }

    async def get_specialties_for_booking(self) -> list[dict[str, Any]]:
        rows = await self.db.fetch(
            "SELECT s.specialty_id as id, s.name, "
            "(SELECT COUNT(*) FROM providers p "
            "WHERE p.specialty_id = s.specialty_id AND p.is_active = true) "
            "as provider_count FROM specialties s "
            "WHERE s.is_active = true "
            "ORDER BY s.sort_order ASC, s.name ASC"
        )
        return [
            {
                "id": str(r["id"]),
                "name": str(r["name"]),
                "provider_count": int(str(r["provider_count"])),
            }
            for r in rows
        ]

    async def get_active_booking_for_client(self, client_id: str, provider_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchrow(
            """
            SELECT b.booking_id, b.start_time, p.name as provider_name 
            FROM bookings b JOIN providers p ON b.provider_id = p.provider_id 
            WHERE b.client_id = $1::uuid AND b.provider_id = $2::uuid 
            AND b.status NOT IN ('cancelled', 'no_show', 'rescheduled') 
            AND b.start_time > NOW() LIMIT 1
            """,
            client_id,
            provider_id,
        )
        return dict(row) if row else None

    async def exists(self, idempotency_key: str) -> bool:
        row = await self.db.fetchrow(
            "SELECT 1 FROM bookings WHERE idempotency_key = $1"
            " AND status NOT IN ('cancelled', 'no_show', 'rescheduled') LIMIT 1",
            idempotency_key,
        )
        return row is not None

    async def get_by_key(self, idempotency_key: str) -> dict[str, Any]:
        row = await self.db.fetchrow(
            ("SELECT booking_id, status FROM bookings WHERE idempotency_key = $1 LIMIT 1"),
            idempotency_key,
        )
        return dict(row) if row else {}

    async def get_booking(self, booking_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchrow(
            "SELECT * FROM bookings WHERE booking_id = $1::uuid LIMIT 1",
            booking_id,
        )
        return dict(row) if row else None

    async def is_available(self, data: dict[str, Any]) -> bool:
        row = await self.db.fetchrow(
            """
            SELECT 1 FROM bookings 
            WHERE provider_id = $1::uuid 
            AND status NOT IN ('cancelled', 'no_show', 'rescheduled') 
            AND start_time < $3::timestamptz AND end_time > $2::timestamptz 
            LIMIT 1
            """,
            data["provider_id"],
            data["start_time"],
            data["end_time"],
        )
        return row is None

    async def _insert_raw(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            row = await self.db.fetchrow(
                """
                INSERT INTO bookings (
                  client_id, provider_id, service_id, start_time, end_time,
                  status, idempotency_key, notes, gcal_sync_status
                ) VALUES (
                  $1::uuid, $2::uuid, $3::uuid, $4::timestamptz, $5::timestamptz,
                  'confirmed', $6, $7, 'pending'
                )
                RETURNING booking_id, status, start_time, end_time
                """,
                data["client_id"],
                data["provider_id"],
                data["service_id"],
                data["start_time"],
                data["end_time"],
                data["idempotency_key"],
                data.get("notes"),
            )
        except Exception as exc:
            if "booking_no_overlap_gist" in str(exc):
                raise BookingSlotUnavailableError(
                    "Slot unavailable — concurrent booking detected by DB constraint."
                ) from exc
            raise
        if row:
            booking_id_str = str(row["booking_id"])
            await self.db.execute(
                (
                    "INSERT INTO booking_audit "
                    "(booking_id, from_status, to_status, actor_id, reason, metadata) "
                    "VALUES ($1::uuid, 'pending', 'confirmed', $2::uuid, "
                    "'Booking created', $3::jsonb)"
                ),
                booking_id_str,
                data["client_id"],
                json.dumps({"channel": "telegram"}),
            )
            await self.db.execute(
                """
                INSERT INTO booking_events
                (booking_id, event_type, previous_status, new_status,
                 actor_type, actor_id, idempotency_key, payload)
                VALUES ($1::uuid, 'CREATE', NULL, 'confirmed',
                        'system', $2::uuid, $3, $4::jsonb)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                booking_id_str,
                data["client_id"],
                f"create-{booking_id_str}",
                json.dumps({"channel": "telegram", "idempotency_key": data["idempotency_key"]}),
            )
            return {"booking_id": booking_id_str, "status": row["status"]}
        return {}

    async def insert(self, data: dict[str, Any]) -> dict[str, Any]:
        return await self._run_in_transaction(lambda: self._insert_raw(data))

    async def _update_status_raw(
        self,
        booking_id: str,
        status: str,
        actor_id: str | None,
        reason: str | None,
        actor_type: str | None = None,
    ) -> dict[str, Any]:
        current = await self.get_booking(booking_id)
        if current:
            err, _ = validate_transition(
                cast("BookingStatus", current["status"]),
                cast("BookingStatus", status),
            )
            if err is not None:
                raise RuntimeError(f"Invalid transition {current['status']!r} → {status!r}: {err}")
        effective_actor_type = actor_type or ("system" if not actor_id else None)
        row = await self.db.fetchrow(
            """
            UPDATE bookings
            SET status            = $1,
                updated_at        = NOW(),
                cancellation_reason = $2,
                cancelled_by      = CASE WHEN $1 = 'cancelled' THEN $4 ELSE cancelled_by END,
                started_at        = CASE WHEN $1 = 'in_service' THEN NOW() ELSE started_at END,
                completed_at      = CASE WHEN $1 = 'completed'  THEN NOW() ELSE completed_at END,
                gcal_sync_status  = 'pending'
            WHERE booking_id = $3::uuid
            RETURNING booking_id, status, client_id, start_time
            """,
            status,
            reason,
            booking_id,
            effective_actor_type,
        )
        if row:
            await self.db.execute(
                (
                    "INSERT INTO booking_audit "
                    "(booking_id, to_status, actor_id, reason) "
                    "VALUES ($1::uuid, $2, $3::uuid, $4)"
                ),
                booking_id,
                status,
                actor_id,
                reason,
            )
            prev_status = current["status"] if current else None
            event_type = _STATUS_TO_EVENT.get(status, "CANCEL")
            await self.db.execute(
                """
                INSERT INTO booking_events
                (booking_id, event_type, previous_status, new_status,
                 actor_type, actor_id, idempotency_key, payload)
                VALUES ($1::uuid, $2, $3, $4, $5, $6::uuid, $7, $8::jsonb)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                booking_id,
                event_type,
                prev_status,
                status,
                effective_actor_type,
                actor_id,
                f"{event_type.lower()}-{booking_id}",
                json.dumps({"reason": reason}),
            )
            return dict(row)
        return {}

    async def update_status(
        self,
        booking_id: str,
        status: str,
        actor_id: str | None,
        reason: str | None,
        actor_type: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_in_transaction(
            lambda: self._update_status_raw(booking_id, status, actor_id, reason, actor_type)
        )

    async def _reschedule_raw(self, old_booking_id: str, new_data: dict[str, Any]) -> dict[str, Any]:
        # Atomic reschedule: Create new, update old
        try:
            new_row = await self.db.fetchrow(
                """
                INSERT INTO bookings (
                  client_id, provider_id, service_id, start_time, end_time,
                  status, idempotency_key, rescheduled_from, gcal_sync_status
                ) VALUES (
                  $1::uuid, $2::uuid, $3::uuid, $4::timestamptz, $5::timestamptz,
                  'confirmed', $6, $7::uuid, 'pending'
                )
                RETURNING booking_id, status, start_time, end_time
                """,
                new_data["client_id"],
                new_data["provider_id"],
                new_data["service_id"],
                new_data["start_time"],
                new_data["end_time"],
                new_data["idempotency_key"],
                old_booking_id,
            )
        except Exception as exc:
            if "booking_no_overlap_gist" in str(exc):
                raise BookingSlotUnavailableError(
                    "New slot unavailable — concurrent booking detected by DB constraint."
                ) from exc
            raise
        if not new_row:
            raise RuntimeError("Failed to insert new booking row")

        new_booking_id = str(new_row["booking_id"])

        await self.db.execute(
            """
            INSERT INTO booking_events
            (booking_id, event_type, previous_status, new_status,
             actor_type, actor_id, idempotency_key, payload)
            VALUES ($1::uuid, 'CREATE', NULL, 'confirmed',
                    'system', $2::uuid, $3, $4::jsonb)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            new_booking_id,
            new_data.get("client_id"),
            f"create-{new_booking_id}",
            json.dumps({"rescheduled_from": old_booking_id}),
        )

        # Link old booking → new booking before marking it rescheduled
        await self.db.execute(
            "UPDATE bookings SET rescheduled_to = $1::uuid WHERE booking_id = $2::uuid",
            new_booking_id,
            old_booking_id,
        )

        await self._update_status_raw(
            old_booking_id,
            "rescheduled",
            new_data.get("actor_id"),
            "Rescheduled to new time",
            new_data.get("actor_type"),
        )

        return {"booking_id": new_booking_id, "status": new_row["status"]}

    async def reschedule(self, old_booking_id: str, new_data: dict[str, Any]) -> dict[str, Any]:
        return await self._run_in_transaction(lambda: self._reschedule_raw(old_booking_id, new_data))
