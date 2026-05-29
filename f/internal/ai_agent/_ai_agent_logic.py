from __future__ import annotations

import re
from typing import Final, Literal, cast

from .._nlu_cache import get_nlu_rule
from ._ai_agent_models import AvailabilityContext, ConversationState, EntityMap, EscalationLevel
from ._constants import (
    FAREWELL_PHRASES,
    FAREWELLS,
    GREETING_PHRASES,
    GREETINGS,
    INTENT,
    THANK_YOU_WORDS,
    URGENCY_WORDS,
)

# ============================================================================
# FSM ROUTING DECISION
# ============================================================================

_FSM_INTENTS: frozenset[str] = frozenset(
    {"crear_cita", "cancelar_cita", "reagendar_cita", "ver_disponibilidad", "generar_reporte"}
)

_FSM_ACTIVE_STATES: frozenset[str] = frozenset(
    {
        "selecting_specialty",
        "selecting_doctor",
        "selecting_time",
        "confirming",
        "needs_registration",
        "reg_confirming_name",
        "reg_entering_name",
        "reg_collecting_phone",
        "reg_collecting_email",
        "reminders_config",
    }
)

# Intents that should interrupt an active flow (high-confidence only)
_FLOW_INTERRUPT_INTENTS: frozenset[str] = frozenset(
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

_FLOW_INTERRUPT_THRESHOLD: float = 0.8


def compute_requires_fsm_routing(intent: str, booking_state_name: str, confidence: float = 0.0) -> bool:
    """Returns True if this message must go through the FSM router.

    When the user is mid-flow but the AI detects a high-confidence interrupt
    intent (e.g., "quiero cancelar" while selecting a doctor), we allow the
    conversational router to handle it instead of forcing FSM routing.
    """
    # Interrupt check: high-confidence non-booking intent during active flow
    if (
        booking_state_name in _FSM_ACTIVE_STATES
        and intent in _FLOW_INTERRUPT_INTENTS
        and confidence >= _FLOW_INTERRUPT_THRESHOLD
    ):
        return False

    if booking_state_name in _FSM_ACTIVE_STATES:
        return True
    return intent in _FSM_INTENTS and booking_state_name == "idle"


# ============================================================================
# CONTEXT-AWARE INTENT ADJUSTMENT
# ============================================================================


def adjust_intent_with_context(
    text: str, current_intent: str, current_confidence: float, state: ConversationState | None
) -> dict[str, object]:
    if state is None:
        return {"adjusted": False, "intent": current_intent, "confidence": current_confidence, "reason": ""}

    lower = text.strip().lower()

    if (state.active_flow in ["selecting_specialty", "booking_wizard"]) and re.match(r"^\d+$", lower):
        return {
            "adjusted": True,
            "intent": INTENT["CREAR_CITA"],
            "confidence": 0.95,
            "reason": f"Context: user selected specialty #{lower} in {state.active_flow} flow",
        }

    if state.active_flow == "selecting_datetime" and re.match(r"^\d", lower):
        return {
            "adjusted": True,
            "intent": INTENT["CREAR_CITA"],
            "confidence": 0.90,
            "reason": "Context: user provided date/time in datetime selection flow",
        }

    if state.active_flow != "none" and lower in ["no", "volver", "menu", "menú", "inicio"]:
        high_min = get_nlu_rule("confidence_bound_high_min", 0.85)
        return {
            "adjusted": True,
            "intent": INTENT["PREGUNTA_GENERAL"],
            "confidence": float(high_min),
            "reason": f"Context: user wants to exit current flow ({state.active_flow})",
        }

    if state.active_flow == "booking_wizard" and lower in ["s", "y", "si", "sí", "confirmar", "confirmo", "yes"]:
        return {
            "adjusted": True,
            "intent": INTENT["CREAR_CITA"],
            "confidence": 0.95,
            "reason": "Context: user confirmed booking in wizard flow",
        }

    return {"adjusted": False, "intent": current_intent, "confidence": current_confidence, "reason": ""}


def detect_fsm_fast_path(text: str, state: ConversationState | None) -> tuple[str, float, str] | None:
    if state is None or state.active_flow == "none":
        return None

    lower = text.strip().lower()
    fsm_state = state.booking_state_name

    if fsm_state in ["selecting_specialty", "selecting_doctor", "selecting_time"] and re.match(r"^\d+$", lower):
        return cast(
            "tuple[str, float, str]",
            (INTENT["CREAR_CITA"], 0.95, f"Num opt in {fsm_state}"),
        )

    if fsm_state == "selecting_time" and re.match(r"^\d", lower):
        return cast(
            "tuple[str, float, str]",
            (INTENT["CREAR_CITA"], 0.90, "User select date/time"),
        )

    if lower in ["no", "volver", "menu", "menú", "inicio"]:
        high_min = float(get_nlu_rule("confidence_bound_high_min", 0.85))
        return cast(
            "tuple[str, float, str]",
            (INTENT["PREGUNTA_GENERAL"], high_min, f"Exit {fsm_state}"),
        )

    if fsm_state == "confirming" and lower in ["s", "y", "si", "sí", "confirmar", "confirmo", "yes"]:
        return cast(
            "tuple[str, float, str]",
            (INTENT["CREAR_CITA"], 0.95, "User confirmed booking"),
        )

    return None


def detect_telegram_command(text: str) -> tuple[str, float] | None:
    text = text.strip()
    if not text.startswith("/"):
        return None

    lower = text.lower()
    if lower in ["/start", "/menu", "/inicio"]:
        return cast("tuple[str, float]", (INTENT["MOSTRAR_MENU_PRINCIPAL"], 1.0))
    if lower in ["/agendar", "/reservar", "/cita"]:
        return cast("tuple[str, float]", (INTENT["CREAR_CITA"], 1.0))
    if lower in ["/cancelar"]:
        return cast("tuple[str, float]", (INTENT["CANCELAR_CITA"], 1.0))
    if lower in ["/mis_citas", "/citas", "/reservas"]:
        return cast("tuple[str, float]", (INTENT["VER_MIS_CITAS"], 1.0))
    if lower in ["/datos", "/perfil"]:
        return cast("tuple[str, float]", (INTENT["VER_MIS_DATOS"], 1.0))

    return cast("tuple[str, float]", (INTENT["MOSTRAR_MENU_PRINCIPAL"], 1.0))


# ============================================================================
# ENTITY EXTRACTION
# ============================================================================


def extract_entities(text: str) -> EntityMap:
    import unicodedata

    lower_text = text.lower()
    # Normalised text for accent-insensitive matching (e.g., "miércoles" → "miercoles")
    normalised_text = "".join(c for c in unicodedata.normalize("NFD", lower_text) if unicodedata.category(c) != "Mn")
    data: dict[str, str | None] = {
        "date": None,
        "time": None,
        "provider_name": None,
        "provider_id": None,
        "service_type": None,
        "service_id": None,
        "booking_id": None,
        "channel": None,
        "reminder_window": None,
    }

    relative_dates: list[str] = get_nlu_rule("relative_dates", [])
    for rel in relative_dates:
        # Normalise rel for accent-insensitive matching
        rel_norm = "".join(c for c in unicodedata.normalize("NFD", rel) if unicodedata.category(c) != "Mn")
        if rel_norm in normalised_text:
            data["date"] = rel if rel in lower_text else rel_norm
            break

    if not data["date"]:
        patterns = [
            r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b",
            r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",
            r"\b(\d{1,2}[-/]\d{1,2})\b",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                data["date"] = m.group(1)
                break

    if not data["date"]:
        day_names: dict[str, str] = get_nlu_rule("day_names", {})
        for day in day_names:
            if day in normalised_text:
                data["date"] = day
                break

    time_patterns = [
        r"(\d{1,2}:\d{2}\s*(?:am|pm|hrs|horas)?)",
        r"(\d{1,2}\s*(?:am|pm|hrs|horas))",
        r"las\s*(\d{1,2})\s*(?:am|pm|horas)?",
    ]
    for p in time_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            data["time"] = m.group(1).strip()
            break

    provider_patterns = [
        # "el/la dr/dra/doctor/doctora X" — most common: "tiene el dr gallegos"
        r"(?:el|la)\s+(?:dr|dra|doctor|doctora)\.?\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)",
        # "con/para [el/la] dr X"
        r"(?:con|para)\s+(?:el|la\s+)?(?:dr|dra|doctor|doctora)\.?\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)",
        # bare "dr X" anywhere
        r"(?:dr|dra|doctor|doctora)\.?\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]+)",
    ]
    for p in provider_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            data["provider_name"] = m.group(1)
            break

    service_types: list[str] = get_nlu_rule("service_types", [])
    for service in service_types:
        if service in lower_text:
            data["service_type"] = service
            break

    booking_patterns = [r"\b([A-Z]{2,3}-\d{3,4})\b", r"#(\d{3,6})\b", r"reserva\s+(\d{3,6})\b"]
    for p in booking_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            data["booking_id"] = m.group(1)
            break

    return EntityMap(**data)


def detect_context(text: str, entities: EntityMap) -> AvailabilityContext:
    lower = text.lower()
    is_today = "hoy" in lower or entities.date == "hoy"
    is_tomorrow = any(x in lower for x in ["mañana", "manana"]) or entities.date == "mañana"

    urgency_words: list[str] = get_nlu_rule("urgency_words", []) or URGENCY_WORDS
    is_urgent = any(w in lower for w in urgency_words)

    flex_keywords: list[str] = get_nlu_rule("flexibility_keywords", [])
    is_flexible = any(w in lower for w in flex_keywords)

    time_pref: Literal["morning", "afternoon", "evening", "any"] = "any"
    if any(x in lower for x in ["mañana", "manana"]):
        time_pref = "morning"
    elif "tarde" in lower:
        time_pref = "afternoon"
    elif "noche" in lower:
        time_pref = "evening"

    day_pref = None
    day_names: dict[str, str] = get_nlu_rule("day_names", {})
    for day, full in day_names.items():
        if day in lower:
            day_pref = full
            break

    return AvailabilityContext(
        is_today=is_today,
        is_tomorrow=is_tomorrow,
        is_urgent=is_urgent,
        is_flexible=is_flexible,
        is_specific_date=entities.date is not None,
        time_preference=time_pref,
        day_preference=day_pref,
    )


def determine_escalation_level(intent: str, text: str, confidence: float) -> EscalationLevel:
    lower = text.lower()
    med_min = float(get_nlu_rule("escalation_medical_emergency_min", 0.8))
    if intent == INTENT["URGENCIA"] and confidence >= med_min:
        patterns = (
            r"muerte|morir|no respiro|infarto|desmay|sangr|convul|paro|dolor.*pecho|dificultad.*respir|no puedo.*respir"
        )
        if re.search(patterns, lower):
            return "medical_emergency"

    pri_max = float(get_nlu_rule("escalation_priority_queue_max", 0.6))
    if intent == INTENT["URGENCIA"] and confidence < pri_max:
        return "priority_queue"

    hum_max = float(get_nlu_rule("escalation_human_handoff_max", 0.4))
    if confidence < hum_max and intent not in [
        INTENT["SALUDO"],
        INTENT["DESPEDIDA"],
        INTENT["AGRADECIMIENTO"],
    ]:
        return "human_handoff"

    return "none"


def generate_ai_response(
    intent: str, entities: EntityMap, context: AvailabilityContext, user_profile: object | None = None
) -> tuple[str, bool, str | None]:
    # simplified for logic
    if intent == INTENT["SALUDO"]:
        return (
            "Hola, soy tu asistente médico. ¿En qué puedo ayudarte?",
            True,
            "¿Deseas agendar, cancelar o cambiar una hora?",
        )

    if intent == INTENT["URGENCIA"]:
        return "Entiendo que es una situación urgente. He localizado espacios prioritarios.", False, None

    return f"He procesado tu solicitud de {intent}.", False, None


def detect_social(text: str) -> tuple[str, float] | None:
    lower = text.lower().strip()

    greetings: list[str] = get_nlu_rule("greetings", []) or GREETINGS
    greeting_phrases: list[str] = get_nlu_rule("greeting_phrases", []) or GREETING_PHRASES
    farewells: list[str] = get_nlu_rule("farewells", []) or FAREWELLS
    farewell_phrases: list[str] = get_nlu_rule("farewell_phrases", []) or FAREWELL_PHRASES

    if lower in greetings:
        return cast("tuple[str, float]", (INTENT["SALUDO"], 0.95))
    if any(p in lower for p in greeting_phrases):
        return cast("tuple[str, float]", (INTENT["SALUDO"], 0.9))
    if lower in farewells:
        return cast("tuple[str, float]", (INTENT["DESPEDIDA"], 0.95))
    if any(p in lower for p in farewell_phrases):
        return cast("tuple[str, float]", (INTENT["DESPEDIDA"], 0.9))
    thank_you_words: list[str] = get_nlu_rule("thank_you_words", []) or THANK_YOU_WORDS
    if lower in thank_you_words or any(p in lower for p in thank_you_words):
        return cast("tuple[str, float]", (INTENT["AGRADECIMIENTO"], 0.95))
    return None


# ============================================================================
# MENU FAST-PATH (deterministic numbered/keyword main-menu selection)
# ============================================================================
#
# The main menu is presented as text ("1️⃣ Agendar … 5️⃣ Mis datos"), so users
# reply with bare digits. TF-IDF cannot classify single tokens (it needs >=2
# words), so without this deterministic fast-path the numbered menu is dead.
# Caller MUST gate this on booking_state_name == "idle": mid-FSM a digit means
# slot/specialty selection and must reach the FSM untouched.

_MENU_AGENDAR: Final[frozenset[str]] = frozenset(
    {"1", "agendar", "agendar cita", "agendar hora", "nueva cita", "nueva hora", "pedir hora", "tomar hora"}
)
_MENU_MIS_CITAS: Final[frozenset[str]] = frozenset(
    {
        "2",
        "mis citas",
        "mis horas",
        "consultar",
        "consultar citas",
        "consultar horas",
        "ver citas",
        "ver horas",
        "ver mis citas",
        "ver mis horas",
    }
)
_MENU_CANCELAR: Final[frozenset[str]] = frozenset(
    {"3", "cancelar", "cancelar cita", "cancelar hora", "anular", "anular cita", "anular hora"}
)
_MENU_REAGENDAR: Final[frozenset[str]] = frozenset(
    {"4", "reagendar", "reagendar cita", "reagendar hora", "cambiar cita", "cambiar hora", "mover cita", "mover hora"}
)
_MENU_REPORTE: Final[frozenset[str]] = frozenset({"5", "reporte", "informe", "descargar citas", "obtener reporte"})
_MENU_RECORDATORIOS: Final[frozenset[str]] = frozenset({"6", "recordatorios", "recordatorio"})
_MENU_INFO: Final[frozenset[str]] = frozenset({"7", "informacion", "información", "info"})
_MENU_MIS_DATOS: Final[frozenset[str]] = frozenset({"8", "mis datos", "datos", "mi perfil", "perfil", "ver mis datos"})


def detect_menu_command(text: str) -> tuple[str, float] | None:
    """Map an exact main-menu selection (digit or alias) to a canonical intent.

    Only valid from the idle state — the caller is responsible for that gate.
    """
    lower = text.strip().lower()
    if lower in _MENU_AGENDAR:
        return cast("tuple[str, float]", (INTENT["CREAR_CITA"], 0.97))
    if lower in _MENU_MIS_CITAS:
        return cast("tuple[str, float]", (INTENT["VER_MIS_CITAS"], 0.97))
    if lower in _MENU_CANCELAR:
        return cast("tuple[str, float]", (INTENT["CANCELAR_CITA"], 0.97))
    if lower in _MENU_REAGENDAR:
        return cast("tuple[str, float]", (INTENT["REAGENDAR_CITA"], 0.97))
    if lower in _MENU_REPORTE:
        return cast("tuple[str, float]", (INTENT["GENERAR_REPORTE"], 0.97))
    if lower in _MENU_RECORDATORIOS:
        return cast("tuple[str, float]", (INTENT["ACTIVAR_RECORDATORIOS"], 0.97))
    if lower in _MENU_INFO:
        return cast("tuple[str, float]", (INTENT["PREGUNTA_GENERAL"], 0.97))
    if lower in _MENU_MIS_DATOS:
        return cast("tuple[str, float]", (INTENT["VER_MIS_DATOS"], 0.97))
    return None
