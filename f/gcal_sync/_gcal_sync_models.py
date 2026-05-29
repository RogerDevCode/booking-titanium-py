from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from f.internal.gcal_utils import BookingEventData


class GCalSyncResult(TypedDict):
    booking_id: str
    provider_event_id: str | None
    client_event_id: str | None
    sync_status: Literal["synced", "partial", "pending"]
    retry_count: int
    errors: list[str]


class BookingDetails(BookingEventData):
    provider_id: str
    gcal_provider_event_id: str | None
    gcal_client_event_id: str | None
    provider_calendar_id: str | None
    provider_gcal_access_token: str | None
    provider_gcal_refresh_token: str | None
    provider_gcal_client_id: str | None
    provider_gcal_client_secret: str | None
    client_calendar_id: str | None


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    booking_id: str
    action: Literal["create", "update", "delete"] = "create"
    max_retries: int = Field(default=3, ge=1, le=5)
    tenant_id: str
