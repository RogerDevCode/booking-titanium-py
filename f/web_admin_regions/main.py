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
# Mission         : Read-only reference data for regions and communes
# DB Tables Used  : regions, communes
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : NO — public reference data
# Pydantic Schemas: YES — InputSchema validates action and region_id
# ============================================================================
from typing import Any, cast

from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._wmill_adapter import log
from ._regions_logic import list_communes, list_regions, search_communes
from ._regions_models import InputSchema

MODULE = "web_admin_regions"


async def _main_async(args: dict[str, Any]) -> object:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        if input_data.action == "list_regions":
            return await list_regions(conn)

        elif input_data.action == "list_communes":
            return await list_communes(conn, input_data.region_id)

        elif input_data.action == "search_communes":
            return await search_communes(conn, input_data.search or "", input_data.region_id)

        raise RuntimeError(f"Unsupported action: {input_data.action}")

    except Exception as e:
        log("Admin Regions Internal Error", error=str(e), module=MODULE)
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
