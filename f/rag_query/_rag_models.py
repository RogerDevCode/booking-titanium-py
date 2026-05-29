from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class KBEntry(TypedDict):
    kb_id: str
    category: str
    title: str
    content: str
    similarity: float


class RAGResult(TypedDict):
    entries: list[KBEntry]
    count: int
    method: Literal["keyword", "vector", "fts"]


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    category: str | None = None
    provider_id: str


# Note: provider_id is used for RLS context
