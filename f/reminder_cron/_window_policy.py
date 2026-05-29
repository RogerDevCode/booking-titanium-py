from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from ..reminder_config._config_models import ReminderWindow  # noqa: TC001

_OFFSET_WINDOWS: Final[dict[ReminderWindow, tuple[timedelta, timedelta, timedelta]]] = {
    "24h": (timedelta(hours=24), timedelta(hours=23), timedelta(hours=25)),
    "12h": (timedelta(hours=12), timedelta(hours=11, minutes=30), timedelta(hours=12, minutes=30)),
    "6h": (timedelta(hours=6), timedelta(hours=5, minutes=30), timedelta(hours=6, minutes=30)),
    "2h": (timedelta(hours=2), timedelta(hours=1, minutes=50), timedelta(hours=2, minutes=10)),
    "1h": (timedelta(hours=1), timedelta(minutes=50), timedelta(hours=1, minutes=10)),
    "30min": (timedelta(minutes=30), timedelta(minutes=25), timedelta(minutes=35)),
}
_ONE_DAY_TOLERANCE: Final[timedelta] = timedelta(minutes=15)


def offset_window_ranges(now_utc: datetime) -> list[tuple[ReminderWindow, datetime, datetime]]:
    windows: list[tuple[ReminderWindow, datetime, datetime]] = []
    for window, (_, lower_bound, upper_bound) in _OFFSET_WINDOWS.items():
        windows.append((window, now_utc + lower_bound, now_utc + upper_bound))
    return windows


def one_day_candidate_range(now_utc: datetime) -> tuple[datetime, datetime]:
    return (now_utc + timedelta(hours=24), now_utc + timedelta(hours=48))


def scheduled_time_for_window(start_time_utc: datetime, provider_timezone: str, window: ReminderWindow) -> datetime:
    timezone = ZoneInfo(provider_timezone)
    local_start = start_time_utc.astimezone(timezone)

    if window == "1day":
        previous_day = local_start - timedelta(days=1)
        local_scheduled = previous_day.replace(hour=8, minute=0, second=0, microsecond=0)
        return local_scheduled.astimezone(UTC)

    delta = _OFFSET_WINDOWS[window][0]
    return (local_start - delta).astimezone(UTC)


def is_due(now_utc: datetime, start_time_utc: datetime, provider_timezone: str, window: ReminderWindow) -> bool:
    scheduled_time = scheduled_time_for_window(start_time_utc, provider_timezone, window)
    if window == "1day":
        return scheduled_time <= now_utc < scheduled_time + _ONE_DAY_TOLERANCE
    return True


def is_quiet_hours(send_time_utc: datetime, provider_timezone: str) -> bool:
    local_send_time = send_time_utc.astimezone(ZoneInfo(provider_timezone))
    return local_send_time.hour < 8 or local_send_time.hour >= 22
