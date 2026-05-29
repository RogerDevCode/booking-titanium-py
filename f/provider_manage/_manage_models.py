from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal[
        "create_provider",
        "update_provider",
        "list_providers",
        "create_service",
        "update_service",
        "list_services",
        "set_schedule",
        "remove_schedule",
        "set_override",
        "remove_override",
    ]
    provider_id: str | None = None
    name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    specialty_id: str | None = None
    timezone_id: int | None = None
    is_active: bool | None = None
    service_id: str | None = None
    service_name: str | None = Field(None, max_length=200)
    description: str | None = None
    duration_minutes: int | None = Field(None, ge=5, le=480)
    buffer_minutes: int | None = Field(None, ge=0, le=120)
    price_cents: int | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    day_of_week: int | None = Field(None, ge=0, le=6)
    start_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    override_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    is_blocked: bool | None = None
    override_reason: str | None = None
