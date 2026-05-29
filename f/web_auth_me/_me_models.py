from typing import TypedDict

from pydantic import BaseModel, ConfigDict


class UserProfileResult(TypedDict):
    user_id: str
    email: str | None
    full_name: str
    role: str
    rut: str | None
    phone: str | None
    address: str | None
    telegram_chat_id: str | None
    timezone: str
    is_active: bool
    profile_complete: bool
    last_login: str | None


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    user_id: str
