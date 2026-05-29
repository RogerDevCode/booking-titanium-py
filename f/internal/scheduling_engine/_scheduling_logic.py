from __future__ import annotations

import zoneinfo
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, cast

from .._wmill_adapter import log

if TYPE_CHECKING:
    from .._result import DBClient
from ._scheduling_models import (
    AffectedBooking,
    AvailabilityQuery,
    AvailabilityResult,
    BookingTimeRow,
    OverrideValidation,
    ProviderScheduleRow,
    ScheduleOverrideRow,
    ServiceRow,
    TimeSlot,
)


def time_to_minutes(time_str: str) -> int:
    """Converts HH:MM[:SS] to minutes from start of day."""
    parts = time_str.split(":")
    hours = int(parts[0]) if len(parts) > 0 else 0
    minutes = int(parts[1]) if len(parts) > 1 else 0
    return hours * 60 + minutes


def generate_slots_for_rule(
    rule: ProviderScheduleRow,
    target_date: str,
    slot_duration_min: int,
    bookings: list[BookingTimeRow],
    timezone_name: str = "UTC",
    slot_spacing_min: int | None = None,
    cutoff_utc: datetime | None = None,
) -> list[TimeSlot]:
    """
    slot_duration_min: actual service duration (used for end_time and overlap check).
    slot_spacing_min:  advance between slot starts = duration + buffer. Defaults to duration.
    """
    spacing = slot_spacing_min if slot_spacing_min is not None else slot_duration_min
    slots: list[TimeSlot] = []
    start_min = time_to_minutes(rule["start_time"])
    end_min = time_to_minutes(rule["end_time"])

    # Parse target date
    try:
        y, m, d = map(int, target_date.split("-"))
    except (ValueError, AttributeError):
        return []

    # Prepare booking ranges as (start_ts, end_ts) for faster lookup
    booking_ranges: list[tuple[float, float]] = []
    for b in bookings:
        b_start_dt = datetime.fromisoformat(b["start_time"].replace("Z", "+00:00"))
        b_end_dt = datetime.fromisoformat(b["end_time"].replace("Z", "+00:00"))
        booking_ranges.append((b_start_dt.timestamp(), b_end_dt.timestamp()))

    tz = zoneinfo.ZoneInfo(timezone_name)
    current_min = start_min
    while current_min + slot_duration_min <= end_min:
        slot_start_dt = datetime(y, m, d, current_min // 60, current_min % 60, tzinfo=tz)
        slot_end_dt = slot_start_dt + timedelta(minutes=slot_duration_min)

        slot_start_ts = slot_start_dt.timestamp()
        slot_end_ts = slot_end_dt.timestamp()

        is_booked = any(slot_start_ts < b_end and slot_end_ts > b_start for b_start, b_end in booking_ranges)

        start_utc = slot_start_dt.astimezone(UTC)
        end_utc = slot_end_dt.astimezone(UTC)

        if cutoff_utc and start_utc <= cutoff_utc:
            current_min += spacing
            continue

        slots.append(
            {
                "start": start_utc.isoformat().replace("+00:00", "Z"),
                "end": end_utc.isoformat().replace("+00:00", "Z"),
                "available": not is_booked,
            }
        )

        current_min += spacing

    return slots


async def get_availability(db: DBClient, query: AvailabilityQuery) -> AvailabilityResult:
    target_date = query["date"]

    try:
        # Determine day of week (0=Sun, ..., 6=Sat) to match Postgres
        dt = datetime.fromisoformat(target_date)
        dt_date = dt.date()  # asyncpg requires date objects, not strings, for ::date params
        day_of_week = dt.isoweekday() % 7

        # 1. Layer 2: Overrides
        override_rows = await db.fetch(
            """
            SELECT override_id, provider_id, override_date, is_blocked,
                   start_time::text, end_time::text, reason
            FROM schedule_overrides
            WHERE provider_id = $1::uuid
              AND override_date = $2
            """,
            query["provider_id"],
            dt_date,
        )

        overrides = cast("list[ScheduleOverrideRow]", override_rows)
        blocking_override = next((o for o in overrides if o["is_blocked"]), None)

        if blocking_override:
            return AvailabilityResult(
                provider_id=query["provider_id"],
                date=target_date,
                timezone="UTC",
                slots=[],
                total_available=0,
                total_booked=0,
                is_blocked=True,
                block_reason=blocking_override["reason"] or "Día no disponible",
            )

        special_override = next(
            (o for o in overrides if not o["is_blocked"] and o["start_time"] and o["end_time"]), None
        )

        # 2. Layer 1: Schedule Rules
        rules: list[ProviderScheduleRow]
        if special_override:
            rules = [
                {
                    "id": 0,
                    "provider_id": query["provider_id"],
                    "day_of_week": day_of_week,
                    "start_time": cast("str", special_override["start_time"]),
                    "end_time": cast("str", special_override["end_time"]),
                }
            ]
        else:
            rule_rows = await db.fetch(
                """
                SELECT id, provider_id, day_of_week,
                       start_time::text, end_time::text
                FROM provider_schedules
                WHERE provider_id = $1::uuid
                  AND day_of_week = $2
                """,
                query["provider_id"],
                day_of_week,
            )
            rules = cast("list[ProviderScheduleRow]", rule_rows)

        if not rules:
            return AvailabilityResult(
                provider_id=query["provider_id"],
                date=target_date,
                timezone="UTC",
                slots=[],
                total_available=0,
                total_booked=0,
                is_blocked=True,
                block_reason="No hay horario para este día de la semana",
            )

        # 3. Layer 3: Bookings
        booking_rows = await db.fetch(
            """
            SELECT start_time::text, end_time::text FROM bookings
            WHERE provider_id = $1::uuid
              AND start_time >= $2
              AND start_time < ($2 + INTERVAL '1 day')
              AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
            """,
            query["provider_id"],
            dt_date,
        )
        bookings = cast("list[BookingTimeRow]", booking_rows)

        # 4. Provider timezone and UI preferences
        tz_rows = await db.fetch(
            """
            SELECT t.name as tz_name, p.ui_preferences
            FROM providers p
            LEFT JOIN timezones t ON t.id = p.timezone_id
            WHERE p.provider_id = $1::uuid
            LIMIT 1
            """,
            query["provider_id"],
        )
        provider_tz = str(tz_rows[0]["tz_name"]) if tz_rows and tz_rows[0]["tz_name"] else "UTC"

        advance_notice_minutes = 0
        if tz_rows and tz_rows[0].get("ui_preferences"):
            prefs = tz_rows[0]["ui_preferences"]
            if isinstance(prefs, dict):
                d = cast("dict[str, object]", prefs)
                advance_notice_minutes = int(str(d.get("advance_notice_minutes", 0)))

        # 5. Service details
        service_rows = await db.fetch(
            "SELECT service_id, duration_minutes, buffer_minutes FROM services WHERE service_id = $1::uuid LIMIT 1",
            query["service_id"],
        )
        if not service_rows:
            raise RuntimeError(f"Service not found: {query['service_id']}")

        service = cast("ServiceRow", service_rows[0])
        slot_duration = service["duration_minutes"]
        slot_spacing = slot_duration + service["buffer_minutes"]

        # 6. Generate slots using provider's local timezone
        cutoff_utc = datetime.now(UTC) + timedelta(minutes=advance_notice_minutes)

        all_slots: list[TimeSlot] = []
        for rule in rules:
            rule_slots = generate_slots_for_rule(
                rule, target_date, slot_duration, bookings, provider_tz, slot_spacing, cutoff_utc
            )
            all_slots.extend(rule_slots)

        available_count = len([s for s in all_slots if s["available"]])
        booked_count = len(all_slots) - available_count

        return AvailabilityResult(
            provider_id=query["provider_id"],
            date=target_date,
            timezone=provider_tz,
            slots=all_slots,
            total_available=available_count,
            total_booked=booked_count,
            is_blocked=False,
            block_reason=None,
        )

    except Exception as e:
        import traceback

        log("GET_AVAILABILITY_CRITICAL_ERROR", error=str(e), traceback=traceback.format_exc())
        raise RuntimeError(f"get_availability failed: {e}") from e


async def get_availability_range(
    db: DBClient, provider_id: str, service_id: str, date_from: str, date_to: str
) -> list[AvailabilityResult]:
    try:
        curr_dt = date.fromisoformat(date_from)
        end_dt = date.fromisoformat(date_to)
    except ValueError as e:
        log("GET_AVAILABILITY_RANGE_DATE_ERROR", error=str(e))
        raise RuntimeError(f"Invalid date format: {e}") from e

    # 1. Fetch provider details (timezone and preferences)
    tz_rows = await db.fetch(
        """
        SELECT t.name as tz_name, p.ui_preferences
        FROM providers p
        LEFT JOIN timezones t ON t.id = p.timezone_id
        WHERE p.provider_id = $1::uuid
        LIMIT 1
        """,
        provider_id,
    )
    provider_tz = str(tz_rows[0]["tz_name"]) if tz_rows and tz_rows[0]["tz_name"] else "UTC"

    advance_notice_minutes = 0
    if tz_rows and tz_rows[0].get("ui_preferences"):
        prefs = tz_rows[0]["ui_preferences"]
        if isinstance(prefs, dict):
            d = cast("dict[str, object]", prefs)
            advance_notice_minutes = int(str(d.get("advance_notice_minutes", 0)))

    # 2. Fetch service details
    service_rows = await db.fetch(
        "SELECT service_id, duration_minutes, buffer_minutes FROM services WHERE service_id = $1::uuid LIMIT 1",
        service_id,
    )
    if not service_rows:
        raise RuntimeError(f"Service not found: {service_id}")

    service = cast("ServiceRow", service_rows[0])
    slot_duration = service["duration_minutes"]
    slot_spacing = slot_duration + service["buffer_minutes"]

    # 3. Fetch overrides for range
    override_rows = await db.fetch(
        """
        SELECT override_id, provider_id, override_date, is_blocked,
               start_time::text, end_time::text, reason
        FROM schedule_overrides
        WHERE provider_id = $1::uuid
          AND override_date >= $2::date
          AND override_date <= $3::date
        """,
        provider_id,
        curr_dt,
        end_dt,
    )
    overrides_list = cast("list[ScheduleOverrideRow]", override_rows)

    # Map overrides by date string
    overrides_by_date: dict[str, list[ScheduleOverrideRow]] = {}
    for o in overrides_list:
        od = o["override_date"]
        od_str = od.isoformat() if isinstance(od, date) else str(od)
        overrides_by_date.setdefault(od_str, []).append(o)

    # 4. Fetch schedule rules
    rule_rows = await db.fetch(
        """
        SELECT id, provider_id, day_of_week,
               start_time::text, end_time::text
        FROM provider_schedules
        WHERE provider_id = $1::uuid
        """,
        provider_id,
    )
    rules_list = cast("list[ProviderScheduleRow]", rule_rows)
    rules_by_day: dict[int, list[ProviderScheduleRow]] = {}
    for r in rules_list:
        rules_by_day.setdefault(r["day_of_week"], []).append(r)

    # 5. Fetch bookings in range
    booking_rows = await db.fetch(
        """
        SELECT start_time::text, end_time::text FROM bookings
        WHERE provider_id = $1::uuid
          AND start_time >= $2::date
          AND start_time < ($3::date + INTERVAL '1 day')
          AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
        """,
        provider_id,
        curr_dt,
        end_dt,
    )
    bookings = cast("list[BookingTimeRow]", booking_rows)

    cutoff_utc = datetime.now(UTC) + timedelta(minutes=advance_notice_minutes)

    results: list[AvailabilityResult] = []
    iter_date = curr_dt
    while iter_date <= end_dt:
        date_str = iter_date.isoformat()
        day_of_week = iter_date.isoweekday() % 7

        # Check overrides for this day
        day_overrides = overrides_by_date.get(date_str, [])
        blocking_override = next((o for o in day_overrides if o["is_blocked"]), None)

        if blocking_override:
            results.append(
                AvailabilityResult(
                    provider_id=provider_id,
                    date=date_str,
                    timezone="UTC",
                    slots=[],
                    total_available=0,
                    total_booked=0,
                    is_blocked=True,
                    block_reason=blocking_override["reason"] or "Día no disponible",
                )
            )
            iter_date += timedelta(days=1)
            continue

        special_override = next(
            (o for o in day_overrides if not o["is_blocked"] and o["start_time"] and o["end_time"]), None
        )

        day_rules: list[ProviderScheduleRow]
        if special_override:
            day_rules = [
                {
                    "id": 0,
                    "provider_id": provider_id,
                    "day_of_week": day_of_week,
                    "start_time": cast("str", special_override["start_time"]),
                    "end_time": cast("str", special_override["end_time"]),
                }
            ]
        else:
            day_rules = rules_by_day.get(day_of_week, [])

        if not day_rules:
            results.append(
                AvailabilityResult(
                    provider_id=provider_id,
                    date=date_str,
                    timezone="UTC",
                    slots=[],
                    total_available=0,
                    total_booked=0,
                    is_blocked=True,
                    block_reason="No hay horario para este día de la semana",
                )
            )
            iter_date += timedelta(days=1)
            continue

        all_slots: list[TimeSlot] = []
        for rule in day_rules:
            rule_slots = generate_slots_for_rule(
                rule, date_str, slot_duration, bookings, provider_tz, slot_spacing, cutoff_utc
            )
            all_slots.extend(rule_slots)

        available_count = len([s for s in all_slots if s["available"]])
        booked_count = len(all_slots) - available_count

        results.append(
            AvailabilityResult(
                provider_id=provider_id,
                date=date_str,
                timezone=provider_tz,
                slots=all_slots,
                total_available=available_count,
                total_booked=booked_count,
                is_blocked=False,
                block_reason=None,
            )
        )

        iter_date += timedelta(days=1)

    return results


async def validate_override(db: DBClient, provider_id: str, date_start: str, date_end: str) -> OverrideValidation:
    try:
        rows = await db.fetch(
            """
            SELECT b.booking_id, b.start_time, p.name as client_name
            FROM bookings b
            JOIN clients p ON p.client_id = b.client_id
            WHERE b.provider_id = $1::uuid
              AND b.start_time >= $2::date
              AND b.start_time < ($3::date + INTERVAL '1 day')
              AND b.status NOT IN ('cancelled', 'no_show', 'rescheduled')
            """,
            provider_id,
            date_start,
            date_end,
        )

        affected: list[AffectedBooking] = [
            {
                "booking_id": str(r["booking_id"]),
                "start_time": r["start_time"].isoformat()
                if isinstance(r["start_time"], datetime)
                else str(r["start_time"]),
                "client_name": str(r["client_name"]),
            }
            for r in rows
        ]

        return OverrideValidation(
            hasBookings=len(affected) > 0,
            bookingCount=len(affected),
            affectedBookings=affected,
        )
    except Exception as e:
        import traceback

        log("VALIDATE_OVERRIDE_ERROR", error=str(e), traceback=traceback.format_exc())
        raise RuntimeError(f"validate_override failed: {e}") from e
