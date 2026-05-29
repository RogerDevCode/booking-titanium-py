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
# Mission         : Auto-register user from Telegram webhook payload
# DB Tables Used  : users
# Concurrency Risk: NO — UPSERT by telegram_chat_id
# GCal Calls      : NO
# Idempotency Key : YES — handled by checking existing chat_id
# RLS Tenant ID   : YES — with_admin_context bypasses RLS for user discovery
# Pydantic Schemas: YES — InputSchema validates Telegram webhook structure
# ============================================================================
from typing import Any, cast

from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._result import with_admin_context
from ..internal._wmill_adapter import log
from ._auto_register_logic import register_telegram_user
from ._auto_register_models import InputSchema, RegisterResult

MODULE = "telegram_auto_register"


async def _main_async(args: dict[str, object], pg_url: str | None = None) -> dict[str, object]:
    # 1. Validate Input (pg_url already stripped by main() before calling here)
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client(pg_url)
    try:
        # 2. Execute Auth Transaction with Admin Context (bypass RLS)
        async def operation() -> RegisterResult:
            return await register_telegram_user(conn, input_data)

        result = await with_admin_context(conn, operation)
        #         if result is None:
        #             raise RuntimeError("telegram_auto_register returned no result")
        return cast("dict[str, object]", result)

    except Exception as e:
        log("Internal error in auto_register", error=str(e), module=MODULE)
        raise RuntimeError(f"Internal error: {e}") from e
    finally:
        await conn.close()


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    try:
        pg_url: str | None = None
        if isinstance(args, InputSchema):
            validated = args
            clean: dict[str, object] = validated.model_dump()
        else:
            # Strip pg_url before validation — InputSchema has extra="forbid"
            pg_url = str(args["pg_url"]) if args.get("pg_url") is not None else None
            clean = {k: v for k, v in args.items() if k != "pg_url"}
            validated = InputSchema.model_validate(clean)

        result: Any = asyncio.run(_main_async(validated.model_dump(), pg_url=str(pg_url) if pg_url else None))

        if isinstance(result, BaseModel):
            return cast("dict[str, object]", result.model_dump())
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("AUTO_REGISTER_DEGRADED", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
