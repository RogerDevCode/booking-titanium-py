from typing import TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from f.internal._config import DEFAULT_TIMEZONE


class CompleteProfileResult(TypedDict):
    user_id: str
    full_name: str
    email: str
    rut: str
    role: str


class UserRow(TypedDict):
    user_id: str
    full_name: str
    email: str | None
    rut: str | None
    role: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    chat_id: str = Field(min_length=1)
    rut: str = Field(min_length=1, max_length=12)
    email: EmailStr
    address: str = Field(min_length=1, max_length=300)
    phone: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)
    timezone: str = DEFAULT_TIMEZONE
