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
import zoneinfo
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final, cast

from ...services.booking._booking_errors import BookingPrefetchBlockedError
from .._db_client import create_db_client as _create_db_client
from .._wmill_adapter import log
from ..scheduling_engine._scheduling_logic import get_availability_range

if TYPE_CHECKING:
    from .._result import DBClient

MODULE: Final[str] = "booking_prefetch"


async def _connect(pg_url: str) -> DBClient:
    return await _create_db_client(pg_url)


async def _fetch_specialties(db: DBClient) -> list[dict[str, object]]:
    rows = await db.fetch(
        """
        SELECT DISTINCT sp.specialty_id, sp.name, sp.sort_order
        FROM specialties sp
        JOIN providers p ON p.specialty_id = sp.specialty_id
        WHERE p.is_active = true
        ORDER BY sp.sort_order ASC, sp.name ASC
        """
    )
    return [{"id": str(r["specialty_id"]), "name": str(r["name"])} for r in rows]


_DAYS_ES: Final[list[str]] = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"]
_MONTHS_ES: Final[list[str]] = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _slot_label(start_iso: str, provider_tz: str = "UTC") -> str:
    dt_utc = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    tz = zoneinfo.ZoneInfo(provider_tz)
    dt = dt_utc.astimezone(tz)
    day = _DAYS_ES[dt.weekday() + 1 if dt.weekday() < 6 else 0]
    return f"{day} {dt.day} {_MONTHS_ES[dt.month]} · {dt.strftime('%H:%M')}"


async def _fetch_slots_for_doctor(
    db: DBClient,
    doctor_id: str,
    target_date: str | None = None,
) -> list[dict[str, object]]:
    row = await db.fetchrow(
        """
        SELECT 
            s.service_id::text, 
            COALESCE(t.name, 'UTC') AS tz_name,
            p.ui_preferences
        FROM providers p
        LEFT JOIN timezones t ON t.id = p.timezone_id
        LEFT JOIN services s ON s.provider_id = p.provider_id AND s.is_active = true
        WHERE p.provider_id = $1::uuid
        LIMIT 1
        """,
        doctor_id,
    )
    if not row or not row["service_id"]:
        return []

    service_id = str(row["service_id"])
    provider_tz = str(row["tz_name"])

    require_advance = False
    if row["ui_preferences"] and isinstance(row["ui_preferences"], dict):
        prefs = cast("dict[str, object]", row["ui_preferences"])
        require_advance = bool(prefs.get("require_advance_booking", False))

    # Use provider's local date as "today", not the server's UTC date
    tz = zoneinfo.ZoneInfo(provider_tz)
    provider_today = datetime.now(tz).date()

    if target_date:
        # Fetch starting from the target date for a 7-day window
        try:
            start_dt = date.fromisoformat(target_date)
        except Exception:
            start_dt = provider_today
        date_from = start_dt.isoformat()
        date_to = (start_dt + timedelta(days=7)).isoformat()
    else:
        # Default: 7-day window
        date_from = (provider_today + timedelta(days=1) if require_advance else provider_today).isoformat()
        date_to = (provider_today + timedelta(days=7)).isoformat()

    results = await get_availability_range(db, doctor_id, service_id, date_from, date_to)
    if not results:
        return []

    # Filter past slots: compare UTC timestamps directly (no artificial buffer)
    now_utc = datetime.now(UTC)
    slots: list[dict[str, object]] = []
    for day_result in results:
        for slot in day_result["slots"]:
            if not slot["available"]:
                continue
            start_iso = str(slot["start"])
            slot_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            if slot_dt <= now_utc:
                continue
            slots.append({"id": start_iso, "label": _slot_label(start_iso, provider_tz), "start_time": start_iso})
            if len(slots) >= 8:
                return slots
    return slots


def _resolve_doctor_from_selection(
    user_input: str | None,
    state_items: list[dict[str, object]],
) -> str | None:
    if not user_input:
        return None
    stripped = user_input.strip()
    if stripped.startswith("doc:"):
        return stripped[4:]
    if not state_items:
        return None
    if stripped.isdigit():
        idx = int(stripped) - 1
        if 0 <= idx < len(state_items):
            return cast("str | None", state_items[idx].get("id"))
    return None


async def _fetch_doctors_by_specialty(db: DBClient, specialty_id: str) -> list[dict[str, object]]:
    rows = await db.fetch(
        """
        SELECT provider_id, name
        FROM providers
        WHERE specialty_id = $1::uuid AND is_active = true
        ORDER BY name ASC
        """,
        specialty_id,
    )
    return [{"id": str(r["provider_id"]), "name": str(r["name"])} for r in rows]


def _resolve_specialty_from_selection(
    user_input: str | None,
    state_items: list[dict[str, object]],
) -> str | None:
    """Return specialty_id from user input: direct UUID via 'spec:UUID' or 1-based index."""
    if not user_input:
        return None
    stripped = user_input.strip()
    if stripped.startswith("spec:"):
        return stripped[5:]
    if not state_items:
        return None
    if stripped.isdigit():
        idx = int(stripped) - 1
        if 0 <= idx < len(state_items):
            return cast("str | None", state_items[idx].get("id"))
    return None


