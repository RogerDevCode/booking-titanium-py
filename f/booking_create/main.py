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

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Create a new medical appointment (SOLID Refactor)
# DB Tables Used  : bookings, providers, clients, services, schedule_overrides, provider_schedules, booking_audit
# Concurrency Risk: YES — GIST exclusion constraint + SELECT FOR UPDATE on provider
# GCal Calls      : NO — gcal_sync handles async sync after creation
# Idempotency Key : YES — ON CONFLICT (idempotency_key) handled
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Zod Schemas     : YES — InputSchema validates all inputs
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import DBClient, with_tenant_context
from ..internal._wmill_adapter import log
from ._booking_create_models import BookingCreated, InputSchema
from ._booking_create_repository import PostgresBookingCreateRepository
from ._create_booking_logic import execute_create_booking

MODULE = "booking_create"


async def run_create_booking(conn: DBClient, args: dict[str, object]) -> BookingCreated:
    """Shared core: execute booking creation using an existing DB connection."""
    input_data = InputSchema.model_validate(args)
    repo = PostgresBookingCreateRepository(conn)

    async def operation() -> BookingCreated:
        return await execute_create_booking(repo, input_data)

    result = await with_tenant_context(conn, input_data.provider_id, operation)

    if not result:
        raise RuntimeError("Booking creation failed: no result")

    log("Booking creation complete", booking_id=str(result["booking_id"]), module=MODULE)
    return result


async def main_async(args: dict[str, object]) -> BookingCreated:
    conn = await create_db_client()
    try:
        return await run_create_booking(conn, args)
    finally:
        await conn.close()


async def _main_async(args: dict[str, object]) -> BookingCreated:
    """Windmill entrypoint."""
    return await main_async(args)


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    import asyncio
    import traceback
    from typing import cast

    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result = asyncio.run(_main_async(validated.model_dump()))

        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
