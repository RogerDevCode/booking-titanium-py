from typing import TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from f.internal._config import DEFAULT_TIMEZONE


class RegisterResult(TypedDict):
    user_id: str
    email: str
    full_name: str
    role: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    full_name: str = Field(min_length=3, max_length=200)
    rut: str = Field(min_length=1, max_length=12)
    email: EmailStr
    address: str = Field(min_length=1, max_length=300)
    phone: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)
    timezone: str = DEFAULT_TIMEZONE