async def _has_active_booking_for_provider(db: DBClient, client_id: str, provider_id: str) -> bool:
    """BE-02: check if client already has an active booking with this specific provider."""
    row = await db.fetchrow(
        """
        SELECT booking_id FROM bookings
        WHERE client_id = $1::uuid
          AND provider_id = $2::uuid
          AND status NOT IN ('cancelled', 'no_show', 'rescheduled')
          AND start_time > NOW()
        LIMIT 1
        """,
        client_id,
        provider_id,
    )
    return row is not None


async def _main_async(
    booking_state: dict[str, object] | None,
    booking_draft: dict[str, object] | None,
    pg_url: str,
    user_input: str | None = None,
    client_id: str | None = None,
) -> dict[str, object]:
    state_name = cast("str", (booking_state or {}).get("name", "idle"))
    normalized_input = user_input.split("|")[0].strip() if user_input else ""
    if normalized_input == "cmd:agendar":
        state_name = "idle"
    db: DBClient | None = None
    try:
        db = await _connect(pg_url)
        if state_name == "idle":
            items = await _fetch_specialties(db)
            log("PREFETCH_SPECIALTIES", count=len(items), module=MODULE)
            return {"items": items, "prefetch_type": "specialties"}

        if state_name == "selecting_specialty":
            # Pre-fetch doctors if we can resolve which specialty the user is picking.
            # This avoids a "loading" round-trip: router can show the list immediately.
            state_items = cast("list[dict[str, object]]", (booking_state or {}).get("items", []))
            specialty_id = _resolve_specialty_from_selection(user_input, state_items)
            if specialty_id:
                items = await _fetch_doctors_by_specialty(db, specialty_id)
                log("PREFETCH_DOCTORS_AHEAD", count=len(items), specialty_id=specialty_id, module=MODULE)
                return {"items": items, "prefetch_type": "doctors", "resolved_specialty_id": specialty_id}

        if state_name == "selecting_doctor":
            state_items = cast("list[dict[str, object]]", (booking_state or {}).get("items", []))
            # Pre-fetch slots when user is picking a doctor
            doctor_id = _resolve_doctor_from_selection(user_input, state_items)
            if doctor_id:
                draft = booking_draft or {}
                target_date = cast("str | None", draft.get("target_date"))
                slots = await _fetch_slots_for_doctor(db, doctor_id, target_date)
                log(
                    "PREFETCH_SLOTS_AHEAD",
                    count=len(slots),
                    doctor_id=doctor_id,
                    target_date=target_date,
                    module=MODULE,
                )
                return {"items": slots, "prefetch_type": "time_slots", "resolved_doctor_id": doctor_id}
            # Fallback: fetch doctor list if state has no items
            if not state_items:
                draft = booking_draft or {}
                specialty_id = cast("str | None", draft.get("specialty_id"))
                if not specialty_id:
                    specialty_id = cast("str | None", (booking_state or {}).get("specialtyId"))
                if specialty_id:
                    items = await _fetch_doctors_by_specialty(db, specialty_id)
                    log("PREFETCH_DOCTORS", count=len(items), specialty_id=specialty_id, module=MODULE)
                    return {"items": items, "prefetch_type": "doctors"}

        if state_name == "selecting_time":
            # Re-fetch slots if state has none (happens when initial prefetch returned empty)
            state_time_items = cast("list[dict[str, object]]", (booking_state or {}).get("items", []))
            if not state_time_items:
                doctor_id = cast("str | None", (booking_state or {}).get("doctorId"))
                if doctor_id:
                    state_raw = booking_state or {}
                    target_date = cast("str | None", state_raw.get("targetDate"))
                    if not target_date:
                        target_date = cast("str | None", (booking_draft or {}).get("target_date"))
                    slots = await _fetch_slots_for_doctor(db, str(doctor_id), target_date)
                    log(
                        "PREFETCH_SLOTS_RETRY",
                        count=len(slots),
                        doctor_id=doctor_id,
                        target_date=target_date,
                        module=MODULE,
                    )
                    return {"items": slots, "prefetch_type": "time_slots"}

        log("PREFETCH_NO_MATCH", state_name=state_name, module=MODULE)
        return {"items": [], "prefetch_type": None}

    except BookingPrefetchBlockedError as e:
        return {"items": [], "prefetch_type": "blocked", "block_reason": e.reason}
    except Exception as e:
        log("PREFETCH_ERROR", error=str(e), traceback=traceback.format_exc(), state_name=state_name, module=MODULE)
        raise RuntimeError(f"Prefetch failed: {e}") from e
    finally:
        if db is not None:
            await db.close()


def main(
    pg_url: str,
    booking_state: dict[str, object] | None = None,
    booking_draft: dict[str, object] | None = None,
    user_input: str | None = None,
    client_id: str | None = None,
) -> dict[str, object]:
    return asyncio.run(_main_async(booking_state, booking_draft, pg_url, user_input, client_id))
