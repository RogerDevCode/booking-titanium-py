from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any

from f.booking_orchestrator._get_entity import get_entity

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    from f.booking_orchestrator._orchestrator_models import OrchestratorInput, OrchestratorResult
    from f.internal._result import DBClient

from ._get_my_bookings import handle_get_my_bookings

"""
PRE-FLIGHT
Mission          : Coordinate booking rescheduling from orchestrator.
DB Tables Used   : (delegated)
Concurrency Risk : YES (delegated)
GCal Calls       : NO
Idempotency Key  : NO
RLS Tenant ID    : YES (delegated)
Zod Schemas      : NO
"""


async def handle_reschedule(
    conn: DBClient, input_data: OrchestratorInput, delegates: Mapping[str, Callable[..., Coroutine[Any, Any, Any]]]
) -> OrchestratorResult:
    booking_id = input_data.booking_id or get_entity(input_data.entities, "booking_id")
    date = input_data.date
    time = input_data.time

    if not booking_id:
        cloned_input = input_data.model_copy(
            update={"notes": "Dime el ID de la hora que quieres mover y la nueva fecha/hora."}
        )
        return await handle_get_my_bookings(conn, cloned_input, delegates)

    if not date or not time:
        res: OrchestratorResult = {
            "action": "reagendar_cita",
            "success": False,
            "data": None,
            "message": "Necesito la nueva fecha y hora para reagendar.",
            "follow_up": "¿Para cuándo te gustaría moverla?",
            "nextState": {
                "name": "selecting_time",
                "specialtyId": "",
                "doctorId": "",
                "doctorName": "",
                "targetDate": date,
                "error": None,
                "items": [],
            },
            "nextDraft": {
                "specialty_id": None,
                "specialty_name": None,
                "doctor_id": input_data.provider_id,
                "doctor_name": get_entity(input_data.entities, "provider_name"),
                "target_date": date,
                "start_time": None,
                "time_label": None,
                "client_id": input_data.client_id,
            },
        }
        return res

    # Call booking_reschedule core directly (in-process)
    args: dict[str, object] = {
        "booking_id": booking_id,
        "new_start_time": f"{date}T{time}:00",
        "actor": "client",
        "actor_id": input_data.client_id,
        "reason": get_entity(input_data.entities, "reason") or input_data.notes,
        "idempotency_key": f"orch-resch-{booking_id}-{date}-{time}",
    }

    from ...booking_reschedule.main import run_reschedule_booking
    from ...internal._wmill_adapter import log

    try:
        data = await run_reschedule_booking(conn, args)
    except Exception as e:
        log("RESCHEDULE_BOOKING_FAILED", error=str(e), traceback=traceback.format_exc(), module="booking_orchestrator")
        raise RuntimeError(f"Reschedule booking failed: {e}") from e

    res_final: OrchestratorResult = {
        "action": "reagendar_cita",
        "success": True,
        "data": data,
        "message": f"✅ Reagendada para el {date} a las {time}.",
    }
    return res_final
