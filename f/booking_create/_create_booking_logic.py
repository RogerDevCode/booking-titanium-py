from datetime import datetime, timedelta

from ..internal._state_machine import validate_transition
from ._booking_create_models import BookingContext, BookingCreated, InputSchema
from ._booking_create_repository import BookingCreateRepository


async def fetch_booking_context(repo: BookingCreateRepository, input_data: InputSchema) -> BookingContext:
    context = await repo.get_booking_context(input_data.client_id, input_data.provider_id, input_data.service_id)
    if not context:
        raise ValueError(
            f"Booking context invalid: client={input_data.client_id}, "
            f"provider={input_data.provider_id}, service={input_data.service_id}"
        )
    return context


async def persist_booking(
    repo: BookingCreateRepository, input_data: InputSchema, context: BookingContext, end_time: datetime
) -> BookingCreated:
    err, _ = validate_transition("pending", "confirmed")
    if err is not None:
        raise RuntimeError(f"Invalid transition: {err}")

    return await repo.insert_booking(
        input_data,
        end_time,
        "confirmed",
        provider_name=context["provider"]["name"],
        service_name=context["service"]["name"],
        client_name=context["client"]["name"],
    )


async def execute_create_booking(repo: BookingCreateRepository, input_data: InputSchema) -> BookingCreated:
    context = await fetch_booking_context(repo, input_data)

    duration_minutes = context["service"]["duration"]
    end_time = input_data.start_time + timedelta(minutes=duration_minutes)

    # BE-02: one active booking per (client, provider) pair
    has_active = await repo.has_active_booking_for_client_provider(input_data.client_id, input_data.provider_id)
    if has_active:
        raise RuntimeError("client_already_has_active_booking_with_provider")

    # RULE 2: no booking at same time slot with any provider
    has_overlap = await repo.has_client_overlap(input_data.client_id, input_data.start_time, end_time)
    if has_overlap:
        raise RuntimeError("client_already_has_booking_at_this_time")

    # Slot overlap for same provider is enforced atomically by the DB GIST exclusion constraint
    return await persist_booking(repo, input_data, context, end_time)
