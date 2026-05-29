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

from ..internal._wmill_adapter import log
from ._telegram_logic import TelegramService
from ._telegram_models import TelegramInputRoot, TelegramSendData

MODULE = "telegram_send"


def _normalize_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return " ".join(str(part) for part in cast("tuple[object, ...]", value))
    if value is None:
        return ""
    return str(value)


async def _main_async(args: dict[str, object]) -> TelegramSendData:
    import time

    from ..internal._wmill_adapter import get_variable

    start = time.perf_counter()

    raw_text = args.get("text")
    text = raw_text if isinstance(raw_text, str) else ""

    if not text.strip() or text.strip() == "SKIP_SEND":
        log(
            "Skipping telegram_send due to empty text or SKIP_SEND",
            mode=str(args.get("mode")),
            module=MODULE,
        )
        return TelegramSendData(
            sent=False,
            message_id=None,
            chat_id=cast("str | None", args.get("chat_id")),
            mode=str(args.get("mode")),
        )

    # Extract bot_token if present
    token_arg = args.get("bot_token")
    resolved_token = (
        str(token_arg) if token_arg else get_variable("u/admin/TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    )

    # Create a local copy to modify
    clean_args: dict[str, object] = {k: v for k, v in args.items() if k != "bot_token"}

    # Ensure inline_buttons is not None for validator
    if clean_args.get("inline_buttons") is None:
        clean_args["inline_buttons"] = []

    try:
        input_root = TelegramInputRoot.model_validate(clean_args)
        input_data = input_root.root
    except Exception as e:
        log("Invalid input for telegram_send", error=str(e), module=MODULE)
        raise RuntimeError(f"INVALID_INPUT: {e}") from e

    if not resolved_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_MISSING")

    service = TelegramService(str(resolved_token))
    res = await service.execute(input_data)
    elapsed_ms = (time.perf_counter() - start) * 1000
    log("LATENCY_RESPOND", elapsed_ms=elapsed_ms, module=MODULE)
    return res


def main(
    mode: str,
    chat_id: str,
    text: object,
    bot_token: str | None = None,
    parse_mode: str | None = None,
    inline_buttons_json: str | None = None,
    reply_keyboard_json: str | None = None,
    message_id: int | None = None,
) -> dict[str, object]:
    import json

    inline_buttons: list[object] = []
    if inline_buttons_json:
        try:
            data = json.loads(inline_buttons_json)
            if isinstance(data, list):
                inline_buttons = cast("list[object]", data)
        except Exception as e:
            from ..internal._wmill_adapter import log

            log("JSON parse error for inline_buttons", error=str(e), data=inline_buttons_json)

    reply_keyboard: list[list[object]] | None = None
    if reply_keyboard_json:
        try:
            rk_data = json.loads(reply_keyboard_json)
            if isinstance(rk_data, list):
                reply_keyboard = cast("list[list[object]]", rk_data)
        except Exception as e:
            from ..internal._wmill_adapter import log

            log("JSON parse error for reply_keyboard", error=str(e), data=reply_keyboard_json)

    normalized_text = _normalize_text(text)

    args: dict[str, object] = {
        "mode": mode,
        "chat_id": str(chat_id),
        "text": normalized_text,
        "bot_token": bot_token,
        "parse_mode": parse_mode or "Markdown",
        "inline_buttons": inline_buttons,
        "reply_keyboard": reply_keyboard,
        "message_id": message_id,
    }

    try:
        result: Any = asyncio.run(_main_async(args))
        return cast("dict[str, object]", result.model_dump())
    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_SEND_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            import logging

            logging.error(f"CRITICAL ERROR: {e}\n{tb}")
        raise RuntimeError(f"Send failed: {e}") from e
