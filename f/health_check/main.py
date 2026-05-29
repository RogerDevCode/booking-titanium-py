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
import os
import traceback

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : System health monitoring (DB, GCal, Telegram, Gmail)
# DB Tables Used  : NONE — connectivity only
# Concurrency Risk: NO
# GCal Calls      : YES — probe
# Idempotency Key : N/A
# RLS Tenant ID   : NO
# Pydantic Schemas: YES — InputSchema validates optional filter
# ============================================================================
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel

from ..internal._wmill_adapter import get_variable
from ._health_logic import check_database, check_gcal, check_gmail, check_telegram
from ._health_models import ComponentStatus, HealthResult, InputSchema

MODULE = "health_check"


async def _main_async(args: dict[str, object]) -> HealthResult:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    gcal_token = str(get_variable("GCAL_ACCESS_TOKEN")) if get_variable("GCAL_ACCESS_TOKEN") else None
    tg_token = str(get_variable("TELEGRAM_BOT_TOKEN")) if get_variable("TELEGRAM_BOT_TOKEN") else None
    gm_pass = os.getenv("GMAIL_PASSWORD")

    components: list[ComponentStatus] = []

    # 2. Sequential Probes
    if input_data.component in ["all", "database"]:
        components.append(await check_database())

    if input_data.component in ["all", "gcal"]:
        components.append(await check_gcal(gcal_token))

    if input_data.component in ["all", "telegram"]:
        components.append(await check_telegram(tg_token))

    if input_data.component in ["all", "gmail"]:
        components.append(check_gmail(gm_pass))

    # 3. Overall Status
    status_priority = {"unhealthy": 2, "degraded": 1, "healthy": 0, "not_configured": 0}
    max_sev = 0
    for c in components:
        max_sev = max(max_sev, status_priority.get(c["status"], 0))

    overall: Literal["healthy", "unhealthy", "degraded"] = "healthy"
    if max_sev == 2:
        overall = "unhealthy"
    elif max_sev == 1:
        overall = "degraded"

    res: HealthResult = {"overall": overall, "timestamp": datetime.now(UTC).isoformat(), "components": components}
    return res


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
