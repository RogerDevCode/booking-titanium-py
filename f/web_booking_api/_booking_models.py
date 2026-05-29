from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class BookingResult(TypedDict):
    booking_id: str
    status: str
    message: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["crear", "cancelar", "reagendar"]
    user_id: str
    booking_id: str | None = None
    provider_id: str | None = None
    service_id: str | None = None
    start_time: str | None = None
    cancellation_reason: str | None = Field(None, max_length=500)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)
