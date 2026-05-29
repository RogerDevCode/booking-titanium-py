from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from f.availability_check._availability_logic import get_provider, get_provider_service_id
from f.availability_check._availability_models import InputSchema as AvailabilityInputSchema
from f.internal._db_client import create_db_client
from f.internal.scheduling_engine import get_availability
from f.services.booking._booking_errors import (
    BookingMissingParamsError,
    BookingNoServiceError,
    BookingNotFoundError,
)
from f.services.booking._booking_models import (
    BookingCancelRequest,
    BookingCreateRequest,
    BookingRescheduleRequest,
)
from f.services.booking.core import cancel_booking, create_booking, reschedule_booking
from f.services.booking.repo import PgBookingRepo

if TYPE_CHECKING:
    from f.internal._result import DBClient


async def _handle_crear_cita(intent: dict[str, Any], conn: DBClient, repo: PgBookingRepo) -> dict[str, Any]:
    ctx = await repo.resolve_context(intent)

    client_id = ctx.get("client_id")
    provider_id = ctx.get("provider_id")
    service_id = ctx.get("service_id")
    date_str = ctx.get("date")
    time_str = ctx.get("time")

    if not all([client_id, provider_id, service_id, date_str, time_str]):
        specs = await repo.get_specialties_for_booking()
        inline_buttons: list[list[dict[str, str]]] = []
        current_row: list[dict[str, str]] = []
        msg_parts = ["🏥 *Selecciona la especialidad que necesitas:*\n"]
        for s in specs:
            if s["provider_count"] > 0:
                current_row.append({"text": s["name"], "callback_data": f"spec:{s['id']}"})
                if len(current_row) == 2:
                    inline_buttons.append(current_row)
                    current_row = []
            else:
                msg_parts.append(f"• {s['name']} *(temp. no disp.)*")
        if current_row:
            inline_buttons.append(current_row)
        inline_buttons.append([{"text": "❌ Cancelar", "callback_data": "cancel"}])
        return {
            "action": "crear_cita",
            "success": False,
            "message": "\n".join(msg_parts) if len(msg_parts) > 1 else msg_parts[0],
            "inline_buttons": inline_buttons,
        }

    active = await repo.get_active_booking_for_client(str(client_id), str(provider_id))
    if active:
        st = active["start_time"]
        fmt_time = st.strftime("%d/%m %H:%M") if hasattr(st, "strftime") else str(st)
        msg = (
            f"i*Ya tienes una cita activa*\n\n"
            f"Tienes una cita con *{active['provider_name']}* para el *{fmt_time}*.\n\n"
            f"¿Deseas reagendar esa cita para el nuevo horario "
            f"(*{date_str}* a las *{time_str}*) o prefieres volver al menú?"
        )
        ars_callback = f"ars:{active['booking_id']}:{date_str}:{time_str}"
        return {
            "action": "crear_cita",
            "success": False,
            "message": msg,
            "inline_buttons": [
                [{"text": "🔄 Sí, reagendar cita", "callback_data": ars_callback}],
                [{"text": "« Volver al menú", "callback_data": "cancel"}],
            ],
        }

    start_time_str = f"{date_str}T{time_str}:00"
    try:
        start_dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BookingMissingParamsError(f"invalid_datetime:{date_str}T{time_str}") from exc

    duration_row = await repo.db.fetchrow(
        "SELECT duration_minutes FROM services WHERE service_id = $1::uuid LIMIT 1",
        str(service_id),
    )
    duration_minutes = (
        int(str(duration_row["duration_minutes"])) if duration_row and duration_row.get("duration_minutes") else 30
    )
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    req = BookingCreateRequest(
        client_id=str(client_id),
        provider_id=str(provider_id),
        service_id=str(service_id),
        start_time=start_dt,
        end_time=end_dt,
        idempotency_key=f"orch-{client_id}-{provider_id}-{date_str}-{time_str}",
        notes=intent.get("notes"),
    )
    res = await create_booking(req, repo)
    return {
        "action": "crear_cita",
        "success": True,
        "message": f"✅ Hora agendada para el {date_str} a las {time_str}.",
        "data": res.model_dump(),
    }


async def _resolve_client_id(intent: dict[str, Any], conn: DBClient) -> str | None:
    actor_id: str | None = intent.get("actor_id")
    if actor_id:
        return actor_id
    chat_id = intent.get("chat_id") or intent.get("telegram_chat_id")
    if not chat_id:
        return None
    rows = await conn.fetch("SELECT client_id FROM clients WHERE telegram_chat_id = $1 LIMIT 1", str(chat_id))
    return str(rows[0]["client_id"]) if rows else None


