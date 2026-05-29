from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BookingCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    client_id: str
    provider_id: str
    service_id: str
    start_time: datetime
    end_time: datetime
    idempotency_key: str
    notes: str | None = None


class BookingCancelRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    booking_id: str
    actor: Literal["client", "provider", "system", "admin"] = "system"
    actor_id: str | None = None
    reason: str = "Cancelled by user"


class BookingRescheduleRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    booking_id: str
    new_start_time: datetime
    new_end_time: datetime
    actor: Literal["client", "provider", "system", "admin"] = "system"
    actor_id: str | None = None


class BookingResult(BaseModel):
    model_config = ConfigDict(strict=True)
    booking_id: str
    status: str
