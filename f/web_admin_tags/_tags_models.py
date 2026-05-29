from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class CategoryRow(TypedDict):
    category_id: str
    name: str
    description: str | None
    is_active: bool
    sort_order: int
    created_at: str
    tag_count: int


class TagRow(TypedDict):
    tag_id: str
    category_id: str
    category_name: str
    name: str
    description: str | None
    color: str
    is_active: bool
    sort_order: int
    created_at: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    admin_user_id: str
    action: Literal[
        "list_categories",
        "create_category",
        "update_category",
        "delete_category",
        "activate_category",
        "deactivate_category",
        "list_tags",
        "create_tag",
        "update_tag",
        "delete_tag",
        "activate_tag",
        "deactivate_tag",
        "list_all",
    ]
    category_id: str | None = None
    tag_id: str | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int | None = Field(None, ge=0, le=999)
    is_active: bool | None = None
