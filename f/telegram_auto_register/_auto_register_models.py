from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field


class RegisterResult(TypedDict):
    user_id: str
    client_id: str
    is_new: bool
    name: str
    phone: str | None


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    chat_id: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str | None = None
    username: str | None = None
