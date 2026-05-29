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

import asyncio
import traceback
from typing import Any, cast

from pydantic import BaseModel

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : View provider daily/weekly schedule with bookings
# DB Tables Used  : providers, provider_schedules, bookings, clients, services, schedule_overrides
# Concurrency Risk: NO — read-only
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps DB ops
# Pydantic Schemas: YES — InputSchema validates provider_id, date_range
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._agenda_logic import get_provider_agenda
from ._agenda_models import InputSchema

MODULE = "provider_agenda"


async def _main_async(args: dict[str, object]) -> object:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context
        async def operation() -> object:
            # Construct AgendaInput from InputSchema
            from datetime import date

            from ._agenda_models import AgendaInput

            # Use date_from as the target_date for the single-day logic
            agenda_input = AgendaInput(
                provider_id=input_data.provider_id, target_date=date.fromisoformat(input_data.date_from)
            )
            return await get_provider_agenda(conn, agenda_input)

        return await with_tenant_context(conn, input_data.provider_id, operation)

    except Exception as e:
        log("Provider Agenda Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result: Any = asyncio.run(_main_async(validated.model_dump()))

        if isinstance(result, BaseModel):
            return cast("dict[str, object]", result.model_dump())
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
