import hashlib
from datetime import datetime, timedelta
from typing import Any, cast

from ..internal._result import DBClient


def derive_idempotency_key(prefix: str, parts: list[str]) -> str:
    combined = f"{prefix}:{':'.join(parts)}".encode()
    return hashlib.sha256(combined).hexdigest()[:32]


def calculate_end_time(start_time_str: str, duration_minutes: int) -> str:
    try:
        start = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        end = start + timedelta(minutes=duration_minutes)
        return end.isoformat().replace("+00:00", "Z")
    except Exception as e:
        raise RuntimeError("formato_fecha_invalido") from e


class BookingRepository:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def resolve_tenant_for_booking(self, booking_id: str) -> str:
        rows = await self.db.fetch("SELECT provider_id FROM bookings WHERE booking_id = $1::uuid LIMIT 1", booking_id)
        if not rows:
            raise RuntimeError("cita_no_encontrada")
        return str(rows[0]["provider_id"])

    async def resolve_client_id(self, user_id: str) -> str:
        # Direct lookup
        rows = await self.db.fetch("SELECT client_id FROM clients WHERE client_id = $1::uuid LIMIT 1", user_id)
        if rows:
            return str(rows[0]["client_id"])

        # Email lookup via users
        rows = await self.db.fetch("SELECT email FROM users WHERE user_id = $1::uuid LIMIT 1", user_id)
        if not rows or not rows[0].get("email"):
            raise RuntimeError("cliente_no_registrado")

        email = rows[0]["email"]
        rows = await self.db.fetch("SELECT client_id FROM clients WHERE email = $1 LIMIT 1", email)
        if not rows:
            raise RuntimeError("cliente_no_registrado")
        return str(rows[0]["client_id"])

    async def lock_provider(self, provider_id: str) -> bool:
        rows = await self.db.fetch(
            "SELECT provider_id FROM providers WHERE provider_id = $1::uuid AND is_active = true FOR UPDATE",
            provider_id,
        )
        if not rows:
            raise RuntimeError("proveedor_inactivo")
        return True

    async def get_service_duration(self, service_id: str) -> int:
        rows = await self.db.fetch(
            "SELECT duration_minutes FROM services WHERE service_id = $1::uuid LIMIT 1", service_id
        )
        if not rows:
            raise RuntimeError("servicio_no_encontrado")
        return int(cast("Any", rows[0]["duration_minutes"]))

    async def check_overlap(self, provider_id: str, start: str, end: str, ignore_id: str | None = None) -> bool:
        # Using English statuses from standardized migration
        query = """
            SELECT booking_id FROM bookings
            WHERE provider_id = $1::uuid
              AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
              AND start_time < $2::timestamptz
              AND end_time > $3::timestamptz
        """
        params = [provider_id, end, start]
        if ignore_id:
            query += " AND booking_id != $4::uuid"
            params.append(ignore_id)

        rows = await self.db.fetch(query + " LIMIT 1", *params)
        if rows:
            raise RuntimeError("horario_ocupado")
        return False

    async def insert_booking(self, data: dict[str, Any]) -> dict[str, Any]:
        rows = await self.db.fetch(
            """
            INSERT INTO bookings (
              provider_id, client_id, service_id, start_time, end_time,
              status, idempotency_key, rescheduled_from, gcal_sync_status
            ) VALUES (
              $1::uuid, $2::uuid, $3::uuid,
              $4::timestamptz, $5::timestamptz,
              'pending', $6, $7::uuid, 'pending'
            )
            ON CONFLICT (idempotency_key) DO UPDATE SET updated_at = NOW()
            RETURNING booking_id, status
            """,
            data["tenant_id"],
            data["client_id"],
            data["service_id"],
            data["start_time"],
            data["end_time"],
            data["idempotency_key"],
            data.get("rescheduled_from"),
        )
        if not rows:
            raise RuntimeError("error_insercion_booking")
        return {"booking_id": str(rows[0]["booking_id"]), "status": str(rows[0]["status"])}

    async def get_booking(self, booking_id: str) -> dict[str, Any]:
        rows = await self.db.fetch(
            "SELECT status, client_id, service_id FROM bookings WHERE booking_id = $1::uuid LIMIT 1", booking_id
        )
        if not rows:
            raise RuntimeError("cita_no_encontrada")
        return {
            "status": str(rows[0]["status"]),
            "client_id": str(rows[0]["client_id"]),
            "service_id": str(rows[0]["service_id"]),
        }

    async def update_status(self, booking_id: str, status: str, reason: str | None = None) -> bool:
        rows = await self.db.fetch(
            "UPDATE bookings SET status = $1, cancellation_reason = $2, updated_at = NOW() WHERE booking_id = $3::uuid RETURNING booking_id",  # noqa: E501
            status,
            reason,
            booking_id,
        )
        if not rows:
            raise RuntimeError("error_actualizacion_booking")
        return True
