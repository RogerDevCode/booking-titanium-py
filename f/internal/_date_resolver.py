from __future__ import annotations

import re
import unicodedata
import zoneinfo
from datetime import datetime, timedelta
from typing import Final, Required, TypedDict

"""
PRE-FLIGHT
Mission          : Canonical relative date resolver — NL input → YYYY-MM-DD
DB Tables        : NONE
Concurrency Risk : NO
GCal Calls       : NO
Idempotency Key  : NO
RLS Tenant ID    : NO
Zod Schemas      : NO
"""


class ResolveDateOpts(TypedDict, total=False):
    referenceDate: str | None
    timezone: Required[str]


def _normalise(s: str) -> str:
    """Normalises common Spanish accented chars for case-insensitive matching."""
    s = s.lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# Weekday name → 0-based Sunday index (matches TS getUTCDay())
WEEKDAY_MAP: Final[dict[str, int]] = {
    "domingo": 0,
    "lunes": 1,
    "martes": 2,
    "miercoles": 3,  # normalised
    "jueves": 4,
    "viernes": 5,
    "sabado": 6,  # normalised
}


def _today_in_timezone(tz: str) -> str:
    """Returns current local date as YYYY-MM-DD in the given timezone."""
    now = datetime.now(zoneinfo.ZoneInfo(tz))
    return now.strftime("%Y-%m-%d")


def _add_days(ymd: str, days: int) -> str:
    """Adds days to a YYYY-MM-DD date string."""
    dt = datetime.strptime(ymd, "%Y-%m-%d")
    res = dt + timedelta(days=days)
    return res.strftime("%Y-%m-%d")


def _day_of_week(ymd: str) -> int:
    """Returns the day-of-week index (0=Sunday ... 6=Saturday)."""
    dt = datetime.strptime(ymd, "%Y-%m-%d")
    # Python weekday(): 0=Mon, 6=Sun
    # Target: 0=Sun, 1=Mon, ..., 6=Sat
    return (dt.weekday() + 1) % 7


def _next_weekday(ref: str, target: int) -> str:
    """Resolves next occurrence of target weekday from a reference."""
    current = _day_of_week(ref)
    diff = (target - current + 7) % 7
    return _add_days(ref, diff)


def _is_valid_calendar_date(y: int, m: int, d: int) -> bool:
    """Checks if y/m/d forms a valid calendar date."""
    try:
        datetime(y, m, d)
        return True
    except ValueError:
        return False


def resolve_date(input_str: str, opts: ResolveDateOpts | None = None) -> str | None:
    """
    Resolves a user-supplied date string to an absolute YYYY-MM-DD date.
    Returns None if unrecognised.
    """
    if opts is None or not opts.get("timezone"):
        raise ValueError("Timezone is required but was not provided.")

    tz = opts["timezone"]
    ref = opts.get("referenceDate") or _today_in_timezone(tz)
    src = _normalise(input_str)

    # 1. Relative keywords
    if src == "hoy":
        return ref
    if src in ("manana", "mañana"):
        return _add_days(ref, 1)
    if src in ("pasado manana", "pasado mañana"):
        return _add_days(ref, 2)

    # 2. Weekday names
    weekday_index = WEEKDAY_MAP.get(src)
    if weekday_index is not None:
        return _next_weekday(ref, weekday_index)

    # 3. ISO date (YYYY-MM-DD)
    iso_match = re.search(r"^(\d{4})-(\d{2})-(\d{2})", input_str.strip())
    if iso_match:
        y, m, d = map(int, iso_match.groups())
        if _is_valid_calendar_date(y, m, d):
            return f"{y:04d}-{m:02d}-{d:02d}"
        return None

    # 4. DD/MM/YYYY
    dmy_match = re.search(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", input_str.strip())
    if dmy_match:
        d, m, y = map(int, dmy_match.groups())
        if _is_valid_calendar_date(y, m, d):
            return f"{y:04d}-{m:02d}-{d:02d}"
        return None

    # 5. DD/MM (year inferred)
    dm_match = re.search(r"^(\d{1,2})/(\d{1,2})$", input_str.strip())
    if dm_match:
        d, m = map(int, dm_match.groups())
        ref_dt = datetime.strptime(ref, "%Y-%m-%d")
        ref_y = ref_dt.year

        if _is_valid_calendar_date(ref_y, m, d):
            candidate = f"{ref_y:04d}-{m:02d}-{d:02d}"
            if candidate >= ref:
                return candidate
            if _is_valid_calendar_date(ref_y + 1, m, d):
                return f"{ref_y + 1:04d}-{m:02d}-{d:02d}"
        return None

    return None


def resolve_time(input_str: str) -> str | None:
    """Resolves a user-supplied time string to HH:MM (24h)."""
    src = input_str.lower().strip()

    # Extract numbers and meridiem
    # Remove "las " prefix
    src = re.sub(r"^las\s+", "", src)

    match = re.search(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|hrs|horas)?", src)
    if not match:
        return None

    h = int(match.group(1))
    m = int(match.group(2)) if match.group(2) else 0
    meridiem: str | None = match.group(3)

    if meridiem == "pm" and h < 12:
        h += 12
    if meridiem == "am" and h == 12:
        h = 0

    if h < 0 or h > 23 or m < 0 or m > 59:
        return None

    return f"{h:02d}:{m:02d}"


def today_ymd(opts: ResolveDateOpts | None = None) -> str:
    """Convenience: returns today's date in YYYY-MM-DD format."""
    return resolve_date("hoy", opts) or ""
