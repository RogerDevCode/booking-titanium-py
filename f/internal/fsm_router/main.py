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
#   "typing-extensions>=4.12.0",
#   "dateparser>=1.2.0",
#   "rapidfuzz>=3.5.2",
#   "jellyfish>=1.0.3"
# ]
# ///
# ///
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, cast

from f.internal._config import DEFAULT_TIMEZONE

if TYPE_CHECKING:
    from ...reminder_config._config_models import InlineButton

import contextlib

from ...nlu._datetime_resolver import resolve_datetime as _resolve_datetime_hybrid
from ...nlu._tfidf_classifier import classify_intent
from .._date_resolver import resolve_date
from .._db_client import create_db_client as _create_db_client
from .._nlu_cache import ensure_nlu_cache
from .._wmill_adapter import log
from ..booking_fsm import (
    apply_transition,
    get_main_menu_inline_buttons,
    get_main_menu_text,
    parse_action,
    parse_callback_data,
)
from ..booking_fsm import BookingStateRoot, DraftBooking, NamedItem, TimeSlotItem
from ..booking_fsm import (
    build_specialty_keyboard,
    build_specialty_prompt,
    build_time_slot_keyboard,
)
from ..booking_prefetch.main import _fetch_slots_for_doctor as _prefetch_slots
from ._router_models import RouterInput, RouterResult
from ._router_reminders import handle_reminders_config
from .handlers._registration_handler import (
    PHONE_REPLY_KEYBOARD as _PHONE_REPLY_KEYBOARD,
)
from .handlers._registration_handler import (
    REG_STATES,
)
from .handlers._registration_handler import (
    handle_registration_state as _handle_registration_state,
)
from .handlers._reports_handler import handle_generar_reporte
from .handlers._smart_prefill_handler import handle_smart_prefill as _handle_smart_prefill
from .handlers._wallet_handler import handle_mis_citas as _handle_mis_citas

_MODULE: Final[str] = "fsm_router"

# Keywords that trigger an immediate abort to main menu (rule-based, no AI needed)
_ABORT_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "menu",
        "menú",
        "inicio",
        "abandono",
        "aborto",
        "salir",
        "dejar",
        "parar",
        "terminar",
        "basta",
        "no mas",
        "no más",
        "desistir",
        "me voy",
        "me rindo",
    }
)

# Intents that can interrupt an active FSM flow (safety net in fsm_router)
_FSM_INTERRUPT_INTENTS: frozenset[str] = frozenset(
    {
        "cancelar_cita",
        "saludo",
        "despedida",
        "agradecimiento",
        "mostrar_menu_principal",
        "ver_mis_citas",
        "ver_mis_datos",
        "activar_recordatorios",
        "pregunta_general",
        "urgencia",
    }
)
_FSM_INTERRUPT_THRESHOLD: float = 0.7

# Fast-path determinista: opciones numéricas del menú principal.
_MENU_NUMERIC_INTENT_MAP: Final[dict[str, str]] = {
    "1": "crear_cita",
    "2": "ver_mis_citas",
    "3": "cancelar_cita",
    "4": "reagendar_cita",
    "5": "generar_reporte",
    "6": "activar_recordatorios",
    "7": "pregunta_general",
    "8": "ver_mis_datos",
}


def _get_start_text(name: str | None = None, phone: str | None = None) -> str:
    greeting = f"¡Hola, {name}! 👋" if name else "¡Hola! 👋"
    user_info_lines: list[str] = []
    if name:
        user_info_lines.append(f"👤 {name}")
    if phone:
        user_info_lines.append(f"📞 {phone}")
    info_block = "\n".join(user_info_lines) + "\n\n" if user_info_lines else ""
    return f"{greeting} Soy tu asistente de reservas.\n\n{info_block}" + get_main_menu_text()


_SI_WORDS: Final[frozenset[str]] = frozenset({"s", "y", "si", "sí", "yes", "ok", "dale", "claro", "correcto", "exacto"})
_NO_WORDS: Final[frozenset[str]] = frozenset({"no", "nope", "nel", "negativo"})
_SKIP_WORDS: Final[frozenset[str]] = frozenset({"saltar", "skip", "omitir"})


