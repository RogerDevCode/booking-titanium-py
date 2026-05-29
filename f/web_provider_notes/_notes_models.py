from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class Tag(TypedDict):
    tag_id: str
    name: str
    color: str


class NoteRow(TypedDict):
    note_id: str
    booking_id: str | None
    client_id: str | None
    provider_id: str
    content_encrypted: str | None
    content: str
    encryption_version: int
    created_at: str
    updated_at: str
    tags: list[Tag]


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    provider_id: str
    action: Literal["create", "read", "update", "delete", "list"]
    note_id: str | None = None
    booking_id: str | None = None
    client_id: str | None = None
    content: str | None = Field(None, min_length=1, max_length=5000)
    tag_ids: list[str] = Field(default_factory=list)
