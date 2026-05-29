from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ProviderRow(TypedDict):
    id: str
    honorific_id: str | None
    name: str
    email: str
    specialty_id: str | None
    timezone_id: int | None
    phone_app: str | None
    phone_contact: str | None
    telegram_chat_id: str | None
    gcal_calendar_id: str | None
    address_street: str | None
    address_number: str | None
    address_complement: str | None
    address_sector: str | None
    region_id: int | None
    commune_id: int | None
    is_active: bool
    has_password: bool
    last_password_change: str | None
    created_at: str
    updated_at: str
    honorific_label: str | None
    specialty_name: str | None
    timezone_name: str | None
    region_name: str | None
    commune_name: str | None


class CreateProviderResult(ProviderRow):
    temp_password: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["list", "create", "update", "activate", "deactivate", "reset_password"]
    provider_id: str | None = None
    name: str | None = Field(None, min_length=2, max_length=200)
    email: EmailStr | None = None
    specialty_id: str | None = None
    honorific_id: str | None = None
    timezone_id: int | None = None
    phone_app: str | None = Field(None, max_length=20)
    phone_contact: str | None = Field(None, max_length=20)
    telegram_chat_id: str | None = Field(None, max_length=100)
    gcal_calendar_id: str | None = Field(None, max_length=500)
    address_street: str | None = Field(None, max_length=300)
    address_number: str | None = Field(None, max_length=20)
    address_complement: str | None = Field(None, max_length=200)
    address_sector: str | None = Field(None, max_length=200)
    region_id: int | None = None
    commune_id: int | None = None
    is_active: bool | None = None
