from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RouterInput(BaseModel):
    model_config = ConfigDict(strict=True)

    chat_id: str
    user_input: str
    state: dict[str, object] | None = None
    items: list[dict[str, object]] | None = None
    phone: str | None = None
    client_name: str | None = None
    prefetch_block_reason: str | None = None
    client_id: str | None = None
    pg_url: str | None = None
    callback_message_id: int | None = None
    ai_intent: str | None = None
    ai_confidence: float | None = None
    ai_entities: dict[str, object] = Field(default_factory=dict)
    requires_fsm_routing: bool = False
    update_id: int | None = None


class RouterResult(BaseModel):
    model_config = ConfigDict(strict=True)
    handled: bool
    response_text: str | None = None
    nextState: dict[str, object] | None = None
    nextDraft: dict[str, object] | None = None
    inline_buttons: list[list[Any]] | None = None
    reply_keyboard: list[list[object]] | None = None  # native Telegram ReplyKeyboard
    active_flow: str | None = None
    registration_data: dict[str, str | None] | None = None
    edit_message: bool = False
