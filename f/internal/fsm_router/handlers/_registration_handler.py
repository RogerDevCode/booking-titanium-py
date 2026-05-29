from __future__ import annotations

import re
from typing import Final

from ..._wmill_adapter import log
from ...booking_fsm import get_main_menu_inline_buttons, get_main_menu_text
from .._router_models import RouterInput, RouterResult

MODULE = "registration_handler"

REG_STATES: Final[frozenset[str]] = frozenset(
    {
        "needs_registration",
        "reg_confirming_name",
        "reg_entering_name",
        "reg_collecting_phone",
        "reg_collecting_email",
    }
)

_SI_WORDS: Final[frozenset[str]] = frozenset({"s", "y", "si", "sí", "yes", "ok", "dale", "claro", "correcto", "exacto"})
_NO_WORDS: Final[frozenset[str]] = frozenset({"no", "nope", "nel", "negativo"})
_SKIP_WORDS: Final[frozenset[str]] = frozenset({"saltar", "skip", "omitir"})

# Native Telegram "share contact" button payload
PHONE_REPLY_KEYBOARD: Final[list[list[object]]] = [
    [{"text": "📱 Compartir mi número", "request_contact": True}],
    [{"text": "✏️ Escribir manualmente"}],
]


def handle_registration_state(
    input_data: RouterInput,
    current_state_name: str,
    current_state_raw: dict[str, object],
    draft_raw: dict[str, object],
) -> RouterResult:
    """Handle all registration FSM states (needs_registration → reg_collecting_email).

    Extracted from fsm_router/main.py — single responsibility per LAW-06.
    """
    lower = input_data.user_input.strip().lower()
    user_text = input_data.user_input.strip()
    client_name = input_data.client_name or "amigo"

    if current_state_name == "needs_registration":
        if lower in _SI_WORDS:
            return RouterResult(
                handled=True,
                nextState={"name": "reg_confirming_name"},
                nextDraft=dict(draft_raw),
                response_text=(
                    f"¡Perfecto! 😊\n\nTu nombre registrado es *{client_name}*.\n¿Es correcto? Responde *sí* o *no*."
                ),
            )
        if lower in _NO_WORDS:
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                nextDraft={},
                response_text=(
                    "Entendido. 👍\n\nPuedes registrarte cuando quieras para agendar horas.\n\n" + get_main_menu_text()
                ),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        attempts = int(str(current_state_raw.get("invalid_attempts", 0))) + 1
        if attempts >= 3:
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                nextDraft={},
                response_text="❌ Demasiados intentos inválidos. Volviendo al menú principal.\n\n"
                + get_main_menu_text(),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        return RouterResult(
            handled=True,
            nextState={"name": "needs_registration", "invalid_attempts": attempts},
            nextDraft=dict(draft_raw),
            response_text="¿Empezamos con el registro? Responde *sí* o *no*. 😊",
        )

    if current_state_name == "reg_confirming_name":
        if lower in _SI_WORDS:
            new_draft: dict[str, object] = {**dict(draft_raw), "reg_name": client_name}
            return RouterResult(
                handled=True,
                nextState={"name": "reg_collecting_phone"},
                nextDraft=new_draft,
                response_text="📱 ¿Cuál es tu número de teléfono?\n\nEjemplo: +34600000000",
            )
        if lower in _NO_WORDS:
            return RouterResult(
                handled=True,
                nextState={"name": "reg_entering_name"},
                nextDraft=dict(draft_raw),
                response_text="¿Cómo te llamas? Escribe tu nombre completo.",
            )
        attempts = int(str(current_state_raw.get("invalid_attempts", 0))) + 1
        if attempts >= 3:
            return RouterResult(
                handled=True,
                nextState={"name": "idle"},
                nextDraft={},
                response_text="❌ Demasiados intentos inválidos. Volviendo al menú principal.\n\n"
                + get_main_menu_text(),
                inline_buttons=get_main_menu_inline_buttons(),
            )
        return RouterResult(
            handled=True,
            nextState={"name": "reg_confirming_name", "invalid_attempts": attempts},
            nextDraft=dict(draft_raw),
            response_text=(f"Tu nombre registrado es *{client_name}*.\n¿Es correcto? Responde *sí* o *no*."),
        )

    if current_state_name == "reg_entering_name":
        if not user_text:
            return RouterResult(
                handled=True,
                nextState={"name": "reg_entering_name"},
                nextDraft=dict(draft_raw),
                response_text="Por favor escribe tu nombre completo.",
            )
        new_draft2: dict[str, object] = {**dict(draft_raw), "reg_name": user_text}
        return RouterResult(
            handled=True,
            nextState={"name": "reg_collecting_phone"},
            nextDraft=new_draft2,
            response_text="📱 ¿Cuál es tu número de teléfono?\n\nEjemplo: +34600000000",
        )

    if current_state_name == "reg_collecting_phone":
        if not user_text:
            return RouterResult(
                handled=True,
                nextState={"name": "reg_collecting_phone"},
                nextDraft=dict(draft_raw),
                reply_keyboard=PHONE_REPLY_KEYBOARD,
                response_text="Por favor comparte o escribe tu número de teléfono.",
            )
        cleaned_phone = re.sub(r"[\s\-()]+", "", user_text)
        if not re.match(r"^\+?\d{8,15}$", cleaned_phone):
            attempts = int(str(current_state_raw.get("invalid_attempts", 0))) + 1
            if attempts >= 3:
                return RouterResult(
                    handled=True,
                    nextState={"name": "idle"},
                    nextDraft={},
                    response_text="❌ Demasiados intentos inválidos de teléfono. Volviendo al menú principal.\n\n"
                    + get_main_menu_text(),
                    inline_buttons=get_main_menu_inline_buttons(),
                )
            return RouterResult(
                handled=True,
                nextState={"name": "reg_collecting_phone", "invalid_attempts": attempts},
                nextDraft=dict(draft_raw),
                response_text=(
                    "⚠️ El número de teléfono no es válido. "
                    "Por favor ingresa un número con código de país (ejemplo: +56999040515)."
                ),
            )
        new_draft3: dict[str, object] = {**dict(draft_raw), "reg_phone": cleaned_phone}
        return RouterResult(
            handled=True,
            nextState={"name": "reg_collecting_email"},
            nextDraft=new_draft3,
            response_text=("📧 ¿Tienes correo electrónico? (opcional)\n\nEscríbelo o envía *saltar* para omitirlo."),
        )

    if current_state_name == "reg_collecting_email":
        reg_name = str(draft_raw.get("reg_name") or client_name)
        reg_phone = str(draft_raw.get("reg_phone") or "")
        reg_email: str | None
        if lower in _SKIP_WORDS or lower in _NO_WORDS:
            reg_email = None
        else:
            if not re.match(r"^[^@]+@[^@]+\.[^@]+$", user_text.strip()):
                attempts = int(str(current_state_raw.get("invalid_attempts", 0))) + 1
                if attempts >= 3:
                    return RouterResult(
                        handled=True,
                        nextState={"name": "idle"},
                        nextDraft={},
                        response_text="❌ Demasiados intentos de correo inválidos. Registro completado sin correo.\n\n"
                        + get_main_menu_text(),
                        registration_data={"name": reg_name, "phone": reg_phone, "email": None},
                        inline_buttons=get_main_menu_inline_buttons(),
                    )
                return RouterResult(
                    handled=True,
                    nextState={"name": "reg_collecting_email", "invalid_attempts": attempts},
                    nextDraft=dict(draft_raw),
                    response_text=(
                        "⚠️ El correo electrónico no es válido. Por favor ingresa un "
                        "correo electrónico válido (ejemplo: usuario@correo.com) o envía *saltar*."
                    ),
                )
            reg_email = user_text.strip()

        log("REGISTRATION_COMPLETE", chat_id=input_data.chat_id, module=MODULE)
        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            nextDraft={},
            registration_data={"name": reg_name, "phone": reg_phone, "email": reg_email},
            response_text=("✅ ¡Registro completado!\n\nYa puedes agendar tu hora. 🗓️\n\n" + get_main_menu_text()),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    return RouterResult(handled=False)
