from __future__ import annotations

import re
from typing import Annotated, Any, Final, Literal, NotRequired, TypedDict, cast

try:
    from typing import TypeIs
except ImportError:
    from typing import TypeIs

from pydantic import BaseModel, ConfigDict, Field, RootModel, TypeAdapter

from ._date_resolver import resolve_date
from ._nlu_cache import get_nlu_rule

# ============================================================================
# CONSTANTS & STEP NAMES
# ============================================================================

BookingStepName = Literal[
    "idle", "selecting_specialty", "selecting_doctor", "selecting_time", "confirming", "completed"
]

class NamedItem(TypedDict):
    id: str
    name: str

class TimeSlotItem(TypedDict):
    id: str
    label: str
    start_time: str

class DraftCore(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    specialty_id: str | None = None
    specialty_name: str | None = None
    doctor_id: str | None = None
    doctor_name: str | None = None
    start_time: str | None = None
    time_label: str | None = None
    client_id: str | None = None
    target_date: str | None = None

class DraftBooking(DraftCore):
    provider_id: str | None = None
    service_id: str | None = None
    last_state_name: BookingStepName | None = None

def empty_draft() -> DraftBooking:
    return DraftBooking()

class IdleState(BaseModel):
    name: Literal["idle"] = "idle"
    session_id: str | None = None

class SelectingSpecialtyState(BaseModel):
    name: Literal["selecting_specialty"] = "selecting_specialty"
    error: str | None = None
    items: list[NamedItem] = Field(default_factory=list)
    invalid_attempts: int = 0
    session_id: str | None = None

class SelectingDoctorState(BaseModel):
    name: Literal["selecting_doctor"] = "selecting_doctor"
    specialtyId: str
    specialtyName: str
    error: str | None = None
    items: list[NamedItem] = Field(default_factory=list)
    invalid_attempts: int = 0
    session_id: str | None = None
    page: int = 1

class SelectingTimeState(BaseModel):
    name: Literal["selecting_time"] = "selecting_time"
    specialtyId: str
    doctorId: str
    doctorName: str
    targetDate: str | None = None
    error: str | None = None
    items: list[TimeSlotItem] = Field(default_factory=list)
    invalid_attempts: int = 0
    session_id: str | None = None

class ConfirmingState(BaseModel):
    name: Literal["confirming"] = "confirming"
    specialtyId: str
    doctorId: str
    doctorName: str
    timeSlot: str
    draft: DraftCore
    invalid_attempts: int = 0
    session_id: str | None = None

class CompletedState(BaseModel):
    name: Literal["completed"] = "completed"
    bookingId: str | None = None
    session_id: str | None = None

BookingState = Annotated[
    IdleState | SelectingSpecialtyState | SelectingDoctorState | SelectingTimeState | ConfirmingState | CompletedState,
    Field(discriminator="name"),
]

class BookingStateRoot(RootModel[BookingState]):
    root: BookingState

class SelectAction(BaseModel):
    type: Literal["select"] = "select"
    value: str

class SelectDateAction(BaseModel):
    type: Literal["select_date"] = "select_date"
    value: str

class BackAction(BaseModel):
    type: Literal["back"] = "back"

class CancelAction(BaseModel):
    type: Literal["cancel"] = "cancel"

class ConfirmYesAction(BaseModel):
    type: Literal["confirm_yes"] = "confirm_yes"

class ConfirmNoAction(BaseModel):
    type: Literal["confirm_no"] = "confirm_no"

class PageAction(BaseModel):
    type: Literal["page"] = "page"
    target: str
    page: int

BookingAction = Annotated[
    SelectAction | SelectDateAction | BackAction | CancelAction | ConfirmYesAction | ConfirmNoAction | PageAction,
    Field(discriminator="type"),
]

class TransitionOutcome(TypedDict):
    nextState: BookingState
    responseText: str
    advance: bool
    inlineButtons: NotRequired[list[list[Any]]]

VALID_TRANSITIONS: dict[BookingStepName, list[BookingStepName]] = {
    "idle": ["selecting_specialty"],
    "selecting_specialty": ["selecting_doctor", "idle"],
    "selecting_doctor": ["selecting_time", "selecting_specialty"],
    "selecting_time": ["confirming", "selecting_doctor"],
    "confirming": ["completed", "selecting_time"],
    "completed": ["idle"],
}

# ============================================================================
# RESPONSE TEMPLATES & KEYBOARDS
# ============================================================================

class InlineButton(TypedDict):
    text: str
    callback_data: str

def build_header(error: str | None = None) -> str:
    return f"⚠️ {error}\n\n" if error else ""

def build_specialty_prompt(items: list[NamedItem], error: str | None = None) -> str:
    header = build_header(error)
    if not items:
        return f"{header}Lo sentimos, el sistema está temporalmente en mantenimiento. Intenta más tarde. 🛠️"
    return f"{header}Selecciona la especialidad que necesitas:"

def build_doctors_prompt(specialty_name: str, items: list[NamedItem], error: str | None = None) -> str:
    header = build_header(error)
    if not items:
        return f"{header}No hay doctores disponibles en este momento para esa especialidad. 🛠️"
    return f"{header}¿Con qué doctor deseas tu hora?"

def build_doctors_with_specialty_prompt(matches: list[dict[str, str]], error: str | None = None) -> str:
    header = build_header(error)
    if not matches:
        return f"{header}No hay doctores disponibles en este momento. 🛠️"
    return f"{header}Encontré varios doctores con ese nombre. ¿Con cuál deseas agendar?"

def build_slots_prompt(doctor_name: str, items: list[TimeSlotItem], error: str | None = None) -> str:
    header = build_header(error)
    if not items:
        return f"{header}No hay horarios disponibles en este momento. 🛠️"
    return f"{header}¿Qué horario prefieres?"

def build_confirmation_prompt(time_label: str, doctor_name: str, extra: str | None = None) -> str:
    prompt = extra or '¿Confirmas esta hora? Responde "sí" o "no".'
    return f"📋 *Confirmar Hora*\n\nDoctor: {doctor_name}\nHorario: {time_label}\n\n{prompt}"

def build_loading_doctors_prompt(specialty_name: str) -> str:
    return f"⏳ Buscando doctores disponibles en *{specialty_name}*..."

def build_loading_slots_prompt(doctor_name: str) -> str:
    return f"⏳ Buscando horarios disponibles con *{doctor_name}*..."

def chunk_buttons(btns: list[InlineButton], size: int = 2) -> list[list[InlineButton]]:
    return [btns[i : i + size] for i in range(0, len(btns), size)]

def build_specialty_keyboard(items: list[NamedItem], session_id: str | None = None) -> list[list[InlineButton]]:
    suffix = f"|{session_id}" if session_id else ""
    rows: list[list[InlineButton]] = [
        [{"text": f"{i + 1}. {it['name']}", "callback_data": f"spec:{it['id']}{suffix}"}] for i, it in enumerate(items)
    ]
    rows.append([{"text": "🏠 Menú Principal", "callback_data": f"cancel{suffix}"}])
    return rows

def build_doctor_keyboard(items: list[NamedItem], page: int = 1, page_size: int = 4, session_id: str | None = None) -> list[list[InlineButton]]:
    suffix = f"|{session_id}" if session_id else ""
    total_items = len(items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = items[start_idx:end_idx]
    global_offset = start_idx
    rows: list[list[InlineButton]] = [
        [{"text": f"{global_offset + i + 1}. {it['name']}", "callback_data": f"doc:{it['id']}{suffix}"}]
        for i, it in enumerate(page_items)
    ]
    chunked = rows
    nav_row: list[InlineButton] = []
    if page > 1:
        nav_row.append({"text": "◀ Anterior", "callback_data": f"page:doctors:{page - 1}{suffix}"})
    if end_idx < total_items:
        nav_row.append({"text": "Siguiente ▶", "callback_data": f"page:doctors:{page + 1}{suffix}"})
    if nav_row:
        chunked.append(nav_row)
    chunked.append([
        {"text": "⬅️ Volver", "callback_data": f"back{suffix}"},
        {"text": "🏠 Menú Principal", "callback_data": f"cancel{suffix}"},
    ])
    return chunked

def build_time_slot_keyboard(items: list[TimeSlotItem], session_id: str | None = None) -> list[list[InlineButton]]:
    suffix = f"|{session_id}" if session_id else ""
    chunked: list[list[InlineButton]] = [
        [{"text": f"{i + 1}. {it['label']}", "callback_data": f"time:{it['id']}{suffix}"}] for i, it in enumerate(items)
    ]
    chunked.append([
        {"text": "⬅️ Volver", "callback_data": f"back{suffix}"},
        {"text": "🏠 Menú Principal", "callback_data": f"cancel{suffix}"},
    ])
    return chunked

def build_confirmation_keyboard(session_id: str | None = None) -> list[list[InlineButton]]:
    suffix = f"|{session_id}" if session_id else ""
    return [
        [
            {"text": "✅ Sí, confirmar", "callback_data": f"cfm:yes{suffix}"},
            {"text": "❌ No, volver", "callback_data": f"cfm:no{suffix}"},
        ]
    ]

# ============================================================================
# FSM LOGIC
# ============================================================================

def get_main_menu_text() -> str:
    default_text = "🏥 *AutoAgenda - Menú Principal*\n\n¿Cómo podemos ayudarte hoy?"
    return str(get_nlu_rule("msg_main_menu", default_text))

def get_main_menu_inline_buttons() -> list[list[dict[str, str]]]:
    return [
        [{"text": "1. 📅 Agendar hora", "callback_data": "cmd:agendar"}],
        [{"text": "2. 📋 Mis horas", "callback_data": "cmd:mis_citas"}],
        [{"text": "3. ❌ Cancelar hora", "callback_data": "cmd:cancelar_hora"}],
        [{"text": "4. 🔄 Reagendar hora", "callback_data": "cmd:reagendar_hora"}],
        [{"text": "5. 📊 Reporte", "callback_data": "cmd:reporte"}],
        [{"text": "6. ⏰ Recordatorios", "callback_data": "cmd:recordatorios"}],
        [{"text": "7. ℹ️ Información", "callback_data": "cmd:info"}],
        [{"text": "8. 👤 Mis datos", "callback_data": "cmd:perfil"}],
    ]

def _is_named_item_list(val: list[Any]) -> TypeIs[list[NamedItem]]:
    return all(isinstance(x, dict) and "id" in x and "name" in x for x in val)

def _is_time_slot_list(val: list[Any]) -> TypeIs[list[TimeSlotItem]]:
    return all(isinstance(x, dict) and "id" in x and "label" in x and "start_time" in x for x in val)

def parse_action(text: str, timezone: str | None = None) -> BookingAction:
    trimmed = text.strip().lower()
    if trimmed in ["volver", "back", "atras"]:
        return BackAction()
    if trimmed in [
        "menu", "menú", "inicio", "cancelar", "cancel", "no quiero", "abandono",
        "aborto", "salir", "dejar", "parar", "terminar", "basta", "no mas", "no más",
        "desistir", "me voy", "me rindo",
    ]:
        return CancelAction()
    if trimmed in ["s", "y", "si", "sí", "yes", "confirmar", "confirmo", "ok", "dale"]:
        return ConfirmYesAction()
    if trimmed in ["n", "no", "nop", "nope"]:
        return ConfirmNoAction()
    if re.match(r"^\d+$", trimmed):
        return SelectAction(value=trimmed)
    if timezone:
        try:
            parsed_date = resolve_date(trimmed, {"timezone": timezone})
            if parsed_date:
                return SelectDateAction(value=parsed_date)
        except ValueError:
            pass
    return SelectAction(value=trimmed)

def parse_callback_data(data: str) -> BookingAction | None:
    raw_data = data
    if "|" in data:
        raw_data = data.split("|")[0]
    if raw_data == "back":
        return BackAction()
    if raw_data == "cancel":
        return CancelAction()
    if raw_data == "cfm:yes":
        return ConfirmYesAction()
    if raw_data == "cfm:no":
        return ConfirmNoAction()
    if raw_data == "agendar":
        return SelectAction(value="1")
    if raw_data.startswith("cmd:"):
        val = raw_data[4:]
        if val == "agendar":
            return SelectAction(value="1")
        if val == "cancelar_hora":
            return SelectAction(value="cancelar_hora")
        if val == "reagendar_hora":
            return SelectAction(value="reagendar_hora")
        return SelectAction(value=val)
    match = re.match(r"^(spec|doc|time|slot):(.+)$", raw_data)
    if match:
        return SelectAction(value=match.group(2))
    match_page = re.match(r"^page:([a-z]+):(\d+)$", raw_data)
    if match_page:
        return PageAction(target=match_page.group(1), page=int(match_page.group(2)))
    return None

def apply_transition(
    current_state: BookingState,
    action: BookingAction | dict[str, Any],
    draft: DraftBooking,
    items: list[Any] | None = None,
) -> TransitionOutcome:
    if isinstance(action, dict):
        try:
            action = cast("BookingAction", TypeAdapter(BookingAction).validate_python(action))
        except Exception as e:
            raise RuntimeError(f"invalid_action_structure: {e}") from e

    if isinstance(action, CancelAction):
        return TransitionOutcome(
            nextState=IdleState(session_id=current_state.session_id),
            responseText=get_main_menu_text(),
            advance=False,
            inlineButtons=get_main_menu_inline_buttons(),
        )

    if isinstance(current_state, IdleState):
        if isinstance(action, SelectAction):
            raw_items = items if items is not None else []
            if _is_named_item_list(raw_items):
                return TransitionOutcome(
                    nextState=SelectingSpecialtyState(items=raw_items, session_id=current_state.session_id),
                    responseText=build_specialty_prompt(raw_items),
                    advance=True,
                    inlineButtons=build_specialty_keyboard(raw_items, session_id=current_state.session_id),
                )
            raise RuntimeError("no_specialties_available")
        raise RuntimeError("invalid_idle_action")

    elif isinstance(current_state, SelectingSpecialtyState):
        if isinstance(action, BackAction):
            return TransitionOutcome(
                nextState=IdleState(session_id=current_state.session_id),
                responseText=get_main_menu_text(),
                advance=False,
                inlineButtons=get_main_menu_inline_buttons(),
            )
        if isinstance(action, SelectAction):
            specialty_items = current_state.items
            specialty = next((i for i in specialty_items if i["id"] == action.value), None)
            if not specialty and re.match(r"^\d+$", action.value):
                idx = int(action.value) - 1
                if 0 <= idx < len(specialty_items):
                    specialty = specialty_items[idx]
            if not specialty:
                attempts = current_state.invalid_attempts + 1
                if attempts >= 3:
                    return TransitionOutcome(
                        nextState=IdleState(session_id=current_state.session_id),
                        responseText="❌ Demasiados intentos inválidos. Volviendo al menú principal.",
                        advance=False,
                        inlineButtons=get_main_menu_inline_buttons(),
                    )
                return TransitionOutcome(
                    nextState=SelectingSpecialtyState(
                        items=specialty_items,
                        error="Opción inválida.",
                        invalid_attempts=attempts,
                        session_id=current_state.session_id,
                    ),
                    responseText=build_specialty_prompt(specialty_items, "⚠️ Opción inválida."),
                    advance=False,
                    inlineButtons=build_specialty_keyboard(specialty_items, session_id=current_state.session_id),
                )
            doctor_items = items if items is not None else []
            if _is_named_item_list(doctor_items) and doctor_items:
                return TransitionOutcome(
                    nextState=SelectingDoctorState(
                        specialtyId=specialty["id"],
                        specialtyName=specialty["name"],
                        items=doctor_items,
                        session_id=current_state.session_id,
                    ),
                    responseText=build_doctors_prompt(specialty["name"], doctor_items),
                    advance=True,
                    inlineButtons=build_doctor_keyboard(doctor_items, session_id=current_state.session_id),
                )
            return TransitionOutcome(
                nextState=SelectingDoctorState(
                    specialtyId=specialty["id"],
                    specialtyName=specialty["name"],
                    items=[],
                    session_id=current_state.session_id,
                ),
                responseText=build_loading_doctors_prompt(specialty["name"]),
                advance=True,
            )

    elif isinstance(current_state, SelectingDoctorState):
        if isinstance(action, BackAction):
            raw_items = items if items is not None else []
            if _is_named_item_list(raw_items):
                return TransitionOutcome(
                    nextState=SelectingSpecialtyState(items=raw_items, session_id=current_state.session_id),
                    responseText=build_specialty_prompt(raw_items),
                    advance=False,
                    inlineButtons=build_specialty_keyboard(raw_items, session_id=current_state.session_id),
                )
            raise RuntimeError("invalid_state_transition_no_items")
        if isinstance(action, PageAction) and action.target == "doctors":
            doctor_items = current_state.items if current_state.items else (items if items is not None else [])
            if not _is_named_item_list(doctor_items):
                raise RuntimeError("invalid_doctor_items")
            return TransitionOutcome(
                nextState=SelectingDoctorState(
                    specialtyId=current_state.specialtyId,
                    specialtyName=current_state.specialtyName,
                    items=doctor_items,
                    invalid_attempts=current_state.invalid_attempts,
                    session_id=current_state.session_id,
                    page=action.page,
                ),
                responseText=build_doctors_prompt(current_state.specialtyName, doctor_items),
                advance=False,
                inlineButtons=build_doctor_keyboard(
                    doctor_items,
                    page=action.page,
                    session_id=current_state.session_id,
                ),
            )
        if isinstance(action, SelectAction):
            doctor_items = current_state.items if current_state.items else (items if items is not None else [])
            if not _is_named_item_list(doctor_items):
                raise RuntimeError("invalid_doctor_items")
            doctor = next((i for i in doctor_items if i["id"] == action.value), None)
            if not doctor and re.match(r"^\d+$", action.value):
                idx = int(action.value) - 1
                if 0 <= idx < len(doctor_items):
                    doctor = doctor_items[idx]
            if not doctor:
                attempts = current_state.invalid_attempts + 1
                if attempts >= 3:
                    return TransitionOutcome(
                        nextState=IdleState(session_id=current_state.session_id),
                        responseText="❌ Demasiados intentos inválidos. Volviendo al menú principal.",
                        advance=False,
                        inlineButtons=get_main_menu_inline_buttons(),
                    )
                return TransitionOutcome(
                    nextState=SelectingDoctorState(
                        specialtyId=current_state.specialtyId,
                        specialtyName=current_state.specialtyName,
                        items=doctor_items,
                        error="Opción inválida.",
                        invalid_attempts=attempts,
                        session_id=current_state.session_id,
                        page=current_state.page,
                    ),
                    responseText=build_doctors_prompt(current_state.specialtyName, doctor_items, "⚠️ Opción inválida."),
                    advance=False,
                    inlineButtons=build_doctor_keyboard(
                        doctor_items,
                        page=current_state.page,
                        session_id=current_state.session_id,
                    ),
                )
            time_items = items if items is not None else []
            if _is_time_slot_list(time_items) and time_items:
                return TransitionOutcome(
                    nextState=SelectingTimeState(
                        specialtyId=current_state.specialtyId,
                        doctorId=doctor["id"],
                        doctorName=doctor["name"],
                        targetDate=draft.target_date,
                        items=time_items,
                        session_id=current_state.session_id,
                    ),
                    responseText=build_slots_prompt(doctor["name"], time_items),
                    advance=True,
                    inlineButtons=build_time_slot_keyboard(time_items, session_id=current_state.session_id),
                )
            return TransitionOutcome(
                nextState=SelectingTimeState(
                    specialtyId=current_state.specialtyId,
                    doctorId=doctor["id"],
                    doctorName=doctor["name"],
                    targetDate=draft.target_date,
                    items=[],
                    session_id=current_state.session_id,
                ),
                responseText=build_loading_slots_prompt(doctor["name"]),
                advance=True,
            )

    elif isinstance(current_state, SelectingTimeState):
        if isinstance(action, BackAction):
            raw_items = items if items is not None else []
            if _is_named_item_list(raw_items):
                return TransitionOutcome(
                    nextState=SelectingDoctorState(
                        specialtyId=current_state.specialtyId,
                        specialtyName="",  # Will be filled by UI/Service
                        items=raw_items,
                        session_id=current_state.session_id,
                    ),
                    responseText=build_doctors_prompt("", raw_items),
                    advance=False,
                    inlineButtons=build_doctor_keyboard(raw_items, session_id=current_state.session_id),
                )
            raise RuntimeError("invalid_state_transition_no_items")
        if isinstance(action, SelectDateAction):
            return TransitionOutcome(
                nextState=SelectingTimeState(
                    specialtyId=current_state.specialtyId,
                    doctorId=current_state.doctorId,
                    doctorName=current_state.doctorName,
                    targetDate=action.value,
                    items=[],
                    session_id=current_state.session_id,
                ),
                responseText=f"Buscando horarios para el {action.value}...",
                advance=True,
            )
        if isinstance(action, SelectAction):
            raw_items = items if items is not None else []
            time_items = current_state.items if current_state.items else raw_items
            if not _is_time_slot_list(time_items):
                raise RuntimeError("invalid_time_items")
            slot = next((i for i in time_items if i["id"] == action.value or i["start_time"] == action.value), None)
            if not slot and re.match(r"^\d+$", action.value):
                idx = int(action.value) - 1
                if 0 <= idx < len(time_items):
                    slot = time_items[idx]
            if not slot:
                attempts = current_state.invalid_attempts + 1
                if attempts >= 3:
                    return TransitionOutcome(
                        nextState=IdleState(session_id=current_state.session_id),
                        responseText="❌ Demasiados intentos inválidos. Volviendo al menú principal.",
                        advance=False,
                        inlineButtons=get_main_menu_inline_buttons(),
                    )
                return TransitionOutcome(
                    nextState=SelectingTimeState(
                        specialtyId=current_state.specialtyId,
                        doctorId=current_state.doctorId,
                        doctorName=current_state.doctorName,
                        targetDate=current_state.targetDate,
                        items=time_items,
                        error="Opción inválida.",
                        invalid_attempts=attempts,
                        session_id=current_state.session_id,
                    ),
                    responseText=build_slots_prompt(current_state.doctorName, time_items, "⚠️ Opción inválida."),
                    advance=False,
                    inlineButtons=build_time_slot_keyboard(time_items, session_id=current_state.session_id),
                )
            new_draft = draft.model_copy()
            new_draft.specialty_id = current_state.specialtyId
            new_draft.doctor_id = current_state.doctorId
            new_draft.doctor_name = current_state.doctorName
            new_draft.start_time = slot["start_time"]
            new_draft.time_label = slot["label"]
            new_draft.target_date = current_state.targetDate
            return TransitionOutcome(
                nextState=ConfirmingState(
                    specialtyId=current_state.specialtyId,
                    doctorId=current_state.doctorId,
                    doctorName=current_state.doctorName,
                    timeSlot=slot["label"],
                    draft=DraftCore(
                        specialty_id=new_draft.specialty_id,
                        specialty_name=new_draft.specialty_name,
                        doctor_id=new_draft.doctor_id,
                        doctor_name=new_draft.doctor_name,
                        start_time=new_draft.start_time,
                        time_label=new_draft.time_label,
                        client_id=new_draft.client_id,
                        target_date=new_draft.target_date,
                    ),
                    session_id=current_state.session_id,
                ),
                responseText=build_confirmation_prompt(slot["label"], current_state.doctorName),
                advance=True,
                inlineButtons=build_confirmation_keyboard(session_id=current_state.session_id),
            )

    elif isinstance(current_state, ConfirmingState):
        if isinstance(action, ConfirmYesAction):
            return TransitionOutcome(
                nextState=IdleState(session_id=current_state.session_id),
                responseText="⏳ Procesando tu reserva...",
                advance=True,
            )
        if isinstance(action, ConfirmNoAction | BackAction):
            raw_items = items if items is not None else []
            if _is_time_slot_list(raw_items):
                return TransitionOutcome(
                    nextState=SelectingTimeState(
                        specialtyId=current_state.specialtyId,
                        doctorId=current_state.doctorId,
                        doctorName=current_state.doctorName,
                        targetDate=draft.target_date,
                        items=raw_items,
                        session_id=current_state.session_id,
                    ),
                    responseText=build_slots_prompt(current_state.doctorName, raw_items),
                    advance=False,
                    inlineButtons=build_time_slot_keyboard(raw_items, session_id=current_state.session_id),
                )
            raise RuntimeError("invalid_state_transition_no_items")
        if isinstance(action, SelectAction):
            if action.value == "1":
                return TransitionOutcome(
                    nextState=IdleState(session_id=current_state.session_id),
                    responseText="⏳ Procesando tu reserva...",
                    advance=True,
                )
            if action.value == "2":
                raw_items = items if items is not None else []
                if _is_time_slot_list(raw_items):
                    return TransitionOutcome(
                        nextState=SelectingTimeState(
                            specialtyId=current_state.specialtyId,
                            doctorId=current_state.doctorId,
                            doctorName=current_state.doctorName,
                            targetDate=draft.target_date,
                            items=raw_items,
                            session_id=current_state.session_id,
                        ),
                        responseText=build_slots_prompt(current_state.doctorName, raw_items),
                        advance=False,
                        inlineButtons=build_time_slot_keyboard(raw_items, session_id=current_state.session_id),
                    )
        attempts = getattr(current_state, "invalid_attempts", 0) + 1
        if attempts >= 3:
            return TransitionOutcome(
                nextState=IdleState(session_id=current_state.session_id),
                responseText="❌ Demasiados intentos inválidos. Volviendo al menú principal.",
                advance=False,
                inlineButtons=get_main_menu_inline_buttons(),
            )
        return TransitionOutcome(
            nextState=ConfirmingState(
                specialtyId=current_state.specialtyId,
                doctorId=current_state.doctorId,
                doctorName=current_state.doctorName,
                timeSlot=current_state.timeSlot,
                draft=current_state.draft,
                invalid_attempts=attempts,
                session_id=current_state.session_id,
            ),
            responseText=build_confirmation_prompt(
                current_state.timeSlot, current_state.doctorName, extra="⚠️ Opción inválida. Responde sí o no."
            ),
            advance=False,
            inlineButtons=build_confirmation_keyboard(session_id=current_state.session_id),
        )

    return TransitionOutcome(
        nextState=IdleState(session_id=current_state.session_id),
        responseText=get_main_menu_text(),
        advance=False,
        inlineButtons=get_main_menu_inline_buttons(),
    )

STEP_TO_FLOW_STEP: Final[dict[str, int]] = {
    "idle": 0,
    "selecting_specialty": 1,
    "selecting_doctor": 2,
    "selecting_time": 3,
    "confirming": 4,
    "completed": 5,
}

def extract_draft_from_state(state: BookingState, previous_draft: DraftBooking | None = None) -> DraftBooking:
    target_date = previous_draft.target_date if previous_draft else None
    if isinstance(state, ConfirmingState):
        return DraftBooking(
            specialty_id=state.draft.specialty_id,
            specialty_name=state.draft.specialty_name,
            doctor_id=state.draft.doctor_id,
            doctor_name=state.draft.doctor_name,
            start_time=state.draft.start_time,
            time_label=state.draft.time_label,
            client_id=state.draft.client_id,
            target_date=state.draft.target_date or target_date,
        )
    if isinstance(state, SelectingTimeState):
        return DraftBooking(
            specialty_id=state.specialtyId,
            doctor_id=state.doctorId,
            doctor_name=state.doctorName,
            target_date=state.targetDate or target_date,
        )
    if isinstance(state, SelectingDoctorState):
        return DraftBooking(
            specialty_id=state.specialtyId,
            specialty_name=state.specialtyName,
            target_date=target_date,
        )
    if isinstance(state, SelectingSpecialtyState):
        return DraftBooking(target_date=target_date)
    if isinstance(state, CompletedState):
        return DraftBooking(last_state_name="completed")
    return DraftBooking(target_date=target_date)

def flow_step_from_state(state: BookingState) -> int:
    return STEP_TO_FLOW_STEP.get(state.name, 0)
