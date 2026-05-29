from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class SpecialtyRow(TypedDict):
    specialty_id: str
    name: str
    description: str | None
    category: str | None
    is_active: bool
    sort_order: int
    created_at: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    admin_user_id: str
    action: Literal["list", "create", "update", "delete", "activate", "deactivate"]
    specialty_id: str | None = None
    name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = Field(None, max_length=500)
    category: str | None = Field(None, max_length=50)
    sort_order: int | None = Field(None, ge=0, le=999)
