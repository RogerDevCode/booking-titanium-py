from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InlineButton(BaseModel):
    model_config = ConfigDict(strict=True)
    text: str
    callback_data: str


class MenuInput(BaseModel):
    model_config = ConfigDict(strict=True)
    action: str
    chat_id: str
    user_input: str | None = None


class MenuResponse(BaseModel):
    model_config = ConfigDict(strict=True)
    handled: bool
    response_text: str
    inline_buttons: list[list[dict[str, str]]] = Field(default_factory=list[list[dict[str, str]]])


class InputSchema(MenuInput):
    pass


class MenuResult(MenuResponse):
    pass
