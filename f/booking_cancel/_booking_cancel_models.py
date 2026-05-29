from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from ..internal._state_machine import BookingStatus


class CancelBookingInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    booking_id: str
    actor: Literal["client", "provider", "system"]
    actor_id: str | None = None
    reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = None


class CancelResult(TypedDict):
    booking_id: str
    previous_status: str
    new_status: str
    cancelled_by: str
    cancellation_reason: str | None


class BookingLookup(TypedDict):
    booking_id: str
    status: BookingStatus
    client_id: str
    provider_id: str
    gcal_provider_event_id: str | None
    gcal_client_event_id: str | None


class UpdatedBooking(TypedDict):
    booking_id: str
    status: str
    cancelled_by: str
    cancellation_reason: str | None
