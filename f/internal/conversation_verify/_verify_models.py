from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PersistedConversationState(BaseModel):
    model_config = ConfigDict(strict=True)

    chat_id: str
    active_flow: str | None = None
    flow_step: int = 0
    pending_data: dict[str, object]
    booking_state: dict[str, object] | None = None
    booking_draft: dict[str, object] | None = None
    message_id: int | None = None
    updated_at: str


class ConversationVerifyInput(BaseModel):
    model_config = ConfigDict(strict=True)

    expected_chat_id: str
    expected_echo_count: int
    persisted_state: PersistedConversationState | None = None


class ConversationVerifyResult(BaseModel):
    model_config = ConfigDict(strict=True)

    success: bool
    verified_chat_id: str
    verified_echo_count: int
