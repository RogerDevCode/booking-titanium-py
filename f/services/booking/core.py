from __future__ import annotations

from typing import TYPE_CHECKING

from ._booking_errors import (
    BookingAlreadyCancelledError,
    BookingAlreadyRescheduledError,
    BookingNotFoundError,
    BookingPermissionError,
)
from ._booking_models import (
    BookingCancelRequest,
    BookingCreateRequest,
    BookingRescheduleRequest,
    BookingResult,
)

if TYPE_CHECKING:
    from .repo import BookingRepo


async def create_booking(
    req: BookingCreateRequest,
    repo: BookingRepo,
) -> BookingResult:
    if await repo.exists(req.idempotency_key):
        existing = await repo.get_by_key(req.idempotency_key)
        return BookingResult(booking_id=existing["booking_id"], status=existing["status"])

    data = req.model_dump()
    # GIST exclusion constraint in repo handles slot conflicts atomically.
    # calendar.sync / notifier.send are enqueued via outbox (gcal_sync_status column).
    booking = await repo.insert(data)
    return BookingResult(booking_id=booking["booking_id"], status=booking["status"])


async def cancel_booking(
    req: BookingCancelRequest,
    repo: BookingRepo,
) -> BookingResult:
    booking = await repo.get_booking(req.booking_id)
    if not booking:
        raise BookingNotFoundError(f"Booking {req.booking_id!r} not found")

    if booking["status"] == "cancelled":
        raise BookingAlreadyCancelledError(f"Booking {req.booking_id!r} is already cancelled")

    if req.actor == "client" and req.actor_id and str(req.actor_id) != str(booking.get("client_id", "")):
        raise BookingPermissionError(f"Client {req.actor_id} cannot cancel another client's booking")

    updated = await repo.update_status(req.booking_id, "cancelled", req.actor_id, req.reason, str(req.actor))
    # calendar.sync / notifier.send enqueued via outbox.
    return BookingResult(booking_id=updated["booking_id"], status=updated["status"])


async def reschedule_booking(
    req: BookingRescheduleRequest,
    repo: BookingRepo,
) -> BookingResult:
    old_booking = await repo.get_booking(req.booking_id)
    if not old_booking:
        raise BookingNotFoundError(f"Booking {req.booking_id!r} not found")

    if old_booking["status"] == "cancelled":
        raise BookingAlreadyCancelledError(f"Booking {req.booking_id!r} is already cancelled")
    if old_booking["status"] == "rescheduled":
        raise BookingAlreadyRescheduledError(f"Booking {req.booking_id!r} is already rescheduled")

    if req.actor == "client" and req.actor_id and str(req.actor_id) != str(old_booking.get("client_id", "")):
        raise BookingPermissionError(f"Client {req.actor_id} cannot reschedule another client's booking")

    new_data = {
        "client_id": old_booking["client_id"],
        "provider_id": old_booking["provider_id"],
        "service_id": old_booking["service_id"],
        "start_time": req.new_start_time,
        "end_time": req.new_end_time,
        "idempotency_key": f"reschedule-{req.booking_id}-{req.new_start_time.isoformat()}",
        "actor_id": req.actor_id,
        "actor_type": str(req.actor),
    }

    # GIST exclusion constraint in repo handles slot conflicts atomically.
    # calendar.sync / notifier.send enqueued via outbox.
    result = await repo.reschedule(req.booking_id, new_data)
    return BookingResult(booking_id=result["booking_id"], status=result["status"])
