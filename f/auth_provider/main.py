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
#   "typing-extensions>=4.12.0",
#   "pyjwt>=2.12.1"
# ]
# ///
from __future__ import annotations

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Password management for providers
# DB Tables Used  : providers
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates action and fields
# ============================================================================
from typing import Any

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._auth_logic import admin_generate_temp_password, provider_change_password, provider_verify
from ._auth_models import InputSchema

MODULE = "auth_provider"


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    # 1. Validate Input
    input_data = InputSchema.model_validate(args)

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context
        async def operation() -> dict[str, Any]:
            if input_data.action == "admin_generate_temp":
                return await admin_generate_temp_password(conn, input_data)
            elif input_data.action == "provider_change":
                return await provider_change_password(conn, input_data)
            elif input_data.action == "provider_verify":
                return await provider_verify(conn, input_data)

            raise RuntimeError(f"unsupported_action: {input_data.action}")

        result = await with_tenant_context(conn, input_data.tenant_id, operation)
        return result

    except Exception as e:
        log("Auth Provider Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()  # pyright: ignore[reportUnknownMemberType]


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    import asyncio
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
