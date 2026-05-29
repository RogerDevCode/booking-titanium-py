from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from f.internal._config import DEFAULT_TIMEZONE

from ..reminder_config._config_models import (  # noqa: TC001
    InlineButton,
    ReminderChannel,
    ReminderPreferences,
    ReminderWindow,
)

DispatchStatus = Literal["pending", "sent", "skipped_quiet_hours", "failed"]


class BookingDetails(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    date: str
    time: str
    provider_name: str
    service: str
    booking_id: str
    client_name: str


class BookingRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    booking_id: str
    client_id: str
    provider_id: str
    start_time: datetime
    end_time: datetime
    status: str
    client_telegram_chat_id: str | None = None
    client_email: str | None = None
    client_name: str | None = None
    provider_name: str | None = None
    service_name: str | None = None
    provider_timezone: str
    reminder_preferences: ReminderPreferences | None = None


class ReminderDispatchRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    booking_id: str
    channel: ReminderChannel
    reminder_window: ReminderWindow
    status: DispatchStatus
    decided_at: datetime
    sent_at: datetime | None = None
    skip_reason: str | None = None
    last_error: str | None = None


class ReminderDispatchDecision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    booking_id: str
    channel: ReminderChannel
    reminder_window: ReminderWindow
    status: DispatchStatus
    sent_at: datetime | None = None
    skip_reason: str | None = None
    last_error: str | None = None


class ReminderMessage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: str
    inline_buttons: list[list[InlineButton]]
    booking_details: BookingDetails


class CronResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    sent: int = 0
    failed: int = 0
    skipped_quiet_hours: int = 0
    processed_bookings: list[str] = Field(default_factory=list)
    dry_run: bool = False


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    dry_run: bool = False
    timezone: str = DEFAULT_TIMEZONE