def _start_registration(
    input_data: RouterInput,
    source: str,
    draft_raw: dict[str, object],
) -> RouterResult:
    new_draft: dict[str, object] = {**draft_raw, "reg_source": source}
    return RouterResult(
        handled=True,
        nextState={"name": "needs_registration"},
        nextDraft=new_draft,
        active_flow="booking",
        response_text=(
            "Para agendar una hora necesito registrarte primero.\n\n"
            "Solo necesito tu número de teléfono. Es rápido. 😊\n\n"
            "¿Empezamos? Responde *sí* para continuar o *no* para volver al menú."
        ),
    )


def _start_phone_only(
    input_data: RouterInput,
    draft_raw: dict[str, object],
) -> RouterResult:
    """Client exists in DB but has no phone. Ask only for phone — skip name."""
    new_draft: dict[str, object] = {**draft_raw, "reg_source": "agendar", "reg_name": input_data.client_name or ""}
    name = input_data.client_name or "amigo"
    return RouterResult(
        handled=True,
        nextState={"name": "reg_collecting_phone"},
        nextDraft=new_draft,
        active_flow="booking",
        reply_keyboard=_PHONE_REPLY_KEYBOARD,
        response_text=(
            f"Hola, {name}! 👋\n\n"
            "Para confirmar tu reserva necesito tu teléfono de contacto.\n\n"
            "📱 Toca el botón o escríbelo manualmente:"
        ),
    )


