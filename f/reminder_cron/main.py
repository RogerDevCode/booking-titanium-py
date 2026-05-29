# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "email-validator>=2.2.0",
#   "asyncpg>=0.30.0",
#   "cryptography>=48.0.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "redis>=7.4.0",
#   "typing-extensions>=4.12.0"
# ]
# ///
from __future__ import annotations

import asyncio
import traceback

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Process pending reminder dispatches from queue
# DB Tables Used  : bookings, clients, providers, services, booking_reminder_dispatches
# Concurrency Risk: NO — uses FOR UPDATE SKIP LOCKED
# GCal Calls      : NO
# Idempotency Key : YES — status in booking_reminder_dispatches
# RLS Tenant ID   : YES — with_tenant_context wraps each dispatch process
# Pydantic Schemas: YES — InputSchema validates parameters
# ============================================================================
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._wmill_adapter import log
from ._delivery_service import dispatch_reminder
from ._reminder_logic import build_reminder_message, get_client_preference
from ._reminder_models import CronResult, InputSchema, ReminderDispatchDecision
from ._reminder_repository import claim_dispatch, get_candidates_between, persist_dispatch_decision
from ._window_policy import (
    is_due,
    is_quiet_hours,
    offset_window_ranges,
    one_day_candidate_range,
    scheduled_time_for_window,
)

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ..reminder_config._config_models import ReminderChannel, ReminderWindow
    from ._reminder_models import BookingRecord

MODULE = "reminder_cron"


def _channel_recipient(booking: BookingRecord, channel: ReminderChannel) -> str | None:
    if channel == "telegram":
        return booking.client_telegram_chat_id
    return booking.client_email


async def _process_channel(
    booking: BookingRecord,
    window: ReminderWindow,
    channel: ReminderChannel,
    now_utc: datetime,
    dry_run: bool,
    result: CronResult,
    conn: DBClient,
) -> None:
    if not get_client_preference(booking.reminder_preferences, channel, window):
        return

    recipient = _channel_recipient(booking, channel)
    if recipient is None or not recipient.strip():
        return

    claimed = await claim_dispatch(conn, booking.booking_id, channel, window)
    if not claimed:
        return

    scheduled_time = scheduled_time_for_window(booking.start_time, booking.provider_timezone, window)
    if is_quiet_hours(scheduled_time, booking.provider_timezone):
        await persist_dispatch_decision(
            conn,
            ReminderDispatchDecision(
                booking_id=booking.booking_id,
                channel=channel,
                reminder_window=window,
                status="skipped_quiet_hours",
                skip_reason="quiet_hours",
            ),
        )
        result.skipped_quiet_hours += 1
        result.processed_bookings.append(booking.booking_id)
        return

    if dry_run:
        await persist_dispatch_decision(
            conn,
            ReminderDispatchDecision(
                booking_id=booking.booking_id,
                channel=channel,
                reminder_window=window,
                status="sent",
                sent_at=now_utc,
            ),
        )
        result.sent += 1
        result.processed_bookings.append(booking.booking_id)
        return

    try:
        dispatch_reminder(channel, recipient, window, build_reminder_message(booking, window))
    except RuntimeError as dispatch_err:
        await persist_dispatch_decision(
            conn,
            ReminderDispatchDecision(
                booking_id=booking.booking_id,
                channel=channel,
                reminder_window=window,
                status="failed",
                last_error=str(dispatch_err),
            ),
        )
        result.failed += 1
        result.processed_bookings.append(booking.booking_id)
        return

    await persist_dispatch_decision(
        conn,
        ReminderDispatchDecision(
            booking_id=booking.booking_id,
            channel=channel,
            reminder_window=window,
            status="sent",
            sent_at=now_utc,
        ),
    )
    result.sent += 1
    result.processed_bookings.append(booking.booking_id)
    return


async def _process_candidates_for_window(
    conn: DBClient,
    bookings: list[BookingRecord],
    window: ReminderWindow,
    now_utc: datetime,
    dry_run: bool,
    result: CronResult,
) -> None:
    for booking in bookings:
        if window == "1day" and not is_due(now_utc, booking.start_time, booking.provider_timezone, window):
            continue

        for channel in ("telegram", "email"):
            await _process_channel(booking, window, channel, now_utc, dry_run, result, conn)


async def _main_async(args: dict[str, object]) -> CronResult:
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Invalid input: {e}") from e

    conn = await create_db_client()
    try:
        now = datetime.now(UTC)
        result = CronResult(dry_run=input_data.dry_run)

        for window, start, end in offset_window_ranges(now):
            bookings = await get_candidates_between(conn, start, end)
            await _process_candidates_for_window(conn, bookings, window, now, input_data.dry_run, result)

        one_day_start, one_day_end = one_day_candidate_range(now)
        one_day_bookings = await get_candidates_between(conn, one_day_start, one_day_end)
        await _process_candidates_for_window(conn, one_day_bookings, "1day", now, input_data.dry_run, result)

        return result

    except Exception as e:
        log("Unexpected error in reminder_cron", error=str(e), module=MODULE)
        raise RuntimeError(f"Internal error: {e}") from e
    finally:
        await conn.close()


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result: Any = asyncio.run(_main_async(validated.model_dump()))

        if isinstance(result, BaseModel):
            return cast("dict[str, object]", result.model_dump())
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
