from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# TELEGRAM GATEWAY — Data Models (v1)
# ============================================================================


class TelegramUser(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: int
    is_bot: bool | None = None
    first_name: str = "Usuario"
    last_name: str | None = None
    username: str | None = None


class TelegramChat(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: int
    type: Literal["private", "group", "supergroup", "channel"]


class TelegramMessage(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    message_id: int
    from_user: TelegramUser | None = Field(None, alias="from")
    chat: TelegramChat
    date: int
    text: str | None = None


class TelegramCallback(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: str
    from_user: TelegramUser | None = Field(None, alias="from")
    message: TelegramMessage | None = None
    data: str


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    update_id: int
    message: TelegramMessage | None = None
    callback_query: TelegramCallback | None = None


class SendMessageOptions(BaseModel):
    parse_mode: Literal["Markdown", "HTML", "MarkdownV2"] | None = "Markdown"
    reply_markup: dict[str, object] | None = None
