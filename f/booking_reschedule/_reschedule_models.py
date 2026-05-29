from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from ..internal._state_machine import BookingStatus


class RescheduleInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    booking_id: str
    new_start_time: datetime
    new_service_id: str | None = None
    actor: Literal["client", "provider", "system"]
    actor_id: str | None = None
    reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = None

    @field_validator("new_start_time", mode="before")
    @classmethod
    def parse_datetime(cls, v: object) -> datetime | object:
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return v
        return v


class RescheduleResult(TypedDict):
    old_booking_id: str
    new_booking_id: str
    old_status: str
    new_status: str
    old_start_time: str
    new_start_time: str
    new_end_time: str


class RescheduleWriteResult(TypedDict):
    new_booking_id: str
    new_status: str
    new_start_time: str
    new_end_time: str
    old_booking_id: str
    old_status: str


class BookingRow(TypedDict):
    booking_id: str
    provider_id: str
    client_id: str
    service_id: str
    status: BookingStatus
    start_time: datetime
    end_time: datetime
    idempotency_key: str


class ServiceRow(TypedDict):
    service_id: str
    duration_minutes: int
