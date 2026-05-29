# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "email-validator>=2.2.0",
#   "asyncpg>=0.30.0",
#   "cryptography>=48.0.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "redis>=7.4.0",
#   "typing-extensions>=4.12.0"
# ]
# ///
from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError

from ..internal._db_client import create_db_client
from ..internal._result import DBClient, with_tenant_context
from ..internal._state_machine import validate_transition
from ..internal._wmill_adapter import log
from ._reschedule_logic import RescheduleBookingError, authorize, execute_reschedule_logic
from ._reschedule_models import RescheduleInput, RescheduleResult
from ._reschedule_repository import PostgresRescheduleRepository

MODULE = "booking_reschedule"


async def run_reschedule_booking(conn: DBClient, args: dict[str, Any]) -> RescheduleResult:
    """Shared core: execute booking reschedule using an existing DB connection."""
    raw_input = args.get("rawInput", args)
    if not isinstance(raw_input, dict):
        raise RescheduleBookingError("invalid_input: expected_dictionary")
    try:
        input_data = RescheduleInput.model_validate(raw_input)
    except ValidationError as e:
        raise RescheduleBookingError(f"validation_failed: {e}") from e

    repo = PostgresRescheduleRepository(conn)

    old_booking = await repo.fetch_booking(input_data.booking_id)
    if not old_booking:
        raise RescheduleBookingError(f"booking_not_found: {input_data.booking_id}")

    service_id = input_data.new_service_id or old_booking["service_id"]
    service = await repo.fetch_service(service_id)
    if not service:
        raise RescheduleBookingError(f"service_not_found: {service_id}")

    err_trans, _ = validate_transition(old_booking["status"], "rescheduled")
    if err_trans:
        raise RescheduleBookingError(f"invalid_transition: {err_trans}")

    authorize(input_data, old_booking)

    async def operation() -> object:
        return await execute_reschedule_logic(repo, input_data, old_booking, service)

    tenant_id = str(old_booking["provider_id"])
    write_result = cast("dict[str, Any]", await with_tenant_context(conn, tenant_id, operation))

    if not write_result:
        raise RescheduleBookingError("reschedule_failed")

    result: RescheduleResult = {
        "old_booking_id": str(write_result["old_booking_id"]),
        "new_booking_id": str(write_result["new_booking_id"]),
        "old_status": str(write_result["old_status"]),
        "new_status": str(write_result["new_status"]),
        "old_start_time": old_booking["start_time"].isoformat(),
        "new_start_time": str(write_result["new_start_time"]),
        "new_end_time": str(write_result["new_end_time"]),
    }
    return result


async def main_async(args: dict[str, Any]) -> RescheduleResult:
    conn = await create_db_client()
    try:
        return await run_reschedule_booking(conn, args)
    except RescheduleBookingError:
        raise
    except Exception as e:
        log("CRITICAL_RESCHEDULE_ERROR", error=str(e), module=MODULE)
        raise RescheduleBookingError(f"unhandled_reschedule_error: {e}") from e
    finally:
        await conn.close()


def main(args: RescheduleInput | dict[str, Any]) -> dict[str, Any]:
    import asyncio
    import traceback

    try:
        if isinstance(args, RescheduleInput):
            validated = args
        else:
            validated = RescheduleInput.model_validate(args)

        result = asyncio.run(main_async(validated.model_dump()))
        return cast("dict[str, Any]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("ENTRYPOINT_CATASTROPHE", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
