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
import traceback

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Manage medical specialties (CRUD + activate/deactivate)
# DB Tables Used  : specialties
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates action and fields
# ============================================================================
from typing import Any, cast

from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._specialty_logic import create_specialty, delete_specialty, list_specialties, set_status, update_specialty
from ._specialty_models import InputSchema

MODULE = "web_admin_specialties_crud"


async def _main_async(args: dict[str, Any]) -> object:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context (using admin_user_id as isolation context)
        async def operation() -> object:
            if input_data.action == "list":
                return await list_specialties(conn)
            elif input_data.action == "create":
                return await create_specialty(conn, input_data)
            elif input_data.action == "update":
                if not input_data.specialty_id:
                    raise RuntimeError("update_failed: specialty_id is required")
                return await update_specialty(conn, input_data.specialty_id, input_data)
            elif input_data.action == "delete":
                if not input_data.specialty_id:
                    raise RuntimeError("delete_failed: specialty_id is required")
                return await delete_specialty(conn, input_data.specialty_id)
            elif input_data.action == "activate" or input_data.action == "deactivate":
                if not input_data.specialty_id:
                    raise RuntimeError(f"{input_data.action}_failed: specialty_id is required")
                return await set_status(conn, input_data.specialty_id, input_data.action == "activate")

            raise RuntimeError(f"Unsupported action: {input_data.action}")

        return await with_tenant_context(conn, input_data.admin_user_id, operation)

    except Exception as e:
        log("Admin Specialty CRUD Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()  # pyright: ignore[reportUnknownMemberType]


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
