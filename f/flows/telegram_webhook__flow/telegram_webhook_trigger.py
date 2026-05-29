from __future__ import annotations

import contextlib
import json
import os
import urllib.request
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

type EventKind = Literal["message", "callback", "empty"]
type TextKind = Literal["plain_text", "command_start", "command_other", "callback", "empty"]


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int


class TelegramFrom(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


class TelegramContact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    phone_number: str
    first_name: str
    last_name: str | None = None
    user_id: int | None = None


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message_id: int
    chat: TelegramChat | None = None
    from_: TelegramFrom | None = Field(None, alias="from")
    text: str | None = None
    contact: TelegramContact | None = None


class TelegramCallbackQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    from_: TelegramFrom | None = Field(None, alias="from")
    message: TelegramMessage | None = None
    data: str | None = None


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    update_id: int | None = None
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None


def _answer_callback_query(callback_query_id: str, bot_token: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    data = json.dumps({"callback_query_id": callback_query_id}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with contextlib.suppress(Exception):
        urllib.request.urlopen(req, timeout=2)  # Non-fatal — best-effort answer


async def _main_async(webhook_payload: dict[str, Any]) -> dict[str, Any]:
    # Extract actual Telegram payload from Windmill's wrapper if present
    payload: dict[str, Any] = webhook_payload
    if "body" in webhook_payload and isinstance(webhook_payload["body"], dict):
        payload = cast("dict[str, Any]", webhook_payload["body"])
    elif "message" not in webhook_payload and "callback_query" not in webhook_payload:
        for key in ["webhook_payload", "data", "event"]:
            if key in webhook_payload and isinstance(webhook_payload[key], dict):
                payload = cast("dict[str, Any]", webhook_payload[key])
                break

    # Pydantic validation at the boundary (LAW-07)
    try:
        update = TelegramUpdate.model_validate(payload)
    except Exception as e:
        return {"skipped": True, "reason": f"invalid_payload: {e}", "payload": payload}

    update_id = update.update_id
    message = update.message
    callback_query = update.callback_query

    chat_id = ""
    text = ""
    username = "unknown"
    callback_data: str | None = None
    callback_query_id: str | None = None
    callback_message_id: int | None = None
    first_name = "Usuario"
    last_name: str | None = None

    if message:
        from_data = message.from_
        if message.chat:
            chat_id = str(message.chat.id)
        if message.text:
            text = message.text
        elif message.contact:
            text = message.contact.phone_number
        if from_data:
            username = from_data.username or "unknown"
            first_name = from_data.first_name or "Usuario"
            last_name = from_data.last_name
    elif callback_query:
        from_data = callback_query.from_
        msg = callback_query.message
        if msg and msg.chat:
            chat_id = str(msg.chat.id)
        callback_data = callback_query.data
        callback_query_id = callback_query.id
        if msg:
            callback_message_id = msg.message_id
        if from_data:
            username = from_data.username or "unknown"
            first_name = from_data.first_name or "Usuario"
            last_name = from_data.last_name

    # Answer callback query immediately to dismiss Telegram inline button spinner
    if callback_query_id:
        try:
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if bot_token:
                _answer_callback_query(callback_query_id, bot_token)
        except Exception:
            pass  # Non-fatal

    # Inline normalize + classify
    normalized_text = text.strip()
    event_kind: EventKind = "empty"

    if normalized_text:
        event_kind = "message"
    elif callback_data is not None:
        event_kind = "callback"

    text_kind: TextKind = "empty"
    canonical_text = ""
    should_process = False

    if event_kind == "callback":
        # Use callback_data as canonical_text so downstream router receives it
        text_kind = "callback"
        canonical_text = callback_data or ""
        should_process = True
    elif event_kind == "message":
        should_process = True
        canonical_text = normalized_text
        if canonical_text == "/start":
            text_kind = "command_start"
        elif canonical_text.startswith("/"):
            text_kind = "command_other"
        else:
            text_kind = "plain_text"

    return {
        "chat_id": chat_id,
        "text": text,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "update_id": update_id,
        "callback_data": callback_data,
        "callback_query_id": callback_query_id,
        "callback_message_id": callback_message_id,
        "event_kind": event_kind,
        "canonical_text": canonical_text,
        "text_kind": text_kind,
        "should_process": should_process,
    }


def main(webhook_payload: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    return asyncio.run(_main_async(webhook_payload))
