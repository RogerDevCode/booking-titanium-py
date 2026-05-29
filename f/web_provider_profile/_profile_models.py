from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ProfileRow(TypedDict):
    id: str
    name: str
    email: str
    honorific_label: str | None
    specialty_name: str | None
    timezone_name: str | None
    phone_app: str | None
    phone_contact: str | None
    telegram_chat_id: str | None
    gcal_calendar_id: str | None
    address_street: str | None
    address_number: str | None
    address_complement: str | None
    address_sector: str | None
    region_name: str | None
    commune_name: str | None
    is_active: bool
    has_password: bool
    last_password_change: str | None


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["get_profile", "update_profile", "change_password"]
    provider_id: str
    name: str | None = Field(None, min_length=2, max_length=200)
    email: EmailStr | None = None
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
    current_password: str | None = None
    new_password: str | None = None