async def _route_impl(input_data: RouterInput) -> RouterResult:
    state_dict = input_data.state or {}
    active_flow = cast("str | None", state_dict.get("active_flow"))

    user_input = input_data.user_input
    is_callback = ":" in user_input or user_input in ["back", "cancel", "cfm:yes", "cfm:no"]
    current_state_raw = cast("dict[str, object]", state_dict.get("booking_state") or {"name": "idle"})
    current_session = str(state_dict.get("session_id") or "")

    if user_input.strip() == "/start":
        return RouterResult(
            handled=True,
            active_flow="booking",
            nextState={"name": "idle", "session_id": str(input_data.update_id)},
            response_text=_get_start_text(input_data.client_name, input_data.phone),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    # ─── Fast-path: opciones numéricas del menú en estado idle ───────────────
    current_state_name_for_fastpath = str(
        cast("dict[str, object]", state_dict.get("booking_state") or {"name": "idle"}).get("name", "idle")
    )
    _injected_intent: str | None = None
    if not is_callback and current_state_name_for_fastpath == "idle":
        numeric_intent = _MENU_NUMERIC_INTENT_MAP.get(user_input.strip())
        if numeric_intent is not None:
            log("MENU_NUMERIC_FASTPATH", input=user_input.strip(), intent=numeric_intent, module=_MODULE)
            _injected_intent = numeric_intent

    # ─── Session Validation (Callback security) ───
    if is_callback:
        if current_session and "|" in user_input:
            parts = user_input.split("|")
            btn_session = parts[1]
            if btn_session != current_session:
                log(
                    "SESSION_MISMATCH_IGNORED",
                    current=current_session,
                    button=btn_session,
                    user_input=user_input,
                    module=_MODULE,
                )
                return RouterResult(
                    handled=True,
                    nextState=current_state_raw,
                    response_text=(
                        "⚠️ Este menú ha caducado por una nueva sesión (/start). Por favor usa el menú más reciente."
                    ),
                    active_flow=active_flow,
                )
        # Strip session_id for internal processing
        if "|" in user_input:
            user_input = user_input.split("|")[0]
            is_callback = ":" in user_input or user_input in ["back", "cancel", "cfm:yes", "cfm:no"]

    # ─── Fast-Track (Wallet) Bypass ───
    if user_input.startswith("cmd:repeat:"):
        parts = user_input.split(":")
        if len(parts) == 4:
            pid = parts[2]

            # Fetch slots ahead to jump straight to time selection
            if not input_data.pg_url:
                return RouterResult(handled=False)

            try:
                db = await _create_db_client(input_data.pg_url)
                try:
                    slots = await _prefetch_slots(db, pid)
                    p_row = await db.fetchrow(
                        "SELECT name, specialty_id FROM providers WHERE provider_id = $1::uuid", pid
                    )
                    p_name = str(p_row["name"]) if p_row else "Especialista"
                    sp_id = str(p_row["specialty_id"]) if p_row else ""

                    sp_row = await db.fetchrow("SELECT name FROM specialties WHERE specialty_id = $1::uuid", sp_id)
                    sp_name = str(sp_row["name"]) if sp_row else ""
                finally:
                    await db.close()

                draft_ft = DraftBooking(
                    specialty_id=sp_id,
                    specialty_name=sp_name,
                    doctor_id=pid,
                    doctor_name=p_name,
                )

                return RouterResult(
                    handled=True,
                    nextState={
                        "name": "selecting_time",
                        "specialtyId": sp_id,
                        "doctorId": pid,
                        "doctorName": p_name,
                        "items": slots,
                    },
                    nextDraft=cast("dict[str, object]", draft_ft.model_dump()),
                    response_text=(
                        f"🔁 *Repitiendo reserva*\n\nDoctor: *{p_name}*\n"
                        f"Especialidad: {sp_name}\n\nSelecciona un nuevo horario:"
                    ),
                    inline_buttons=cast(
                        "list[list[InlineButton]]",
                        build_time_slot_keyboard(
                            [
                                TimeSlotItem(
                                    id=str(s["id"]),
                                    label=str(s["label"]),
                                    start_time=str(s["start_time"]),
                                )
                                for s in slots
                            ],
                            session_id=current_session,
                        ),
                    ),
                )
            except Exception as e:
                log("FAST_TRACK_BYPASS_FAILED", error=str(e), module=_MODULE)
                # Fallback to main menu if fast-track fails
                return RouterResult(
                    handled=True,
                    nextState={"name": "idle"},
                    response_text=(
                        "No pudimos repetir la reserva. Por favor selecciona una opción:\n\n" + get_main_menu_text()
                    ),
                    inline_buttons=get_main_menu_inline_buttons(),
                )

    # ─── Activity Report (with Pagination) ───
    if user_input.startswith("cmd:reporte"):
        return await handle_generar_reporte(input_data, user_input, current_session)

    current_state_raw = cast("dict[str, object]", state_dict.get("booking_state") or {"name": "idle"})
    current_state_name = str(current_state_raw.get("name", "idle"))

    if user_input == "cmd:agendar":
        current_state_raw = cast("dict[str, object]", {"name": "idle"})
        current_state_name = "idle"
        state_dict["booking_draft"] = {}

    # cmd:cancelar_hora / cmd:reagendar_hora → redirect to mis_citas view
    if user_input in ("cmd:cancelar_hora", "cancelar_hora"):
        return await _handle_mis_citas(input_data, current_state_raw, session_id=current_session)
    if user_input in ("cmd:reagendar_hora", "reagendar_hora"):
        return await _handle_mis_citas(input_data, current_state_raw, session_id=current_session)

    # Early rule-based or AI-based escape to main menu (este donde este)
    trimmed = user_input.strip().lower()
    is_menu_keyword = trimmed in {
        "menu",
        "menú",
        "ir al menu",
        "ir al menú",
        "ver el menu",
        "ver el menú",
        "volver al menu",
        "volver al menú",
    }
    is_abort_keyword = trimmed in _ABORT_KEYWORDS

    ai_intent = _injected_intent or input_data.ai_intent or ""
    ai_conf = 1.0 if _injected_intent else (input_data.ai_confidence or 0.0)

    if is_menu_keyword or (ai_intent == "mostrar_menu_principal" and ai_conf >= _FSM_INTERRUPT_THRESHOLD):
        if current_state_name != "idle":
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                nextDraft={},
                response_text="He cancelado la reserva en curso.\n\n" + get_main_menu_text(),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        else:
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                nextDraft={},
                response_text=get_main_menu_text(),
                inline_buttons=get_main_menu_inline_buttons(),
            )

    if current_state_name != "idle" and (
        is_abort_keyword or (ai_intent == "cancelar_cita" and ai_conf >= _FSM_INTERRUPT_THRESHOLD)
    ):
        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            nextDraft={},
            response_text="He cancelado la reserva en curso.\n\n" + get_main_menu_text(),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    # Callback double-click/out-of-order protection
    if is_callback:
        state_to_prefixes: dict[str, list[str]] = {
            "selecting_specialty": ["spec:"],
            "selecting_doctor": ["doc:", "back", "cancel"],
            "selecting_time": ["time:", "slot:", "back", "cancel"],
            "confirming": ["cfm:yes", "cfm:no", "back", "cancel"],
            "reminders_config": ["rem:", "back", "cancel"],
            "needs_registration": ["back", "cancel"],
            "reg_confirming_name": ["back", "cancel"],
            "reg_entering_name": ["back", "cancel"],
            "reg_collecting_phone": ["back", "cancel"],
            "reg_collecting_email": ["back", "cancel"],
        }
        allowed = state_to_prefixes.get(current_state_name, [])
        if allowed and not any(user_input.startswith(prefix) for prefix in allowed):
            log(
                "IGNORE_OUT_OF_STATE_CALLBACK",
                user_input=user_input,
                current_state=current_state_name,
                module=_MODULE,
            )
            draft_val = state_dict.get("booking_draft")
            next_draft = cast("dict[str, object] | None", draft_val)
            return RouterResult(
                handled=True,
                nextState=current_state_raw,
                nextDraft=next_draft,
                response_text="SKIP_SEND",
            )

    # Guard: if ai_agent determined no FSM routing needed and we're idle, skip
    if not input_data.requires_fsm_routing and current_state_name == "idle":
        return RouterResult(handled=False)

    # Allow idle processing when requires_fsm_routing is True (booking intent from idle)
    if not active_flow and not is_callback and current_state_name != "idle":
        return RouterResult(handled=False)

    if active_flow and active_flow != "booking":
        return RouterResult(handled=False)

    draft_raw = cast("dict[str, object]", state_dict.get("booking_draft") or {})

    # Defensive fix: Redis Lua cjson serializes empty lists as {} instead of []
    # Convert back to [] for known list fields to prevent Pydantic validation errors
    if isinstance(current_state_raw.get("items"), dict):
        current_state_raw["items"] = []
    if isinstance(draft_raw.get("items"), dict):
        draft_raw["items"] = []

    # Registration states must be checked before BookingStateRoot.model_validate
    if current_state_name in REG_STATES:
        return _handle_registration_state(input_data, current_state_name, current_state_raw, draft_raw)

    if current_state_name == "reminders_config" or user_input.startswith("rem:"):
        return await handle_reminders_config(input_data, current_state_raw)

    await ensure_nlu_cache()

    # Rule-based abort: keywords that immediately cancel any active flow
    if current_state_name != "idle" and user_input.strip().lower() in _ABORT_KEYWORDS:
        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            response_text="He cancelado la reserva en curso.\n\n" + get_main_menu_text(),
        )

    # Flow-interrupt safety net: if AI detected a clear non-booking intent,
    # handle it here instead of forcing through FSM transitions.
    # This catches cases where confidence is below the routing threshold
    # but the intent is still unambiguous.
    ai_intent = _injected_intent or input_data.ai_intent or ""
    ai_conf = 1.0 if _injected_intent else (input_data.ai_confidence or 0.0)

    is_active_booking = current_state_name in ("selecting_doctor", "selecting_time", "confirming")
    allowed_interrupt = True
    if is_active_booking and ai_intent not in ("cancelar_cita", "urgencia"):
        allowed_interrupt = False

    if (
        current_state_name != "idle"
        and ai_intent in _FSM_INTERRUPT_INTENTS
        and ai_conf >= _FSM_INTERRUPT_THRESHOLD
        and allowed_interrupt
    ):
        if ai_intent == "cancelar_cita":
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                nextDraft={},
                response_text="He cancelado la reserva en curso.\n\n" + get_main_menu_text(),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        if ai_intent == "mostrar_menu_principal":
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                response_text=get_main_menu_text(),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        if ai_intent == "ver_mis_citas":
            return await _handle_mis_citas(input_data, current_state_raw, session_id=current_session)
        if ai_intent in ("saludo", "despedida", "agradecimiento"):
            return RouterResult(
                handled=True,
                nextState=current_state_raw,
                response_text=(
                    "Entendido. Cuando quieras continuar con tu reserva, "
                    "responde con la opción que necesitas.\n\n" + get_main_menu_text()
                ),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        if ai_intent in ("ver_mis_datos", "activar_recordatorios", "pregunta_general"):
            return RouterResult(
                handled=True,
                nextState=current_state_raw,
                response_text=(
                    f"He registrado tu consulta ({ai_intent}). "
                    "Para continuar con tu reserva, selecciona una opción del menú.\n\n" + get_main_menu_text()
                ),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        if ai_intent == "urgencia":
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                response_text=(
                    "⚠️ He detectado una situación urgente. "
                    "Tu reserva en curso se ha pausado.\n\n" + get_main_menu_text()
                ),
                inline_buttons=get_main_menu_inline_buttons(),
            )

    try:
        # Handle booking intent from idle — translate to keyword-based FSM
        if current_state_name == "idle" and not is_callback:
            ai_conf = 1.0 if _injected_intent else (input_data.ai_confidence or 0.0)
            intent = _injected_intent or ""
            if not intent:
                if input_data.ai_intent and ai_conf > 0.6:
                    intent = input_data.ai_intent
                else:
                    nlu_res = classify_intent(user_input.strip())
                    intent = str(nlu_res["intent"]) if nlu_res["confidence"] > 0.6 else ""

            if intent in ("crear_cita", "ver_disponibilidad"):
                if not input_data.client_id:
                    # No client in DB at all → full registration
                    return _start_registration(input_data, source="agendar", draft_raw=draft_raw)
                if not input_data.phone:
                    # Client exists but no phone → ask only for phone
                    return _start_phone_only(input_data, draft_raw=draft_raw)

                smart_result = await _handle_smart_prefill(input_data, draft_raw, session_id=current_session)
                if smart_result.handled:
                    return smart_result

                # Resolve target date from AI entities
                target_date: str | None = None
                date_entity = input_data.ai_entities.get("date")
                if date_entity:
                    try:
                        default_tz = DEFAULT_TIMEZONE
                        date_str = str(date_entity)
                        hybrid_result = _resolve_datetime_hybrid(date_str, provider_tz=default_tz)
                        if hybrid_result.intent_detected and hybrid_result.datetime_iso:
                            target_date = hybrid_result.datetime_iso[:10]
                        else:
                            target_date = resolve_date(date_str, {"timezone": default_tz})
                    except Exception:
                        log(
                            "DATE_RESOLUTION_FAILED",
                            date=str(date_entity),
                            chat_id=input_data.chat_id,
                            module=_MODULE,
                        )
                        target_date = None

                # Intent detected — show specialty list, do NOT apply_transition
                # (user hasn't selected anything yet, just expressed intent)
                specialty_items_raw = list(input_data.items) if input_data.items else []
                specialty_items = [
                    NamedItem(id=str(i.get("id", i.get("specialty_id", ""))), name=str(i["name"]))
                    for i in specialty_items_raw
                ]
                if specialty_items:
                    response = build_specialty_prompt(specialty_items)
                else:
                    response = "Buscando especialidades disponibles..."

                next_draft = dict(draft_raw)
                if target_date:
                    next_draft["target_date"] = target_date

                return RouterResult(
                    handled=True,
                    nextState={"name": "selecting_specialty", "items": specialty_items_raw},
                    nextDraft=next_draft,
                    response_text=response,
                    inline_buttons=cast(
                        "list[list[dict[str, str]]] | None",
                        build_specialty_keyboard(specialty_items, session_id=current_session)
                        if specialty_items
                        else None,
                    ),
                )
            elif intent in ("mis_citas", "ver_mis_citas") or intent in ("cancelar_cita", "reagendar_cita"):
                return await _handle_mis_citas(input_data, current_state_raw, session_id=current_session)
            elif intent == "generar_reporte":
                return await handle_generar_reporte(input_data, user_input, current_session)
            elif intent == "mostrar_menu_principal":
                return RouterResult(
                    handled=True,
                    nextState=current_state_raw,
                    response_text=get_main_menu_text(),
                    inline_buttons=get_main_menu_inline_buttons(),
                )
            else:
                return RouterResult(handled=False)

        state_root = BookingStateRoot.model_validate(current_state_raw)
        current_state = state_root.root

        # Strip registration keys so DraftBooking(extra="forbid") doesn't reject them
        booking_draft_raw = {k: v for k, v in draft_raw.items() if not k.startswith("reg_")}
        draft = DraftBooking.model_validate(booking_draft_raw)

        action = parse_callback_data(user_input) if is_callback else parse_action(user_input)

        if not action:
            return RouterResult(handled=False)

        prefetched_items = list(input_data.items) if input_data.items is not None else None
        outcome = apply_transition(current_state, action, draft, items=prefetched_items)

        if not outcome:
            return RouterResult(handled=False)

        # Intercept transition to confirming if user already has an active booking
        next_state_obj = outcome.get("nextState")
        next_state_name = getattr(next_state_obj, "name", None) if next_state_obj else None
        if (
            next_state_name == "confirming"
            and input_data.client_id
            and input_data.pg_url
            and "://test" not in input_data.pg_url
        ):
            from .._booking_shared import query_my_bookings

            active_bookings = await query_my_bookings(input_data.client_id, input_data.pg_url)
            if active_bookings:
                active_booking = active_bookings[0]
                draft_obj = getattr(next_state_obj, "draft", None)
                new_start_time = getattr(draft_obj, "start_time", None) if draft_obj else None
                new_doctor_id = getattr(draft_obj, "doctor_id", None) if draft_obj else None

                if new_start_time and new_doctor_id:
                    from datetime import UTC, datetime
                    from zoneinfo import ZoneInfo

                    from .._booking_shared import _MONTHS_ES

                    # Format old time
                    raw_start = active_booking["start_time"]
                    if isinstance(raw_start, datetime):
                        start_utc = raw_start if raw_start.tzinfo else raw_start.replace(tzinfo=UTC)
                    else:
                        start_utc = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))

                    tz_name = cast("str", active_booking["tz_name"])
                    tz = ZoneInfo(tz_name)
                    local_dt = start_utc.astimezone(tz)
                    day = local_dt.day
                    month = _MONTHS_ES[local_dt.month]
                    time_str = local_dt.strftime("%H:%M")
                    fmt_old_time = f"{day} de {month} a las {time_str}"

                    # Format new time
                    new_dt = datetime.fromisoformat(new_start_time.replace("Z", "+00:00"))
                    new_local_dt = new_dt.astimezone(tz)
                    new_time_str = new_local_dt.strftime("%H:%M")
                    new_date_iso = new_local_dt.strftime("%Y-%m-%d")

                    suffix = f"|{current_session}" if current_session else ""

                    if str(active_booking["provider_id"]) == str(new_doctor_id):
                        ars_callback = f"ars:{active_booking['booking_id']}:{new_date_iso}:{new_time_str}{suffix}"
                        cxl_callback = f"cxl:{active_booking['booking_id']}{suffix}"

                        return RouterResult(
                            handled=True,
                            nextState={"name": "idle"},
                            response_text=(
                                f"ℹ️ *Ya tienes una hora activa*\n\n"  # noqa: RUF001
                                f"Tienes una hora con *{active_booking['provider_name']}* "
                                f"para el *{fmt_old_time}*.\n\n"
                                f"¿Deseas reagendar esa hora para el nuevo horario "
                                f"(*{new_date_iso}* a las *{new_time_str}*)?"
                            ),
                            inline_buttons=[
                                [{"text": "🔄 Sí, reagendar hora", "callback_data": ars_callback}],
                                [{"text": "❌ Cancelar hora", "callback_data": cxl_callback}],
                                [{"text": "« Volver al menú", "callback_data": f"cmd:menu{suffix}"}],
                            ],
                        )
                    else:
                        cxl_callback = f"cxl:{active_booking['booking_id']}{suffix}"
                        return RouterResult(
                            handled=True,
                            nextState={"name": "idle"},
                            response_text=(
                                f"⚠️ *Ya tienes una hora activa*\n\n"
                                f"Tienes una hora con *{active_booking['provider_name']}* "
                                f"para el *{fmt_old_time}*.\n\n"
                                f"Debes cancelar tu hora actual antes de reservar una nueva "
                                f"con un profesional diferente."
                            ),
                            inline_buttons=[
                                [
                                    {
                                        "text": f"❌ Cancelar hora con {active_booking['provider_name']}",
                                        "callback_data": cxl_callback,
                                    }
                                ],
                                [{"text": "« Volver al menú", "callback_data": f"cmd:menu{suffix}"}],
                            ],
                        )

        return RouterResult(
            handled=True,
            response_text=outcome["responseText"],
            nextState=cast("dict[str, object]", outcome["nextState"].model_dump()) if outcome["nextState"] else None,
            nextDraft=None,
            inline_buttons=cast(
                "list[list[dict[str, str]]] | None",
                outcome.get("inlineButtons"),
            ),
            edit_message=is_callback,
        )

    except Exception as e:
        log("ROUTER_INTERNAL_ERROR", error=str(e), chat_id=input_data.chat_id, module=_MODULE)
        raise RuntimeError(f"Router internal error: {e}") from e


