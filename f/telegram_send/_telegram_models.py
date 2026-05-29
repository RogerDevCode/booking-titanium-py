from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

# ============================================================================
# TELEGRAM SEND — Data Models (v1)
# ============================================================================


class InlineButton(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: str = Field(min_length=1)
    callback_data: str = Field(max_length=64)


class BaseTelegramInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    chat_id: str = Field(min_length=1)
    parse_mode: Literal["Markdown", "HTML"] | None = None


class SendMessageInput(BaseTelegramInput):
    mode: Literal["send_message"] = "send_message"
    text: str = Field(min_length=1)
    inline_buttons: list[object] | None = Field(default_factory=lambda: [])
    message_id: int | None = None
    reply_keyboard: list[list[object]] | None = None  # for request_contact button


class EditMessageInput(BaseTelegramInput):
    mode: Literal["edit_message"] = "edit_message"
    message_id: int
    text: str = Field(min_length=1)
    inline_buttons: list[object] | None = Field(default_factory=lambda: [])


class DeleteMessageInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    mode: Literal["delete_message"] = "delete_message"
    chat_id: str = Field(min_length=1)
    message_id: int
    # Optional fields for compatibility
    text: str | None = None
    parse_mode: str | None = None
    inline_buttons: list[object] | None = None


class AnswerCallbackInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    mode: Literal["answer_callback"] = "answer_callback"
    callback_query_id: str = Field(min_length=1)
    callback_alert: str | None = None
    # Compatibility fields
    chat_id: str | None = None
    text: str | None = None
    parse_mode: str | None = None
    inline_buttons: list[object] | None = None
    message_id: int | None = None


TelegramInput = Annotated[
    SendMessageInput | EditMessageInput | DeleteMessageInput | AnswerCallbackInput, Field(discriminator="mode")
]


class TelegramInputRoot(RootModel[TelegramInput]):
    root: TelegramInput


class TelegramResponseResult(BaseModel):
    message_id: int | None = None


class TelegramResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    ok: bool
    result: TelegramResponseResult | None = None
    description: str | None = None
    error_code: int | None = None


class TelegramSendData(BaseModel):
    sent: bool
    message_id: int | None = None
    chat_id: str | None = None
    mode: str
