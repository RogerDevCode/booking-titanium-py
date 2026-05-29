from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict


class TempPasswordResult(TypedDict):
    provider_id: str
    provider_name: str
    tempPassword: str
    expires_at: str
    message: str


class PasswordChangeResult(TypedDict):
    provider_id: str
    message: str


class VerifyResult(TypedDict):
    provider_id: str
    valid: bool
    provider_name: str | None


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    tenant_id: str
    action: Literal["admin_generate_temp", "provider_change", "provider_verify"]
    provider_id: str
    current_password: str | None = None
    new_password: str | None = None
    access_token: str | None = None
