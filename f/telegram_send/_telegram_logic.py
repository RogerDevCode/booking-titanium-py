from __future__ import annotations

"""Telegram API integration logic - handles untyped API responses."""
import asyncio  # noqa: E402
from typing import cast  # noqa: E402

import httpx  # noqa: E402

from ..internal._config import MAX_RETRIES, TIMEOUT_TELEGRAM_API_MS  # noqa: E402
from ._telegram_models import (  # noqa: E402
    AnswerCallbackInput,
    DeleteMessageInput,
    EditMessageInput,
    SendMessageInput,
    TelegramInput,
    TelegramResponse,
    TelegramSendData,
)


class TelegramService:
    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def execute(self, input_data: TelegramInput) -> TelegramSendData:
        endpoint, body = self.prepare_request(input_data)

        last_err: Exception | str | None = None
        for attempt in range(MAX_RETRIES):
            try:
                res_data = await self.api_call(endpoint, body)
                # Ensure message_id is int | None
                msg_id = (
                    int(res_data.result.message_id)
                    if res_data.result and res_data.result.message_id is not None
                    else None
                )
                chat_id = str(input_data.chat_id) if hasattr(input_data, "chat_id") else None

                res: TelegramSendData = TelegramSendData(
                    sent=True, message_id=msg_id, mode=input_data.mode, chat_id=chat_id
                )
                return res
            except Exception as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (2**attempt))

        raise RuntimeError(str(last_err) or "Telegram API failed")

    def prepare_request(self, input_data: TelegramInput) -> tuple[str, dict[str, object]]:
        mode = input_data.mode

        if mode == "send_message":
            inp_s = cast("SendMessageInput", input_data)
            keyboard = self.normalize_keyboard(inp_s.inline_buttons)
            # reply_keyboard takes precedence over inline_keyboard (mutually exclusive in Telegram)
            if inp_s.reply_keyboard:
                reply_markup: dict[str, object] = {
                    "keyboard": inp_s.reply_keyboard,
                    "one_time_keyboard": True,
                    "resize_keyboard": True,
                }
            elif keyboard:
                reply_markup = {"inline_keyboard": keyboard}
            else:
                reply_markup = {}
            return f"{self.base_url}/sendMessage", {
                "chat_id": inp_s.chat_id,
                "text": inp_s.text,
                "parse_mode": inp_s.parse_mode,
                "reply_markup": reply_markup if reply_markup else None,
            }

        elif mode == "edit_message":
            inp_e = cast("EditMessageInput", input_data)
            keyboard = self.normalize_keyboard(inp_e.inline_buttons)
            return f"{self.base_url}/editMessageText", {
                "chat_id": inp_e.chat_id,
                "message_id": inp_e.message_id,
                "text": inp_e.text,
                "parse_mode": inp_e.parse_mode,
                "reply_markup": {"inline_keyboard": keyboard} if keyboard else None,
            }

        elif mode == "delete_message":
            inp_d = cast("DeleteMessageInput", input_data)
            return f"{self.base_url}/deleteMessage", {"chat_id": inp_d.chat_id, "message_id": inp_d.message_id}

        elif mode == "answer_callback":
            inp_a = cast("AnswerCallbackInput", input_data)
            body: dict[str, object] = {"callback_query_id": inp_a.callback_query_id}
            if inp_a.callback_alert:
                body["text"] = inp_a.callback_alert
                body["show_alert"] = True
            return f"{self.base_url}/answerCallbackQuery", body

        raise ValueError(f"Unsupported mode: {mode}")

    async def api_call(self, url: str, body: dict[str, object]) -> TelegramResponse:
        async with httpx.AsyncClient(timeout=TIMEOUT_TELEGRAM_API_MS / 1000.0) as client:
            clean_body: dict[str, object] = {k: v for k, v in body.items() if v is not None}
            response = await client.post(url, json=clean_body)

            data: object = response.json()
            if not isinstance(data, dict):
                raise ValueError("Telegram API returned non-object response")

            parsed = TelegramResponse.model_validate(data)

            if not parsed.ok:
                desc = parsed.description or "Unknown error"
                code = parsed.error_code or 0
                raise Exception(f"TELEGRAM_ERROR_{code}: {desc}")

            return parsed

    def normalize_keyboard(self, buttons: list[object] | None) -> list[list[dict[str, str]]]:
        if not buttons:
            return []

        # Case 1: Already a list of lists
        if len(buttons) > 0 and isinstance(buttons[0], list):
            return cast("list[list[dict[str, str]]]", buttons)

        # Case 2: Flat list
        normalized: list[list[dict[str, str]]] = []
        flat_list = list(buttons)
        for i in range(0, len(flat_list), 2):
            row: list[dict[str, str]] = []
            for b_obj in flat_list[i : i + 2]:
                if hasattr(b_obj, "text") and hasattr(b_obj, "callback_data"):
                    b = cast("dict[str, str]", b_obj)
                    row.append({"text": str(b["text"]), "callback_data": str(b["callback_data"])})
                elif isinstance(b_obj, dict):
                    b_dict = cast("dict[str, object]", b_obj)
                    row.append(
                        {"text": str(b_dict.get("text", "")), "callback_data": str(b_dict.get("callback_data", ""))}
                    )
            normalized.append(row)
        return normalized
