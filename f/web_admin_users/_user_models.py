from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserInfo(TypedDict):
    full_name: str
    email: str | None
    rut: str | None
    phone: str | None
    role: str
    is_active: bool
    telegram_chat_id: str | None
    last_login: str | None
    created_at: str


class UsersListResult(TypedDict):
    users: list[UserInfo]
    total: int


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    access_token: str
    action: Literal["list", "get", "update", "deactivate", "activate"]
    target_user_id: str | None = None
    full_name: str | None = Field(None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    role: Literal["admin", "provider", "client"] | None = None
