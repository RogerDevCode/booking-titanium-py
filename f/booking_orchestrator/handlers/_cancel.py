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
Mission          : Coordinate booking cancellation from orchestrator.
DB Tables Used   : (delegated)
Concurrency Risk : YES (delegated)
GCal Calls       : NO
Idempotency Key  : NO
RLS Tenant ID    : YES (delegated)
Zod Schemas      : NO
"""


async def handle_cancel_booking(
    conn: DBClient, input_data: OrchestratorInput, delegates: Mapping[str, Callable[..., Coroutine[Any, Any, Any]]]
) -> OrchestratorResult:
    booking_id = input_data.booking_id or get_entity(input_data.entities, "booking_id")

    if not booking_id:
        # If no ID, show current bookings so user can pick
        cloned_input = input_data.model_copy(update={"notes": "Por favor, dime el ID de la hora que deseas cancelar."})
        return await handle_get_my_bookings(conn, cloned_input, delegates)

    # Call booking_cancel core directly (in-process)
    args: dict[str, object] = {
        "booking_id": booking_id,
        "actor": "client",
        "actor_id": input_data.client_id,
        "reason": get_entity(input_data.entities, "reason") or input_data.notes,
        "idempotency_key": f"orch-cancel-{booking_id}",
    }

    from ...booking_cancel.main import run_cancel_booking
    from ...internal._wmill_adapter import log

    try:
        data = await run_cancel_booking(conn, args)
    except Exception as e:
        log("CANCEL_BOOKING_FAILED", error=str(e), traceback=traceback.format_exc(), module="booking_orchestrator")
        raise RuntimeError(f"Cancel booking failed: {e}") from e

    res: OrchestratorResult = {
        "action": "cancelar_cita",
        "success": True,
        "data": data,
        "message": "✅ Tu hora ha sido cancelada exitosamente.",
    }
    return res
