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

from ._normalize_models import TelegramNormalizeInput, TelegramNormalizeResult

type EventKind = Literal["message", "callback", "empty"]


def _coerce_input_data(input_data: TelegramNormalizeInput | dict[str, object]) -> TelegramNormalizeInput:
    if isinstance(input_data, TelegramNormalizeInput):
        return input_data

    return TelegramNormalizeInput.model_validate(input_data)


def _normalize_text(value: str) -> str:
    return value.strip()


async def _main_async(input_data: TelegramNormalizeInput) -> TelegramNormalizeResult:
    normalized_text = _normalize_text(input_data.text)
    event_kind: EventKind = "empty"
    processable = False

    if normalized_text:
        event_kind = "message"
        processable = True
    elif input_data.callback_data is not None:
        event_kind = "callback"
    else:
        event_kind = "empty"

    return TelegramNormalizeResult(
        processable=processable,
        event_kind=event_kind,
        chat_id=input_data.chat_id,
        normalized_text=normalized_text,
        username=input_data.username,
        callback_data=input_data.callback_data,
        callback_query_id=input_data.callback_query_id,
        callback_message_id=input_data.callback_message_id,
    )


def main(input_data: TelegramNormalizeInput | dict[str, object]) -> dict[str, object]:
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

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module="telegram_normalize")
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
