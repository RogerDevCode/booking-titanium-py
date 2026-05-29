from __future__ import annotations

from typing import TYPE_CHECKING

from ..internal._config import DEFAULT_TIMEZONE
from ._reminder_models import BookingRecord, ReminderDispatchDecision

if TYPE_CHECKING:
    from datetime import datetime

    from ..internal._result import DBClient
    from ..reminder_config._config_models import ReminderChannel, ReminderWindow


async def get_candidates_between(db: DBClient, start: datetime, end: datetime) -> list[BookingRecord]:
    rows = await db.fetch(
        f"""
        SELECT
          b.booking_id::text, b.client_id::text, b.provider_id::text,
          b.start_time, b.end_time, b.status,
          cl.telegram_chat_id AS client_telegram_chat_id,
          cl.email AS client_email,
          cl.name AS client_name,
          cl.metadata->'reminder_preferences' AS reminder_preferences,
          pr.name AS provider_name,
          s.name AS service_name,
          COALESCE(tz.name, '{DEFAULT_TIMEZONE}') AS provider_timezone
        FROM bookings b
        JOIN clients cl ON cl.client_id = b.client_id
        LEFT JOIN providers pr ON pr.provider_id = b.provider_id
        LEFT JOIN timezones tz ON tz.id = pr.timezone_id
        LEFT JOIN services s ON s.service_id = b.service_id
        WHERE b.status = 'confirmed'
          AND b.start_time >= $1::timestamptz
          AND b.start_time <= $2::timestamptz
        ORDER BY b.start_time ASC
        """,
        start,
        end,
    )
    return [BookingRecord.model_validate(dict(row)) for row in rows]


async def claim_dispatch(
    db: DBClient,
    booking_id: str,
    channel: ReminderChannel,
    reminder_window: ReminderWindow,
) -> bool:
    row = await db.fetchrow(
        """
        INSERT INTO booking_reminder_dispatches (
            booking_id, reminder_window, channel, status, decided_at, sent_at, skip_reason, last_error
        )
        VALUES ($1::uuid, $2, $3, 'pending', NOW(), NULL, NULL, NULL)
        ON CONFLICT (booking_id, reminder_window, channel) DO NOTHING
        RETURNING booking_id
        """,
        booking_id,
        reminder_window,
        channel,
    )
    return row is not None


async def persist_dispatch_decision(db: DBClient, decision: ReminderDispatchDecision) -> None:
    await db.execute(
        """
        UPDATE booking_reminder_dispatches
        SET status = $1,
            decided_at = NOW(),
            sent_at = $2,
            skip_reason = $3,
            last_error = $4
        WHERE booking_id = $5::uuid
          AND reminder_window = $6
          AND channel = $7
        """,
        decision.status,
        decision.sent_at,
        decision.skip_reason,
        decision.last_error,
        decision.booking_id,
        decision.reminder_window,
        decision.channel,
    )
