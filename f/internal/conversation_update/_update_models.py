from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ConversationUpdateInput(BaseModel):
    model_config = ConfigDict(strict=True)

    chat_id: str
    active_flow: str | None = None
    flow_step: int | None = None
    pending_data: dict[str, Any] | None = None
    booking_state: dict[str, Any] | None = None
    booking_draft: dict[str, Any] | None = None
    message_id: int | None = None
    version: int | None = None
    clear: bool = False


class ConversationUpdateResult(BaseModel):
    model_config = ConfigDict(strict=True)
    success: bool
    chat_id: str
