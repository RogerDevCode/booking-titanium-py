from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict


class ChangeRoleResult(TypedDict):
    user_id: str
    full_name: str
    old_role: str
    new_role: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    admin_user_id: str
    target_user_id: str
    new_role: Literal["client", "provider", "admin"]
