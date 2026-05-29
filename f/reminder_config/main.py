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
# Mission         : Configure reminder preferences (UI-driven)
# DB Tables Used  : clients
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps DB ops
# Pydantic Schemas: YES — InputSchema validates action and client_id
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._config_models import InputSchema, ReminderConfigResult
from ._config_repository import load_preferences, save_preferences
from ._config_service import activate_all, deactivate_all, toggle_channel, toggle_window
from ._config_view import build_config_view

MODULE = "reminder_config"


async def run_reminder_config(input_data: InputSchema, pg_url: str | None = None) -> ReminderConfigResult:
    conn = await create_db_client(pg_url)
    try:

        async def operation() -> ReminderConfigResult:
            preferences = await load_preferences(conn, input_data.client_id)

            match input_data.action:
                case "toggle_channel":
                    if input_data.channel is None:
                        raise RuntimeError("missing_channel")
                    preferences = toggle_channel(preferences, input_data.channel)
                    await save_preferences(conn, input_data.client_id, preferences)
                case "toggle_window":
                    if input_data.window is None:
                        raise RuntimeError("missing_window")
                    preferences = toggle_window(preferences, input_data.window)
                    await save_preferences(conn, input_data.client_id, preferences)
                case "deactivate_all":
                    preferences = deactivate_all(preferences)
                    await save_preferences(conn, input_data.client_id, preferences)
                case "activate_all":
                    preferences = activate_all()
                    await save_preferences(conn, input_data.client_id, preferences)
                case "show" | "back":
                    pass

            view = build_config_view(preferences)
            return ReminderConfigResult(
                message=view.message,
                inline_buttons=view.inline_buttons,
                preferences=preferences,
            )

        return await with_tenant_context(conn, input_data.client_id, operation)
    except Exception as e:
        log("Reminder Config Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()


async def _main_async(args: dict[str, object]) -> ReminderConfigResult:
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Invalid input: {e}") from e

    return await run_reminder_config(input_data)


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
