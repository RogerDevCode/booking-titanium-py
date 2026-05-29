from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ProfileResult(TypedDict):
    client_id: str
    name: str
    email: str | None
    phone: str | None
    telegram_chat_id: str | None
    timezone_id: int | None
    gcal_calendar_id: str | None


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    user_id: str
    action: Literal["get", "update"] = "get"
    name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    timezone_id: int | None = None
