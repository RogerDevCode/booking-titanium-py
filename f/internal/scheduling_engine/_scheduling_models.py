from typing import TypedDict


class TimeSlot(TypedDict):
    start: str
    end: str
    available: bool


class AvailabilityQuery(TypedDict):
    provider_id: str
    date: str
    service_id: str


class AvailabilityResult(TypedDict):
    provider_id: str
    date: str
    timezone: str
    slots: list[TimeSlot]
    total_available: int
    total_booked: int
    is_blocked: bool
    block_reason: str | None


class ScheduleOverrideRow(TypedDict):
    override_id: str
    provider_id: str
    override_date: str
    is_blocked: bool
    start_time: str | None
    end_time: str | None
    reason: str | None


class ProviderScheduleRow(TypedDict):
    id: int
    provider_id: str
    day_of_week: int
    start_time: str
    end_time: str


class BookingTimeRow(TypedDict):
    start_time: str
    end_time: str


class ServiceRow(TypedDict):
    service_id: str
    duration_minutes: int
    buffer_minutes: int


class AffectedBooking(TypedDict):
    booking_id: str
    start_time: str
    client_name: str


class OverrideValidation(TypedDict):
    hasBookings: bool
    bookingCount: int
    affectedBookings: list[AffectedBooking]
