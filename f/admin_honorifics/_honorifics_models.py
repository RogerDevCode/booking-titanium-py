from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class HonorificRow(TypedDict):
    """Represents a database row for an honorific."""

    honorific_id: str
    code: str
    label: str
    gender: str | None
    sort_order: int
    is_active: bool
    created_at: str


class InputSchema(BaseModel):
    """Validation schema for honorifics CRUD actions."""

    model_config = ConfigDict(strict=True, extra="forbid")

    tenant_id: str
    action: Literal["list", "create", "update", "delete"]
    honorific_id: str | None = None
    code: str | None = Field(None, max_length=10)
    label: str | None = Field(None, max_length=10)
    gender: Literal["M", "F", "N"] | None = None
    sort_order: int | None = Field(None, ge=0, le=999)
    is_active: bool | None = None
