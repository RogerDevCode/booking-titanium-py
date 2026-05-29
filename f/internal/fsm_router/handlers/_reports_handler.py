from __future__ import annotations

from typing import Any, cast

from ..._report_logic import generate_booking_report
from ...booking_fsm import get_main_menu_inline_buttons, get_main_menu_text
from .._router_models import RouterInput, RouterResult

MODULE = "reports_handler"


async def handle_generar_reporte(
    input_data: RouterInput,
    user_input: str,
    session_id: str | None = None,
) -> RouterResult:
    """Handles the generating and paginating of reports."""
    if not input_data.client_id or not input_data.pg_url:
        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            response_text="📊 *Generar Reporte*\n\nNo pude generar tu reporte en este momento.\n\n"
            + get_main_menu_text(),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    page = 1
    if user_input.startswith("cmd:reporte:p:"):
        try:
            page = int(user_input.split(":")[-1])
        except (ValueError, IndexError):
            page = 1

    report = await generate_booking_report(input_data.client_id, input_data.pg_url, page=page, session_id=session_id)
    if not report:
        return RouterResult(
            handled=True,
            nextState={"name": "idle"},
            response_text="📊 *Generar Reporte*\n\nHubo un error al generar el reporte.\n\n" + get_main_menu_text(),
            inline_buttons=get_main_menu_inline_buttons(),
        )

    return RouterResult(
        handled=True,
        nextState={"name": "idle"},
        response_text=report["text"] + "\n\n" + get_main_menu_text(),
        inline_buttons=cast("list[list[Any]] | None", report["inline_buttons"]),
        edit_message=page > 1,
    )
