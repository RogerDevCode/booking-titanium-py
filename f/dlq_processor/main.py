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
# Mission         : Dead Letter Queue (DLQ) processor for failed bookings
# DB Tables Used  : booking_dlq
# Concurrency Risk: YES — atomic updates and FOR UPDATE locks
# GCal Calls      : NO
# Idempotency Key : YES — preserved from failed bookings
# RLS Tenant ID   : NO — global system table
# Pydantic Schemas: YES — InputSchema validates actions and IDs
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_admin_context
from ..internal._wmill_adapter import log
from ._dlq_logic import discard_dlq, get_dlq_status_stats, list_dlq, resolve_dlq, retry_dlq
from ._dlq_models import InputSchema

MODULE = "dlq_processor"


async def _main_async(args: dict[str, object]) -> object:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"validation_error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute within Admin Context (global system table)
        async def operation() -> object:
            if input_data.action == "list":
                return await list_dlq(conn, input_data.status_filter)
            elif input_data.action == "retry":
                return await retry_dlq(conn, input_data.dlq_id)
            elif input_data.action == "resolve":
                if input_data.dlq_id is None:
                    raise RuntimeError("resolve_error: dlq_id is required")
                return await resolve_dlq(conn, input_data.dlq_id, input_data.resolved_by, input_data.resolution_notes)
            elif input_data.action == "discard":
                if input_data.dlq_id is None:
                    raise RuntimeError("discard_error: dlq_id is required")
                return await discard_dlq(conn, input_data.dlq_id, input_data.resolution_notes)
            elif input_data.action == "status":
                return await get_dlq_status_stats(conn)

            raise RuntimeError(f"unknown_action: {input_data.action}")

        return await with_admin_context(conn, operation)

    except Exception as e:
        log("DLQ Processor Internal Error", error=str(e), module=MODULE)
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
