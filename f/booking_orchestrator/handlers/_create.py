from __future__ import annotations

import traceback
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from f.booking_orchestrator._get_entity import get_entity
from f.internal._booking_utils import get_active_booking_for_provider

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    from f.booking_orchestrator._orchestrator_models import OrchestratorInput, OrchestratorResult
    from f.internal._result import DBClient

"""
PRE-FLIGHT
Mission          : Coordinate booking creation from orchestrator.
DB Tables Used   : (delegated to booking_create)
Concurrency Risk : YES (delegated)
GCal Calls       : NO
Idempotency Key  : YES
RLS Tenant ID    : YES (delegated)
Zod Schemas      : NO
"""


async def handle_create_booking(
    conn: DBClient, input_data: OrchestratorInput, delegates: Mapping[str, Callable[..., Coroutine[Any, Any, Any]]]
) -> OrchestratorResult:
    client_id = input_data.client_id
    provider_id = input_data.provider_id
    service_id = input_data.service_id
    date = input_data.date
    time = input_data.time

    # 1. SMART HANDOFF: Detect missing required fields for a direct booking
    if not all([client_id, provider_id, service_id, date, time]):
        query = """
        SELECT
            s.specialty_id as id,
            s.name,
            (SELECT COUNT(*) FROM providers p
             WHERE p.specialty_id = s.specialty_id AND p.is_active = true) as provider_count
        FROM specialties s
        WHERE s.is_active = true
        ORDER BY s.sort_order ASC, s.name ASC
        """
        rows = await conn.fetch(query)

        inline_buttons: list[list[dict[str, str]]] = []
        current_row: list[dict[str, str]] = []
        msg_parts: list[str] = ["🏥 *Selecciona la especialidad que necesitas:*\n"]

        for r in rows:
            name = str(r["name"])
            sp_id = str(r["id"])
            count = int(cast("int", r["provider_count"]))

            if count > 0:
                current_row.append({"text": name, "callback_data": f"spec:{sp_id}"})
                if len(current_row) == 2:
                    inline_buttons.append(current_row)
                    current_row = []
            else:
                msg_parts.append(f"• {name} *(temp. no disp.)*")

        if current_row:
            inline_buttons.append(current_row)

        inline_buttons.append([{"text": "❌ Cancelar", "callback_data": "cancel"}])

        message = "\n".join(msg_parts) if len(msg_parts) > 1 else msg_parts[0]

        res: OrchestratorResult = {
            "action": "crear_cita",
            "success": False,
            "data": None,
            "message": message,
            "inline_buttons": inline_buttons,
            "nextState": {"name": "selecting_specialty", "error": None, "items": []},
            "nextDraft": {
                "specialty_id": None,
                "specialty_name": get_entity(input_data.entities, "specialty_name"),
                "doctor_id": provider_id,
                "doctor_name": get_entity(input_data.entities, "provider_name"),
                "target_date": date,
                "start_time": f"{date}T{time}:00" if date and time else None,
                "time_label": time,
                "client_id": client_id,
            },
        }
        return res

    # 1.5. VALIDATE IDS IN DB (FAIL-FAST)
    assert client_id is not None
    assert provider_id is not None
    assert service_id is not None

    provider_check = await conn.fetchrow(
        "SELECT 1 FROM providers WHERE provider_id = $1::uuid AND is_active = true", provider_id
    )
    if not provider_check:
        return {
            "action": "crear_cita",
            "success": False,
            "message": (
                "❌ El especialista seleccionado no está disponible o ya no existe. "
                "Por favor, intenta agendar nuevamente."
            ),
        }

    service_check = await conn.fetchrow(
        "SELECT 1 FROM services WHERE service_id = $1::uuid AND is_active = true", service_id
    )
    if not service_check:
        return {
            "action": "crear_cita",
            "success": False,
            "message": "❌ El servicio seleccionado no está disponible. Por favor, intenta agendar nuevamente.",
        }

    # 2. CHECK FOR DUPLICATE ACTIVE BOOKING (Rule BE-02)
    # client_id and provider_id are guaranteed non-None by the all() guard above
    active_booking = await get_active_booking_for_provider(conn, client_id, provider_id)
    if active_booking:
        st = active_booking["start_time"]
        fmt_time = st.strftime("%d/%m %H:%M") if isinstance(st, datetime) else str(st)

        message = (
            f"\u2139\ufe0f *Ya tienes una cita activa*\n\n"
            f"Tienes una cita con *{active_booking['provider_name']}* para el *{fmt_time}*.\n\n"
            f"\u00bfDeseas reagendar esa cita para el nuevo horario "
            f"(*{date}* a las *{time}*) o prefieres volver al men\u00fa?"
        )

        # Action code 'ars' for Auto-Reschedule
        # We use a compact format to fit in Telegram's 64 byte limit
        # ars:BOOKING_ID:YYYY-MM-DD:HH:MM
        ars_callback = f"ars:{active_booking['booking_id']}:{date}:{time}"

        res_dup: OrchestratorResult = {
            "action": "crear_cita",
            "success": False,
            "message": message,
            "inline_buttons": [
                [{"text": "\ud83d\udd04 S\u00ed, reagendar cita", "callback_data": ars_callback}],
                [{"text": "\u00ab Volver al men\u00fa", "callback_data": "cancel"}],
            ],
        }
        return res_dup

    # 3. CALL CORE MODULE DIRECTLY (in-process, no cross-script dispatch)
    args: dict[str, object] = {
        "client_id": client_id,
        "provider_id": provider_id,
        "service_id": service_id,
        "start_time": f"{date}T{time}:00",
        "idempotency_key": f"orch-{client_id}-{provider_id}-{date}-{time}",
        "notes": input_data.notes,
        "actor": "client",
        "channel": input_data.channel,
    }

    from ...booking_create.main import run_create_booking
    from ...internal._wmill_adapter import log

    try:
        data = await run_create_booking(conn, args)
    except Exception as e:
        log("CREATE_BOOKING_FAILED", error=str(e), traceback=traceback.format_exc(), module="booking_orchestrator")
        raise RuntimeError(f"Create booking failed: {e}") from e

    res_final: OrchestratorResult = {
        "action": "crear_cita",
        "success": True,
        "data": data,
        "message": f"✅ Hora agendada para el {date} a las {time}.",
        "follow_up": None,
    }
    return res_final
