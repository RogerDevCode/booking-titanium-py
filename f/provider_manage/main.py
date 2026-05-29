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
# Mission         : CRUD for providers, services, schedules, and overrides
# DB Tables Used  : providers, services, provider_schedules, schedule_overrides
# Concurrency Risk: NO — atomic operations
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates action and fields
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._manage_logic import (
    handle_override_actions,
    handle_provider_actions,
    handle_schedule_actions,
    handle_service_actions,
)
from ._manage_models import InputSchema

MODULE = "provider_manage"


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"VALIDATION_ERROR: {e}") from e

    # For list_providers, provider_id might be None initially, but for others it is required
    # However, list_providers usually runs in admin context or with a specific provider filter.
    # If no provider_id, we default to with_admin_context (if needed) or just with_tenant_context with empty

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context (if provider_id supplied)
        async def operation() -> dict[str, object]:
            action = input_data.action
            if "provider" in action:
                return await handle_provider_actions(conn, input_data)
            if "service" in action:
                return await handle_service_actions(conn, input_data)
            if "schedule" in action:
                return await handle_schedule_actions(conn, input_data)
            if "override" in action:
                return await handle_override_actions(conn, input_data)

            raise RuntimeError(f"ROUTING_ERROR: Unknown action group: {action}")

        # If it's a global action like 'list_providers', we could use a dummy tenant or admin context
        tenant_id = input_data.provider_id or "00000000-0000-0000-0000-000000000000"
        return await with_tenant_context(conn, tenant_id, operation)

    except Exception as e:
        log("Provider Manage Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"INTERNAL_ERROR: {e}") from e
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
