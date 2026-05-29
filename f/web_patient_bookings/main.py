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
import asyncio

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Client booking history and upcoming appointments
# DB Tables Used  : bookings, providers, services, clients, users
# Concurrency Risk: NO — read-only
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates parameters
# ============================================================================
from typing import Any, cast

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._bookings_logic import get_patient_bookings, resolve_client_id
from ._bookings_models import BookingsResult, InputSchema

MODULE = "web_patient_bookings"


async def _main_async(args: dict[str, Any]) -> dict[str, object]:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context (client_user_id)
        async def operation() -> BookingsResult:
            client_id = await resolve_client_id(conn, input_data.client_user_id)
            if not client_id:
                raise RuntimeError("client_not_found")

            return await get_patient_bookings(conn, client_id, input_data)

        result = await with_tenant_context(conn, input_data.client_user_id, operation)
        return cast("dict[str, object]", result)

    except Exception as e:
        log("Patient Bookings Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()  # pyright: ignore[reportUnknownMemberType]


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    import traceback

    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        return asyncio.run(_main_async(validated.model_dump()))

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
