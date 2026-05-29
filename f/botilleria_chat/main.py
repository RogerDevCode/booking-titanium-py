# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
# ]
# ///
from __future__ import annotations

import asyncio
import contextlib
import traceback
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from ..internal._wmill_adapter import get_variable, log

MODULE = "botilleria_chat"


class BotilleriaChatInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    user_id: str = Field(description="External user ID (Telegram chat_id, WhatsApp number, etc.)")
    message: str = Field(description="User message text")
    platform: str = Field(default="telegram", description="Platform identifier (telegram, whatsapp, web)")
    channel_identifier: str = Field(
        default="",
        description="Channel identifier (bot token, phone number, etc.) for tenant resolution",
    )
    tenant_id: str = Field(
        default="",
        description="Direct tenant UUID (overrides channel resolution)",
    )
    session_id: str = Field(
        default="",
        description="Existing session ID for conversation continuity",
    )


class BotilleriaChatOutput(BaseModel):
    model_config = ConfigDict(strict=True)

    response: str
    session_id: str
    user_id: str
    tenant_slug: str | None = None
    platform: str | None = None


async def _main_async(args: dict[str, object]) -> BotilleriaChatOutput:
    import httpx

    try:
        input_data = BotilleriaChatInput.model_validate(args)
    except Exception as e:
        log("INVALID_INPUT_BOTILLERIA_CHAT", error=str(e), module=MODULE)
        raise RuntimeError(f"Invalid input: {e}") from e

    api_url = get_variable("u/admin/BOTILLERIA_API_URL") or "http://botilleria_core_api:8000"

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Platform": input_data.platform,
    }

    if input_data.tenant_id:
        headers["X-Tenant-ID"] = input_data.tenant_id
    if input_data.channel_identifier:
        headers["X-Channel-Identifier"] = input_data.channel_identifier

    payload: dict[str, Any] = {
        "user_id": input_data.user_id,
        "message": input_data.message,
    }

    if input_data.session_id:
        payload["session_id"] = input_data.session_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{api_url}/chat", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            log(
                "BOTILLERIA_API_HTTP_ERROR",
                status=e.response.status_code,
                body=e.response.text,
                url=f"{api_url}/chat",
                module=MODULE,
            )
            raise RuntimeError(f"Botilleria API error {e.response.status_code}: {e.response.text}") from e
        except httpx.TimeoutException as e:
            log("BOTILLERIA_API_TIMEOUT", url=f"{api_url}/chat", module=MODULE)
            raise RuntimeError(f"Botilleria API timeout: {e}") from e
        except httpx.RequestError as e:
            log("BOTILLERIA_API_REQUEST_ERROR", error=str(e), module=MODULE)
            raise RuntimeError(f"Botilleria API request failed: {e}") from e

    return BotilleriaChatOutput(
        response=data.get("response", ""),
        session_id=data.get("session_id", ""),
        user_id=data.get("user_id", input_data.user_id),
        tenant_slug=data.get("tenant_slug"),
        platform=input_data.platform,
    )


def main(
    user_id: str,
    message: str,
    platform: str = "telegram",
    channel_identifier: str = "",
    tenant_id: str = "",
    session_id: str = "",
) -> dict[str, object]:
    args: dict[str, object] = {
        "user_id": user_id,
        "message": message,
        "platform": platform,
        "channel_identifier": channel_identifier,
        "tenant_id": tenant_id,
        "session_id": session_id,
    }

    try:
        result = asyncio.run(_main_async(args))
        return cast("dict[str, object]", result.model_dump())
    except Exception as e:
        tb = traceback.format_exc()
        with contextlib.suppress(Exception):
            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        raise RuntimeError(f"Execution failed: {e}") from e
