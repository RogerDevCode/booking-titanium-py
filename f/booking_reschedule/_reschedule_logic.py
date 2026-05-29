from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._reschedule_models import BookingRow, RescheduleInput, RescheduleWriteResult, ServiceRow
    from ._reschedule_repository import RescheduleRepository


class RescheduleBookingError(RuntimeError): ...


def authorize(input_data: RescheduleInput, old_booking: BookingRow) -> None:
    if input_data.actor == "client" and old_booking["client_id"] != input_data.actor_id:
        raise RescheduleBookingError("unauthorized: client_id mismatch")

    if input_data.actor == "provider" and old_booking["provider_id"] != input_data.actor_id:
        raise RescheduleBookingError("unauthorized: provider_id mismatch")


async def execute_reschedule_logic(
    repo: RescheduleRepository, input_data: RescheduleInput, old_booking: BookingRow, service: ServiceRow
) -> RescheduleWriteResult:
    new_start = input_data.new_start_time
    new_end = new_start + timedelta(minutes=service["duration_minutes"])

    # Deterministic idempotency key
    new_key = f"reschedule-{old_booking['booking_id']}-{new_start.isoformat()}"

    overlap = await repo.check_overlap(old_booking["provider_id"], old_booking["booking_id"], new_start, new_end)
    if overlap:
        raise RescheduleBookingError("new_time_slot_already_booked")

    client_overlap = await repo.check_client_overlap(
        old_booking["client_id"], old_booking["booking_id"], new_start, new_end
    )
    if client_overlap:
        raise RescheduleBookingError("client_already_has_booking_at_this_time")

    write_result = await repo.execute_reschedule(input_data, old_booking, service, new_end, new_key)
    if not write_result:
        raise RescheduleBookingError("failed_to_execute_reschedule_transaction")

    return write_result
