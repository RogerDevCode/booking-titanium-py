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

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._patient_logic import upsert_client
from ._patient_models import ClientResult, InputSchema

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Create or update client records
# DB Tables Used  : clients
# Concurrency Risk: NO — UPSERT pattern
# GCal Calls      : NO
# Idempotency Key : YES — multiple identifiers supported
# RLS Tenant ID   : YES — with_tenant_context wraps DB ops
# Pydantic Schemas: YES — InputSchema validates name, email, phone
# ============================================================================

MODULE = "patient_register"


async def main_async(args: dict[str, Any]) -> dict[str, Any]:
    """
    Main business logic execution.
    """
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    # 2. Resolve Tenant Identifier
    # We require a tenant ID (provider_id or client_id) to activate RLS
    tenant_id = input_data.provider_id or input_data.client_id
    if not tenant_id:
        raise RuntimeError("tenant_id required for isolation (provider_id or client_id)")

    # 3. Minimum Identification Requirement
    if not any([input_data.email, input_data.phone, input_data.telegram_chat_id]):
        raise RuntimeError("At least one identifier required (email, phone, or telegram_chat_id)")

    conn = await create_db_client()
    try:
        # 4. Execute operation within tenant context
        async def operation() -> ClientResult:
            return await upsert_client(conn, input_data)

        result = await with_tenant_context(conn, tenant_id, operation)
        #         if result is None:
        #             raise RuntimeError("patient_register returned no result")
        return cast("dict[str, Any]", result)

    except Exception as e:
        log("Unexpected error in patient_register", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_database_error: {e}") from e
    finally:
        await conn.close()


def main(args: InputSchema | dict[str, Any]) -> dict[str, Any]:
    """
    Windmill sync wrapper.
    """

    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result: Any = asyncio.run(main_async(validated.model_dump()))

        if isinstance(result, BaseModel):
            return result.model_dump()

        return cast("dict[str, Any]", result)
    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
