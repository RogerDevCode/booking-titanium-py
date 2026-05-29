from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class LogResult(TypedDict):
    message_id: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    client_id: str | None = None
    provider_id: str
    channel: Literal["telegram", "web", "api"]
    direction: Literal["incoming", "outgoing"]
    content: str = Field(min_length=1, max_length=2000)
    intent: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
