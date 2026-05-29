from __future__ import annotations

from typing import cast

from f.internal._config import DEFAULT_TIMEZONE
from f.internal._date_resolver import resolve_date
from f.nlu._datetime_resolver import resolve_datetime as _resolve_datetime_hybrid

from ..._booking_shared import resolve_provider_by_name
from ..._db_client import create_db_client as _create_db_client
from ..._wmill_adapter import log
from ...booking_fsm import get_main_menu_inline_buttons, get_main_menu_text
from ...booking_fsm import DraftBooking, NamedItem, TimeSlotItem
from ...booking_fsm import (
    build_doctor_keyboard,
    build_doctors_with_specialty_prompt,
    build_specialty_keyboard,
    build_time_slot_keyboard,
)
from ...booking_prefetch.main import _fetch_slots_for_doctor as _prefetch_slots
from ...booking_prefetch.main import _has_active_booking_for_provider as _prefetch_active_booking
from .._router_models import RouterInput, RouterResult

MODULE = "smart_prefill_handler"


async def _has_active_booking_for_provider(client_id: str, provider_id: str, pg_url: str) -> bool:
    """Wrapper around prefetch's _has_active_booking_for_provider with own DB conn."""
    db = await _create_db_client(pg_url)
    try:
        return await _prefetch_active_booking(db, client_id, provider_id)
    finally:
        await db.close()


async def _fetch_slots_for_doctor(
    pg_url: str,
    doctor_id: str,
    target_date: str | None = None,
) -> list[dict[str, object]]:
    """Wrapper around prefetch's _fetch_slots_for_doctor with own DB conn."""
    db = await _create_db_client(pg_url)
    try:
        return await _prefetch_slots(db, doctor_id, target_date)
    finally:
        await db.close()


async def handle_smart_prefill(
    input_data: RouterInput,
    draft_raw: dict[str, object],
    session_id: str | None = None,
) -> RouterResult:
    """Smart pre-fill: resolve provider from AI entities and skip wizard steps.

    Extracted from fsm_router/main.py — single responsibility per LAW-06.
    """
    entities = input_data.ai_entities
    provider_name_raw = entities.get("provider_name")
    if not provider_name_raw or not input_data.pg_url:
        return RouterResult(handled=False)

    provider_name = str(provider_name_raw)

    try:
        matches = await resolve_provider_by_name(provider_name, input_data.pg_url)
    except Exception:
        log("SMART_PREFILL_RESOLVE_FAILED", chat_id=input_data.chat_id, module=MODULE)
        return RouterResult(handled=False)

    if not matches:
        display = provider_name.strip().title()
        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            response_text=(
                f"No encontré a *{display}* en nuestro sistema. 🔍\n\n"
                "¿Deseas buscar por especialidad médica?\n\n" + get_main_menu_text()
            ),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    if len(matches) > 1:
        items_list = [{"id": str(m["provider_id"]), "name": str(m["name"])} for m in matches]
        matches_for_prompt = [{"name": str(m["name"]), "specialty_name": str(m["specialty_name"])} for m in matches]
        multi_draft = DraftBooking(target_date=(str(entities.get("date")) if entities.get("date") else None))
        return RouterResult(
            handled=True,
            nextState={
                "name": "selecting_doctor",
                "specialtyId": "",
                "specialtyName": "Selecciona un doctor",
                "items": items_list,
            },
            nextDraft=cast("dict[str, object]", multi_draft.model_dump()),
            response_text=build_doctors_with_specialty_prompt(matches_for_prompt),
            inline_buttons=cast(
                "list[list[dict[str, str]]]",
                build_doctor_keyboard(
                    [NamedItem(id=str(i.get("id", i.get("provider_id", ""))), name=str(i["name"])) for i in items_list],
                    session_id=session_id,
                ),
            ),
        )

    provider = matches[0]
    provider_id = str(provider["provider_id"])
    specialty_id = str(provider["specialty_id"])
    specialty_name = str(provider["specialty_name"])
    doctor_name = str(provider["name"])

    # Resolve target date from AI entities (e.g., "viernes" → "2026-05-22")
    target_date: str | None = None
    date_entity = entities.get("date")
    if date_entity:
        try:
            db = await _create_db_client(input_data.pg_url)
            try:
                tz_row = await db.fetchrow(
                    "SELECT t.name as tz_name FROM providers p"
                    " LEFT JOIN timezones t ON t.id = p.timezone_id"
                    " WHERE p.provider_id = $1::uuid",
                    provider_id,
                )
                provider_tz = str(tz_row["tz_name"]) if tz_row and tz_row["tz_name"] else DEFAULT_TIMEZONE
            finally:
                await db.close()

            date_str = str(date_entity)
            hybrid_result = _resolve_datetime_hybrid(date_str, provider_tz=provider_tz)
            if hybrid_result.intent_detected and hybrid_result.datetime_iso:
                target_date = hybrid_result.datetime_iso[:10]
            else:
                target_date = resolve_date(date_str, {"timezone": provider_tz})
        except Exception:
            log("DATE_RESOLUTION_FAILED", date=str(date_entity), chat_id=input_data.chat_id, module=MODULE)
            target_date = None

    try:
        slots = await _fetch_slots_for_doctor(input_data.pg_url, provider_id, target_date)
    except Exception:
        log("SMART_PREFETCH_SLOTS_FAILED", chat_id=input_data.chat_id, module=MODULE)
        slots = []

    draft = DraftBooking(
        specialty_id=specialty_id,
        specialty_name=specialty_name,
        doctor_id=provider_id,
        doctor_name=doctor_name,
        target_date=target_date or (str(entities.get("date")) if entities.get("date") else None),
    )

    if slots:
        date_label = ""
        if target_date:
            date_label = f" para el {target_date}"
        return RouterResult(
            handled=True,
            nextState={
                "name": "selecting_time",
                "specialtyId": specialty_id,
                "doctorId": provider_id,
                "doctorName": doctor_name,
                "targetDate": target_date,
                "items": slots,
            },
            nextDraft=cast("dict[str, object]", draft.model_dump()),
            response_text=(f"Encontré al *{doctor_name}* ({specialty_name}). Horarios disponibles{date_label}:"),
            inline_buttons=cast(
                "list[list[dict[str, str]]]",
                build_time_slot_keyboard(
                    [
                        TimeSlotItem(id=str(s["id"]), label=str(s["label"]), start_time=str(s["start_time"]))
                        for s in slots
                    ],
                    session_id=session_id,
                ),
            ),
        )

    date_msg = f" para el {target_date}" if target_date else " esta semana"
    specialty_items_raw = list(input_data.items) if input_data.items else []
    specialty_items = [
        NamedItem(id=str(i.get("id", i.get("specialty_id", ""))), name=str(i["name"])) for i in specialty_items_raw
    ]
    return RouterResult(
        handled=True,
        nextState={"name": "selecting_specialty", "items": specialty_items_raw},
        nextDraft=cast("dict[str, object]", draft.model_dump()),
        response_text=(
            f"El *{doctor_name}* no tiene horarios disponibles{date_msg}.\n\n"
            "¿Te gustaría ver otras especialidades o elegir otro doctor?"
        ),
        inline_buttons=cast(
            "list[list[dict[str, str]]] | None",
            build_specialty_keyboard(specialty_items, session_id=session_id) if specialty_items else None,
        ),
    )