async def _handle_cancelar_cita(intent: dict[str, Any], conn: DBClient, repo: PgBookingRepo) -> dict[str, Any]:
    entities: dict[str, Any] = intent.get("entities") or {}
    booking_id = intent.get("booking_id") or entities.get("booking_id")
    if not booking_id:
        raise BookingMissingParamsError("booking_id required")

    client_id = await _resolve_client_id(intent, conn)
    actor_raw = "client" if client_id else intent.get("actor", "system")
    actor = actor_raw if actor_raw in ("client", "provider", "system", "admin") else "system"
    actor_id_raw = client_id or intent.get("actor_id")
    req_cancel = BookingCancelRequest(
        booking_id=booking_id,
        actor=actor,  # type: ignore[arg-type]
        actor_id=str(actor_id_raw) if actor_id_raw is not None else None,
        reason=str(intent.get("reason") or "Cancelled by user"),
    )
    res = await cancel_booking(req_cancel, repo)
    return {
        "action": "cancelar_cita",
        "success": True,
        "message": "✅ Tu hora ha sido cancelada.",
        "data": res.model_dump(),
    }


async def _handle_reagendar_cita(intent: dict[str, Any], conn: DBClient, repo: PgBookingRepo) -> dict[str, Any]:
    entities: dict[str, Any] = intent.get("entities") or {}
    booking_id = intent.get("booking_id") or entities.get("booking_id")
    date_str = intent.get("date") or entities.get("date")
    time_str = intent.get("time") or entities.get("time")

    if not booking_id or not (date_str and time_str):
        raise BookingMissingParamsError("booking_id, date, time required")

    new_start_time_str = f"{date_str}T{time_str}:00"
    try:
        new_start_dt = datetime.fromisoformat(new_start_time_str.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BookingMissingParamsError(f"invalid_datetime:{date_str}T{time_str}") from exc

    duration_row = await repo.db.fetchrow(
        "SELECT s.duration_minutes FROM services s "
        "JOIN bookings b ON b.service_id = s.service_id "
        "WHERE b.booking_id = $1::uuid LIMIT 1",
        booking_id,
    )
    duration_minutes = (
        int(str(duration_row["duration_minutes"])) if duration_row and duration_row.get("duration_minutes") else 30
    )
    new_end_dt = new_start_dt + timedelta(minutes=duration_minutes)

    client_id = await _resolve_client_id(intent, conn)
    actor_raw = "client" if client_id else intent.get("actor", "system")
    actor = actor_raw if actor_raw in ("client", "provider", "system", "admin") else "system"
    actor_id_raw = client_id or intent.get("actor_id")
    req_reschedule = BookingRescheduleRequest(
        booking_id=booking_id,
        new_start_time=new_start_dt,
        new_end_time=new_end_dt,
        actor=actor,  # type: ignore[arg-type]
        actor_id=str(actor_id_raw) if actor_id_raw is not None else None,
    )
    res = await reschedule_booking(req_reschedule, repo)
    return {
        "action": "reagendar_cita",
        "success": True,
        "message": f"✅ Hora reagendada para el {date_str} a las {time_str}.",
        "data": res.model_dump(),
    }


async def _handle_ver_disponibilidad(intent: dict[str, Any], conn: DBClient, repo: PgBookingRepo) -> dict[str, Any]:
    entities: dict[str, Any] = intent.get("entities") or {}
    provider_id = intent.get("provider_id") or entities.get("provider_id")
    date_str = intent.get("date") or entities.get("date")

    if not provider_id or not date_str:
        raise BookingMissingParamsError("provider_id, date required")

    validated = AvailabilityInputSchema.model_validate(
        {
            "provider_id": provider_id,
            "date": date_str,
            "tenant_id": intent.get("tenant_id", "default"),
        }
    )
    provider = await get_provider(conn, validated.provider_id)
    if not provider:
        raise BookingNotFoundError(f"provider_not_found:{validated.provider_id}")

    service_id = validated.service_id or await get_provider_service_id(conn, validated.provider_id)
    if not service_id:
        raise BookingNoServiceError(f"no_service_for_provider:{validated.provider_id}")

    result = await get_availability(
        conn,
        {"provider_id": validated.provider_id, "date": validated.date, "service_id": service_id},
    )
    if not result:
        raise RuntimeError(f"availability_check_failed:{validated.provider_id}:{validated.date}")
    return {"action": "ver_disponibilidad", "success": True, "data": result}


async def _handle_mis_citas(intent: dict[str, Any], conn: DBClient, repo: PgBookingRepo) -> dict[str, Any]:
    chat_id = intent.get("chat_id") or intent.get("telegram_chat_id")
    rows = await conn.fetch(
        """
        SELECT b.booking_id, b.start_time, p.name AS provider_name,
               sp.name AS specialty, s.name AS service_name
        FROM bookings b
        JOIN providers p ON b.provider_id = p.provider_id
        JOIN specialties sp ON p.specialty_id = sp.specialty_id
        JOIN services s ON b.service_id = s.service_id
        JOIN clients c ON b.client_id = c.client_id
        WHERE c.telegram_chat_id = $1
          AND b.status NOT IN ('cancelled', 'no_show', 'rescheduled', 'completed')
          AND b.start_time > NOW()
        ORDER BY b.start_time ASC
        LIMIT 5
        """,
        str(chat_id),
    )
    if not rows:
        return {"action": "mis_citas", "success": True, "message": "No tienes citas activas actualmente."}

    lines = ["📋 *Tus próximas citas:*\n"]
    for r in rows:
        short_id = str(r["booking_id"]).replace("-", "").upper()[:9]
        ref = f"{short_id[:2]}-{short_id[2:5]}-{short_id[5:]}"
        st = r["start_time"]
        fmt_time = cast("datetime", st).strftime("%d/%m/%Y %H:%M") if hasattr(st, "strftime") else str(st)
        lines.append(f"• *{r['provider_name']}* ({r['specialty']})\n  📅 {fmt_time}\n  🔖 Ref: `{ref}`")

    return {"action": "mis_citas", "success": True, "message": "\n\n".join(lines)}


async def _handle_consultar_cita(intent: dict[str, Any], conn: DBClient, repo: PgBookingRepo) -> dict[str, Any]:
    entities: dict[str, Any] = intent.get("entities") or {}
    booking_id = intent.get("booking_id") or entities.get("booking_id")
    chat_id = intent.get("chat_id") or intent.get("telegram_chat_id")

    if booking_id:
        row = await conn.fetchrow(
            """
            SELECT b.booking_id, b.start_time, b.status,
                   p.name AS provider_name, sp.name AS specialty, s.name AS service_name
            FROM bookings b
            JOIN providers p ON b.provider_id = p.provider_id
            JOIN specialties sp ON p.specialty_id = sp.specialty_id
            JOIN services s ON b.service_id = s.service_id
            WHERE b.booking_id = $1::uuid
            LIMIT 1
            """,
            booking_id,
        )
    elif chat_id:
        row = await conn.fetchrow(
            """
            SELECT b.booking_id, b.start_time, b.status,
                   p.name AS provider_name, sp.name AS specialty, s.name AS service_name
            FROM bookings b
            JOIN providers p ON b.provider_id = p.provider_id
            JOIN specialties sp ON p.specialty_id = sp.specialty_id
            JOIN services s ON b.service_id = s.service_id
            JOIN clients c ON b.client_id = c.client_id
            WHERE c.telegram_chat_id = $1
              AND b.status NOT IN ('cancelled', 'no_show', 'rescheduled', 'completed')
              AND b.start_time > NOW()
            ORDER BY b.start_time ASC
            LIMIT 1
            """,
            str(chat_id),
        )
    else:
        return {
            "action": "consultar_cita",
            "success": False,
            "message": "❌ Necesito el ID o referencia de tu hora para consultarla.",
        }

    if not row:
        return {
            "action": "consultar_cita",
            "success": False,
            "message": "No encontré una hora activa. ¿Quieres agendar una nueva?",
        }

    short_id = str(row["booking_id"]).replace("-", "").upper()[:9]
    ref = f"{short_id[:2]}-{short_id[2:5]}-{short_id[5:]}"
    st = row["start_time"]
    fmt_time = cast("datetime", st).strftime("%d/%m/%Y %H:%M") if hasattr(st, "strftime") else str(st)
    status_emoji = {"confirmed": "✅", "pending": "⏳", "cancelled": "❌"}.get(str(row["status"]), "i")
    msg = (
        f"\U0001f4cb *Detalle de tu hora*\n\n"
        f"*Doctor:* {row['provider_name']}\n"
        f"*Especialidad:* {row['specialty']}\n"
        f"*Servicio:* {row['service_name']}\n"
        f"*Fecha:* {fmt_time}\n"
        f"*Estado:* {status_emoji} {row['status']}\n"
        f"*Referencia:* `{ref}`"
    )
    return {"action": "consultar_cita", "success": True, "message": msg, "data": dict(row)}


async def route_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """
    Pure service-layer router. Single DB connection for the entire request.
    Routing only — no IO setup outside this function.
    """
    intent_type = str(intent.get("type", "desconocido"))

    if intent_type not in (
        "crear_cita",
        "cancelar_cita",
        "reagendar_cita",
        "reagendar",
        "ver_disponibilidad",
        "mis_citas",
        "consultar_cita",
    ):
        raise ValueError(f"unknown_intent:{intent_type}")

    conn = await create_db_client()
    try:
        repo = PgBookingRepo(conn)
        if intent_type == "crear_cita":
            return await _handle_crear_cita(intent, conn, repo)
        elif intent_type == "cancelar_cita":
            return await _handle_cancelar_cita(intent, conn, repo)
        elif intent_type in ("reagendar_cita", "reagendar"):
            return await _handle_reagendar_cita(intent, conn, repo)
        elif intent_type == "ver_disponibilidad":
            return await _handle_ver_disponibilidad(intent, conn, repo)
        elif intent_type == "mis_citas":
            return await _handle_mis_citas(intent, conn, repo)
        else:  # consultar_cita
            return await _handle_consultar_cita(intent, conn, repo)
    finally:
        await conn.close()
