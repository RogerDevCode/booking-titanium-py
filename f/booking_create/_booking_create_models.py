from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    client_id: str
    provider_id: str
    service_id: str
    start_time: datetime
    idempotency_key: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=500)
    actor: Literal["client", "provider", "system"] = "client"
    channel: Literal["telegram", "web", "api"] = "api"

    @field_validator("start_time", mode="before")
    @classmethod
    def parse_datetime(cls, v: object) -> datetime | object:
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return v
        return v


class BookingCreated(TypedDict):
    booking_id: str
    status: str
    start_time: str
    end_time: str
    provider_name: str
    service_name: str
    client_name: str


class ClientContext(TypedDict):
    id: str
    name: str


class ProviderContext(TypedDict):
    id: str
    name: str


class ServiceContext(TypedDict):
    id: str
    name: str
    duration: int


class BookingContext(TypedDict):
    client: ClientContext
    provider: ProviderContext
    service: ServiceContext
