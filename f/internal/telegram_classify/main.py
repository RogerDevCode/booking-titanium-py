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

from typing import Literal, cast

from ._classify_models import TelegramClassifyInput, TelegramClassifyResult

type TextKind = Literal["plain_text", "command_start", "command_other", "callback", "empty"]


def _coerce_input_data(input_data: TelegramClassifyInput | dict[str, object]) -> TelegramClassifyInput:
    if isinstance(input_data, TelegramClassifyInput):
        return input_data

    return TelegramClassifyInput.model_validate(input_data)


async def _main_async(input_data: TelegramClassifyInput) -> TelegramClassifyResult:
    if input_data.event_kind == "callback":
        return TelegramClassifyResult(
            should_process=False,
            text_kind="callback",
            chat_id=input_data.chat_id,
            canonical_text="",
            username=input_data.username,
        )

    if input_data.event_kind == "empty" or not input_data.processable:
        return TelegramClassifyResult(
            should_process=False,
            text_kind="empty",
            chat_id=input_data.chat_id,
            canonical_text="",
            username=input_data.username,
        )

    canonical_text = input_data.normalized_text
    text_kind: TextKind
    if canonical_text == "/start":
        text_kind = "command_start"
    elif canonical_text.startswith("/"):
        text_kind = "command_other"
    else:
        text_kind = "plain_text"

    return TelegramClassifyResult(
        should_process=True,
        text_kind=text_kind,
        chat_id=input_data.chat_id,
        canonical_text=canonical_text,
        username=input_data.username,
    )


def main(input_data: TelegramClassifyInput | dict[str, object]) -> dict[str, object]:
    import asyncio
    import traceback

    try:
        validated_input = _coerce_input_data(input_data)
        result = asyncio.run(_main_async(validated_input))
        return cast("dict[str, object]", result.model_dump())
    except Exception as e:
        tb = traceback.format_exc()
        try:
            from .._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module="telegram_classify")
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
