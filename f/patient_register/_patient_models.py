from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClientResult(TypedDict):
    client_id: str
    name: str
    email: str | None
    phone: str | None
    telegram_chat_id: str | None
    timezone: str
    created: bool


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = None
    telegram_chat_id: str | None = None
    timezone: str | None = None
    idempotency_key: str | None = None
    provider_id: str | None = None
    client_id: str | None = None
