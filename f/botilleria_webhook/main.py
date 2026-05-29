# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "cryptography>=48.0.0",
# ]
# ///
from __future__ import annotations

import asyncio
import contextlib
import traceback
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from ..internal._wmill_adapter import get_variable, log

MODULE = "botilleria_webhook"


class TelegramWebhookPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    update_id: int
    message_chat_id: int
    message_text: str | None = None
    message_from_id: int | None = None
    message_from_username: str | None = None
    bot_token: str = Field(description="Telegram bot token for tenant resolution")


class BotilleriaWebhookOutput(BaseModel):
    model_config = ConfigDict(strict=True)

    response: str
    session_id: str
    user_id: str
    tenant_slug: str | None = None
    chat_id: int


async def _main_async(args: dict[str, object]) -> BotilleriaWebhookOutput:
    import httpx

    try:
        payload = TelegramWebhookPayload.model_validate(args)
    except Exception as e:
        log("INVALID_WEBHOOK_PAYLOAD", error=str(e), module=MODULE)
        raise RuntimeError(f"Invalid webhook payload: {e}") from e

    if not payload.message_text:
        raise RuntimeError("EMPTY_MESSAGE: Telegram message has no text")

    api_url = get_variable("u/admin/BOTILLERIA_API_URL") or "http://botilleria_core_api:8000"

    user_id = str(payload.message_from_id or payload.message_chat_id)

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Platform": "telegram",
        "X-Channel-Identifier": payload.bot_token,
    }

    request_body: dict[str, Any] = {
        "user_id": user_id,
        "message": payload.message_text,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{api_url}/chat",
                json=request_body,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            log(
                "BOTILLERIA_WEBHOOK_HTTP_ERROR",
                status=e.response.status_code,
                body=e.response.text,
                url=f"{api_url}/chat",
                chat_id=payload.message_chat_id,
                module=MODULE,
            )
            raise RuntimeError(
                f"Botilleria API error {e.response.status_code}: {e.response.text}",
            ) from e
        except httpx.TimeoutException as e:
            log(
                "BOTILLERIA_WEBHOOK_TIMEOUT",
                url=f"{api_url}/chat",
                chat_id=payload.message_chat_id,
                module=MODULE,
            )
            raise RuntimeError(f"Botilleria API timeout: {e}") from e
        except httpx.RequestError as e:
            log(
                "BOTILLERIA_WEBHOOK_REQUEST_ERROR",
                error=str(e),
                chat_id=payload.message_chat_id,
                module=MODULE,
            )
            raise RuntimeError(f"Botilleria API request failed: {e}") from e

    return BotilleriaWebhookOutput(
        response=data.get("response", ""),
        session_id=data.get("session_id", ""),
        user_id=data.get("user_id", user_id),
        tenant_slug=data.get("tenant_slug"),
        chat_id=payload.message_chat_id,
    )


def main(
    update_id: int,
    message_chat_id: int,
    message_text: str | None = None,
    message_from_id: int | None = None,
    message_from_username: str | None = None,
    bot_token: str = "",
) -> dict[str, object]:
    args: dict[str, object] = {
        "update_id": update_id,
        "message_chat_id": message_chat_id,
        "message_text": message_text,
        "message_from_id": message_from_id,
        "message_from_username": message_from_username,
        "bot_token": bot_token,
    }

    try:
        result = asyncio.run(_main_async(args))
        return cast("dict[str, object]", result.model_dump())
    except Exception as e:
        tb = traceback.format_exc()
        with contextlib.suppress(Exception):
            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        raise RuntimeError(f"Execution failed: {e}") from e
