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

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Advisory lock for race condition prevention
# DB Tables Used  : booking_locks, providers
# Concurrency Risk: YES — lock mechanism itself
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — provider_id used for all queries
# Pydantic Schemas: YES — InputSchema validates action and key
# ============================================================================
from typing import Any, cast

from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._lock_logic import acquire_lock, check_lock, cleanup_locks, release_lock
from ._lock_models import InputSchema, LockResult

MODULE = "distributed_lock"


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    # 1. Validate Input
    try:
        data = args.get("rawInput", args)
        input_data = InputSchema.model_validate(data)
    except Exception as e:
        raise RuntimeError(f"validation_failed: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context
        async def operation() -> LockResult:
            if input_data.action == "acquire":
                return await acquire_lock(conn, input_data)
            elif input_data.action == "release":
                return await release_lock(conn, input_data)
            elif input_data.action == "check":
                return await check_lock(conn, input_data.lock_key)
            elif input_data.action == "cleanup":
                return await cleanup_locks(conn)

            raise RuntimeError(f"unsupported_action: {input_data.action}")

        result = await with_tenant_context(conn, input_data.provider_id, operation)
        #         if result is None:
        #             raise RuntimeError("Distributed lock returned no result")
        return cast("dict[str, object]", result)

    except Exception as e:
        log("Distributed Lock Internal Error", error=str(e), module=MODULE)
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
