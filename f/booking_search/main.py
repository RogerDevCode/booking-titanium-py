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

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Search and filter bookings
# DB Tables Used  : bookings, providers, clients, services
# Concurrency Risk: NO — read-only query
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES (if provider_id is supplied, but since it is optional, we might query globally if authorized)
# Zod Schemas     : YES — SearchInput validates all inputs
# ============================================================================
from pydantic import BaseModel, ValidationError

from ..internal._db_client import create_db_client
from ..internal._wmill_adapter import log
from ._search_logic import execute_search
from ._search_models import BookingSearchResult, SearchInput

MODULE = "booking_search"


async def _main_async(args: dict[str, object]) -> BookingSearchResult:
    raw_input = args.get("rawInput", args)

    try:
        if not isinstance(raw_input, dict):
            raise ValueError("Input must be a JSON object")
        input_data = SearchInput.model_validate(raw_input)
    except ValidationError as e:
        log("Validation error", error=str(e), module=MODULE)
        raise RuntimeError(f"Validation error: {e}") from e
    except Exception as e:
        log("Validation error", error=str(e), module=MODULE)
        raise RuntimeError(f"Validation error: {e}") from e

    try:
        conn = await create_db_client()
    except Exception as e:
        raise RuntimeError(f"CONFIGURATION_ERROR: {e}") from e

    try:
        result = await execute_search(conn, input_data)
        return result
    except Exception as e:
        msg = str(e)
        log("Internal error", error=msg, module=MODULE)
        raise RuntimeError(f"Internal error: {msg}") from e
    finally:
        await conn.close()


def main(args: SearchInput | dict[str, object]) -> dict[str, object]:
    try:
        if isinstance(args, SearchInput):
            validated = args
        else:
            validated = SearchInput.model_validate(args)

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