async def _route(input_data: RouterInput) -> RouterResult:
    result: RouterResult = await _route_impl(input_data)

    # ─── Session ID Injection (Final Guard) ───
    # Ensure every nextState returned by this router preserves the session_id
    if result.nextState:
        state_dict = input_data.state or {}
        current_session = str(state_dict.get("session_id") or "")

        # If /start was just called, a NEW session was generated in nextState.
        # Otherwise, we carry forward the current session.
        if "session_id" not in result.nextState and current_session:
            result.nextState["session_id"] = current_session

    if result.handled and result.active_flow is None:
        # Only set active_flow if not already explicitly set by the handler
        next_state_name = "idle"
        if result.nextState:
            next_state_name = str(result.nextState.get("name", "idle"))
        else:
            state_dict = input_data.state or {}
            current_state_raw = cast("dict[str, object]", state_dict.get("booking_state") or {"name": "idle"})
            next_state_name = str(current_state_raw.get("name", "idle"))

        if next_state_name != "idle" and next_state_name != "reminders_config":
            result.active_flow = "booking"
        elif next_state_name == "idle":
            result.active_flow = None
            if not result.inline_buttons:
                result.inline_buttons = cast("list[list[Any]]", get_main_menu_inline_buttons())

    # Dual Action Enforcement: if text contains main menu, ensure main menu buttons are present
    if result.response_text and (
        "1️⃣" in result.response_text
        or "Menú Principal" in result.response_text
        or "menú principal" in result.response_text.lower()
    ):
        has_main_menu = False
        if result.inline_buttons:
            for row in result.inline_buttons:
                for btn in row:
                    if isinstance(btn, dict):
                        btn_dict = cast("dict[str, object]", btn)
                        cb_val = btn_dict.get("callback_data")
                        cb = str(cb_val) if cb_val is not None else ""
                    else:
                        cb = ""
                    if cb.startswith("cmd:agendar") or cb.startswith("cmd:book"):
                        has_main_menu = True
                        break
                if has_main_menu:
                    break
        if not has_main_menu:
            main_menu_btns = get_main_menu_inline_buttons()
            if not result.inline_buttons:
                result.inline_buttons = cast("list[list[Any]]", main_menu_btns)
            else:
                current_btns = list(result.inline_buttons)
                result.inline_buttons = current_btns + cast("list[list[Any]]", main_menu_btns)

    return result


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    """Windmill entrypoint."""
    import time

    start = time.perf_counter()
    try:
        input_data = RouterInput.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Router validation error: {e}") from e

    result = await _route(input_data)
    elapsed_ms = (time.perf_counter() - start) * 1000
    log("LATENCY_PROCESS", elapsed_ms=elapsed_ms, module=_MODULE)
    return {"data": cast("dict[str, object]", result.model_dump())}


def main(args: dict[str, object]) -> dict[str, object]:
    import asyncio
    import traceback

    try:
        return asyncio.run(_main_async(args))
    except Exception as e:
        tb = traceback.format_exc()
        with contextlib.suppress(Exception):
            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=_MODULE)
        raise RuntimeError(f"Execution failed: {e}") from e
