from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConversationState(BaseModel):
    model_config = ConfigDict(strict=True)

    chat_id: str
    active_flow: str | None = None
    flow_step: int = 0
    pending_data: dict[str, Any] = Field(default_factory=dict)
    booking_state: dict[str, Any] | None = None
    booking_draft: dict[str, Any] | None = None
    message_id: int | None = None
    version: int = 1
    updated_at: str


class ConversationGetResult(BaseModel):
    model_config = ConfigDict(strict=True)
    data: ConversationState | None = None
