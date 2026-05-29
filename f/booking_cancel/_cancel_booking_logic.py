from __future__ import annotations

from typing import TYPE_CHECKING

from ..internal._state_machine import validate_transition

if TYPE_CHECKING:
    from ._booking_cancel_models import BookingLookup, CancelBookingInput, UpdatedBooking
    from ._booking_cancel_repository import BookingCancelRepository


class CancelBookingError(RuntimeError): ...


def authorize_actor(input_data: CancelBookingInput, booking: BookingLookup) -> None:
    if input_data.actor == "client" and booking["client_id"] != input_data.actor_id:
        raise CancelBookingError("unauthorized: client_id mismatch")

    if input_data.actor == "provider" and booking["provider_id"] != input_data.actor_id:
        raise CancelBookingError("unauthorized: provider_id mismatch")


async def execute_cancel_booking(
    repo: BookingCancelRepository, input_data: CancelBookingInput, booking: BookingLookup
) -> UpdatedBooking:
    current_status = await repo.lock_booking(input_data.booking_id)
    if not current_status:
        raise CancelBookingError("booking_lost_during_transaction")

    if current_status == "cancelled":
        raise CancelBookingError("booking_already_cancelled")

    err_trans, _ = validate_transition(current_status, "cancelled")
    if err_trans is not None:
        raise CancelBookingError(f"invalid_transition: {err_trans}")

    updated = await repo.update_booking_status(input_data)
    if not updated:
        raise CancelBookingError("failed_to_update_booking_status")

    await repo.insert_audit_trail(input_data, booking)

    # Side Effects: GCal Sync — failure here is logged but does not block cancellation
    try:
        if booking.get("gcal_provider_event_id") or booking.get("gcal_client_event_id"):
            await repo.trigger_gcal_sync(input_data.booking_id)
    except Exception as e:
        from ..internal._wmill_adapter import log

        log("GCAL_SYNC_TRIGGER_FAILED", error=str(e), booking_id=input_data.booking_id)

    return updated
