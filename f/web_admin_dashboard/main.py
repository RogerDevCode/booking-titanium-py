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
# Mission         : Admin stats and system overview KPIs
# DB Tables Used  : bookings, providers, clients, users, booking_audit
# Concurrency Risk: NO — read-only
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates admin_user_id
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._dashboard_logic import fetch_dashboard_stats
from ._dashboard_models import AdminDashboardResult, InputSchema

MODULE = "web_admin_dashboard"


async def _main_async(args: dict[str, object]) -> AdminDashboardResult:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context (admin_user_id is the tenant filter for with_tenant_context)
        async def operation() -> AdminDashboardResult:
            return await fetch_dashboard_stats(conn, input_data)

        return await with_tenant_context(conn, input_data.admin_user_id, operation)

    except Exception as e:
        log("Admin Dashboard Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()


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
