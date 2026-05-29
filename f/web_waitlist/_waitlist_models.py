from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict


class WaitlistEntry(TypedDict):
    waitlist_id: str
    service_id: str
    preferred_date: str | None
    preferred_start_time: str | None
    status: str
    position: int
    created_at: str


class WaitlistResult(TypedDict):
    entries: list[WaitlistEntry]
    position: int | None
    message: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["join", "leave", "list", "check_position"]
    user_id: str
    client_id: str | None = None
    service_id: str | None = None
    waitlist_id: str | None = None
    preferred_date: str | None = None
    preferred_start_time: str | None = None
    preferred_end_time: str | None = None
