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
from typing import Any, cast

from pydantic import BaseModel

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Send email notifications with HTML action links
# DB Tables Used  : NONE
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : NO
# Pydantic Schemas: YES — InputSchema validates recipient and message type
# ============================================================================
from ..internal._wmill_adapter import log
from ._gmail_logic import build_email_content, send_with_retry
from ._gmail_models import GmailSendData, InputSchema

MODULE = "gmail_send"


async def _main_async(args: dict[str, object]) -> GmailSendData:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Invalid input: {e}") from e

    # 2. Resolve SMTP Configuration
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except (ValueError, TypeError):
        smtp_port = 587

    smtp_user = os.getenv("GMAIL_USER") or os.getenv("DEV_LOCAL_GMAIL_USER")
    smtp_pass = os.getenv("GMAIL_PASSWORD") or os.getenv("DEV_LOCAL_GMAIL_PASS")
    from_email = os.getenv("GMAIL_FROM_EMAIL") or smtp_user
    from_name = os.getenv("GMAIL_FROM_NAME", "Sistema de Citas Médicas")

    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP credentials not configured (GMAIL_USER/GMAIL_PASSWORD)")

    smtp_config: dict[str, object] = {"host": smtp_host, "port": smtp_port, "user": smtp_user, "password": smtp_pass}

    # 3. Build Content
    subject, html = build_email_content(input_data.message_type, input_data.booking_details, input_data.action_links)

    # 4. Dispatch with Retry
    from_addr = f"{from_name} <{from_email}>"
    err_send, msg_id = await send_with_retry(smtp_config, from_addr, input_data.recipient_email, subject, html)

    if err_send:
        log("Gmail send failed", error=str(err_send), module=MODULE)
        raise RuntimeError(str(err_send))

    res: GmailSendData = {
        "sent": True,
        "message_id": msg_id,
        "recipient_email": str(input_data.recipient_email),
        "message_type": input_data.message_type,
        "subject": subject,
    }
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
