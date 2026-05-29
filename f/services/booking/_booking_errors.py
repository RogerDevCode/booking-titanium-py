from __future__ import annotations


class BookingError(RuntimeError):
    """Base for all booking domain errors. Catch this to handle any booking failure."""


class BookingNotFoundError(BookingError): ...


class BookingAlreadyCancelledError(BookingError): ...


class BookingAlreadyRescheduledError(BookingError): ...


class BookingSlotUnavailableError(BookingError): ...


class BookingPermissionError(BookingError): ...


class BookingClientOverlapError(BookingError):
    """Client already has a booking at the requested time."""


class BookingClientAlreadyActiveError(BookingError):
    """Client already has an active upcoming booking."""


class BookingNoServiceError(BookingError):
    """Provider has no active services configured."""


class BookingMissingParamsError(BookingError):
    """Required parameters are absent."""


class BookingPrefetchBlockedError(BookingError):
    """Prefetch blocked by a business rule (e.g. client already booked)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
