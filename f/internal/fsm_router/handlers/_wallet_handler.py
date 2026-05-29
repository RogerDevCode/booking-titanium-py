from __future__ import annotations

from ..._booking_shared import get_mis_citas_data
from ...booking_fsm import get_main_menu_inline_buttons, get_main_menu_text
from .._router_models import RouterInput, RouterResult

MODULE = "wallet_handler"


async def handle_mis_citas(
    input_data: RouterInput,
    current_state_raw: dict[str, object],
    session_id: str | None = None,
) -> RouterResult:
    if not input_data.client_id or not input_data.pg_url:
        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            nextDraft={},
            response_text=("📋 *Mis Horas*\n\nNo pudimos cargar tus horas en este momento.\n\n" + get_main_menu_text()),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    text, buttons = await get_mis_citas_data(
        input_data.client_id, input_data.pg_url, input_data.chat_id, session_id=session_id
    )

    if not text:
        msg = "📋 *Mis Horas*\n\nNo tienes horas próximas agendadas."

        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            nextDraft={},
            response_text=msg + "\n\n" + get_main_menu_text(),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    return RouterResult(
        handled=True,
        nextState={"name": "idle"},
        nextDraft={},
        response_text=text + "\n\n" + get_main_menu_text(),
        inline_buttons=buttons,
    )
