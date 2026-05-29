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
from ..internal._wmill_adapter import log
from ._booking_cancel_models import CancelBookingInput, CancelResult
from ._booking_cancel_repository import PostgresBookingCancelRepository
from ._cancel_booking_logic import CancelBookingError, authorize_actor, execute_cancel_booking

MODULE = "booking_cancel"


async def run_cancel_booking(conn: DBClient, args: dict[str, Any]) -> CancelResult:
    """Shared core: execute booking cancellation using an existing DB connection."""
    raw_input = args.get("rawInput", args)
    if not isinstance(raw_input, dict):
        raise CancelBookingError("invalid_input: expected_dictionary")
    try:
        input_data = CancelBookingInput.model_validate(raw_input)
    except ValidationError as e:
        raise CancelBookingError(f"validation_failed: {e}") from e

    repo = PostgresBookingCancelRepository(conn)

    booking = await repo.fetch_booking(input_data.booking_id)
    if not booking:
        raise CancelBookingError(f"booking_not_found: {input_data.booking_id}")

    authorize_actor(input_data, booking)

    async def operation() -> object:
        return await execute_cancel_booking(repo, input_data, booking)

    tenant_id = str(booking["provider_id"])
    updated_booking = cast("dict[str, Any]", await with_tenant_context(conn, tenant_id, operation))

    if not updated_booking:
        raise CancelBookingError("cancellation_result_empty")

    result: CancelResult = {
        "booking_id": str(updated_booking["booking_id"]),
        "previous_status": str(booking["status"]),
        "new_status": str(updated_booking["status"]),
        "cancelled_by": str(updated_booking["cancelled_by"]),
        "cancellation_reason": updated_booking.get("cancellation_reason"),
    }
    return result


async def main_async(args: dict[str, Any]) -> CancelResult:
    conn = await create_db_client()
    try:
        return await run_cancel_booking(conn, args)
    except CancelBookingError:
        raise
    except Exception as e:
        log("CRITICAL_CANCEL_ERROR", error=str(e), module=MODULE)
        raise CancelBookingError(f"unhandled_cancellation_error: {e}") from e
    finally:
        await conn.close()


def main(args: CancelBookingInput | dict[str, Any]) -> dict[str, Any]:
    import asyncio
    import traceback

    try:
        if isinstance(args, CancelBookingInput):
            validated = args
        else:
            validated = CancelBookingInput.model_validate(args)

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
