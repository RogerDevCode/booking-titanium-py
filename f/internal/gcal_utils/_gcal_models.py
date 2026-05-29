from typing import Literal, TypedDict


class BookingEventData(TypedDict):
    booking_id: str
    status: str
    start_time: str
    end_time: str
    provider_name: str
    service_name: str


class GCalTime(TypedDict):
    dateTime: str
    timeZone: str


class GCalReminderOverride(TypedDict):
    method: Literal["popup", "email"]
    minutes: int


class GCalReminders(TypedDict):
    useDefault: bool
    overrides: list[GCalReminderOverride]


class GoogleCalendarEvent(TypedDict):
    summary: str
    description: str
    start: GCalTime
    end: GCalTime
    status: Literal["confirmed", "cancelled", "tentative"]
    reminders: GCalReminders


class TokenInfo(TypedDict):
    accessToken: str
    clientId: str | None
    clientSecret: str | None
    refreshToken: str | None
