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
import contextlib
import traceback
from typing import Any, cast

from pydantic import BaseModel

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Handle Telegram inline keyboard button actions
# DB Tables Used  : bookings, booking_audit, clients
# Concurrency Risk: YES — booking state transitions
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates callback_data format
# ============================================================================
from ..internal._wmill_adapter import get_variable, log
from ._callback_logic import (
    answer_callback_query,
    clean_message_reply_markup,
    parse_callback_data,
    send_followup_message,
)
from ._callback_models import ActionContext, InputSchema
from ._callback_router import (
    AcknowledgeHandler,
    AutoRescheduleHandler,
    CancelHandler,
    CancelReasonHandler,
    ConfirmHandler,
    RescheduleCitaHandler,
    TelegramRouter,
)

MODULE = "telegram_callback"


async def _main_async(
    args: dict[str, object],
) -> dict[str, object]:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Invalid input: {e}") from e

    # 2. Resolve bot token
    bot_token = get_variable("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")

    # 3. Parse callback data
    parsed_cb = parse_callback_data(input_data.callback_data)
    if not parsed_cb:
        await answer_callback_query(bot_token, input_data.callback_query_id, "⚠️ Acción no reconocida")
        raise RuntimeError(f"Invalid callback data format: {input_data.callback_data}")

    action = parsed_cb["action"]
    booking_id = parsed_cb["booking_id"]

    # 4. Resolve tenant (client_id or user_id)
    tenant_id = input_data.client_id or input_data.user_id
    if not tenant_id:
        await answer_callback_query(bot_token, input_data.callback_query_id, "⚠️ Error de identificación")
        raise RuntimeError("tenant_id could not be determined")

    # 5. Route and execute action
    router = TelegramRouter()
    router.register("confirm", ConfirmHandler())
    router.register("cancel", CancelHandler())
    router.register("cancel_reason", CancelReasonHandler())
    router.register("acknowledge", AcknowledgeHandler())
    router.register("auto_reschedule", AutoRescheduleHandler())
    router.register("reagendar_cita", RescheduleCitaHandler())

    context: ActionContext = {
        "botToken": bot_token,
        "tenantId": tenant_id,
        "booking_id": booking_id,
        "client_id": input_data.client_id,
        "chat_id": input_data.chat_id,
        "callback_query_id": input_data.callback_query_id,
        "session_id": parsed_cb.get("session_id"),
        "date": parsed_cb.get("date"),
        "time": parsed_cb.get("time"),
        "reason_code": parsed_cb.get("reason_code"),
    }

    result = await router.route(action, context)

    # 6. Response to Telegram
    await answer_callback_query(bot_token, input_data.callback_query_id, result["responseText"])

    # 6.1 Clean original inline markup to prevent double-click abuse
    if input_data.message_id:
        await clean_message_reply_markup(bot_token, input_data.chat_id, input_data.message_id)

    reply_markup = None
    if result.get("followUpText") and result.get("inlineButtons"):
        reply_markup = cast("dict[str, object]", {"inline_keyboard": result.get("inlineButtons")})

    if result.get("followUpText"):
        await send_followup_message(
            bot_token,
            input_data.chat_id,
            str(result["followUpText"]),
            reply_markup=reply_markup,
        )

    return {
        "action": action,
        "booking_id": booking_id,
        "callback_query_id": input_data.callback_query_id,
        "response_text": result["responseText"],
        "follow_up_text": result.get("followUpText"),
        "inline_buttons": result.get("inlineButtons"),
    }


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
        with contextlib.suppress(Exception):
            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        raise RuntimeError(f"Execution failed: {e}") from e
