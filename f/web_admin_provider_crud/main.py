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
# Mission         : CRUD for providers management (admin dashboard)
# DB Tables Used  : providers, honorifics, specialties, regions, communes, timezones
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context for mutations
# Pydantic Schemas: YES — InputSchema validates all fields
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_admin_context, with_tenant_context
from ..internal._wmill_adapter import log
from ._provider_logic import create_provider, list_providers, reset_provider_password, update_provider
from ._provider_models import InputSchema, ProviderRow

MODULE = "web_admin_provider_crud"

type ProviderCRUDResult = list[ProviderRow] | ProviderRow | dict[str, object]


async def _main_async(args: dict[str, object]) -> ProviderCRUDResult:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 'list' is global admin operation
        if input_data.action == "list":
            return await with_admin_context(conn, lambda: list_providers(conn))

        # Actions like 'create' might not have provider_id yet
        # For create, we use a global admin context or a temporary ID
        if input_data.action == "create":

            async def create_op() -> ProviderRow:
                return await create_provider(conn, input_data)

            return await with_admin_context(conn, create_op)

        # Other actions require provider_id (tenant context)
        provider_id = input_data.provider_id
        if not provider_id:
            raise RuntimeError("provider_id is required for non-list/create operations")

        async def operation() -> ProviderCRUDResult:
            if input_data.action == "update":
                return await update_provider(conn, input_data)
            elif input_data.action == "activate" or input_data.action == "deactivate":
                active = input_data.action == "activate"
                # provider table uses 'provider_id' as PK in most schemas, but model says 'id'
                # checking f/f/database/init/001_core_schema.sql usually shows provider_id
                await conn.execute(
                    "UPDATE providers SET is_active = $1, updated_at = NOW() WHERE provider_id = $2::uuid",
                    active,
                    provider_id,
                )
                res: dict[str, object] = {"provider_id": provider_id, "is_active": active}
                return res
            elif input_data.action == "reset_password":
                return await reset_provider_password(conn, provider_id)

            raise RuntimeError(f"Unsupported action: {input_data.action}")

        return await with_tenant_context(conn, provider_id, operation)

    except Exception as e:
        log("Admin Provider CRUD Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    import asyncio
    import traceback
    from typing import cast

    from pydantic import BaseModel

    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result = asyncio.run(_main_async(validated.model_dump()))

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
