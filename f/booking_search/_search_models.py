from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class SearchInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    provider_id: str | None = None
    client_id: str | None = None
    status: Literal["pending", "confirmed", "in_service", "completed", "cancelled", "no_show", "rescheduled"] | None = (
        None
    )
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    service_id: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class BookingSearchRow(TypedDict):
    booking_id: str
    start_time: str
    end_time: str
    status: str
    provider_name: str
    client_name: str
    service_name: str
    gcal_sync_status: str
    notification_sent: bool


class BookingSearchResult(TypedDict):
    bookings: list[BookingSearchRow]
    total: int
    offset: int
    limit: int
