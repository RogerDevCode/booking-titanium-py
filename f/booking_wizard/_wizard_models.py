from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from f.internal._config import DEFAULT_TIMEZONE


class WizardState(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    step: int = Field(default=0, ge=0)
    client_id: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    selected_date: str | None = None
    selected_time: str | None = None


class StepView(TypedDict):
    message: str
    reply_keyboard: list[list[str]]
    new_state: WizardState
    force_reply: bool
    reply_placeholder: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["start", "select_date", "select_time", "confirm", "cancel", "back"]
    wizard_state: dict[str, object] | None = None
    user_input: str | None = None
    provider_id: str | None = None
    service_id: str | None = None
    timezone: str = DEFAULT_TIMEZONE


class WizardResult(TypedDict):
    message: str
    reply_keyboard: list[list[str]]
    force_reply: bool
    reply_placeholder: str
    wizard_state: dict[str, object]
    is_complete: bool
