from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class TelegramNormalizeInput(BaseModel):
    model_config = ConfigDict(strict=True)

    chat_id: str
    text: str
    username: str
    callback_data: str | None = None
    callback_query_id: str | None = None
    callback_message_id: int | None = None


class TelegramNormalizeResult(BaseModel):
    model_config = ConfigDict(strict=True)

    processable: bool
    event_kind: Literal["message", "callback", "empty"]
    chat_id: str
    normalized_text: str
    username: str
    callback_data: str | None = None
    callback_query_id: str | None = None
    callback_message_id: int | None = None
