from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from f.internal.scheduling_engine import TimeSlot


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    tenant_id: str
    provider_id: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    service_id: str | None = None
    duration_minutes: int | None = Field(None, ge=5, le=480)
    buffer_minutes: int | None = Field(None, ge=0, le=120)


class AvailabilityResult(TypedDict):
    provider_id: str
    provider_name: str
    date: str
    timezone: str
    slots: list[TimeSlot]
    total_available: int
    total_booked: int
    is_blocked: bool
    block_reason: str | None


class ProviderRow(TypedDict):
    provider_id: str
    name: str
    timezone: str
