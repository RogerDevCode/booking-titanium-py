from __future__ import annotations

from typing import Final

from ._menu_models import MenuInput, MenuResponse

MAIN_MENU_INLINE: Final[list[list[dict[str, str]]]] = [
    [{"text": "1. 📅 Agendar hora", "callback_data": "cmd:agendar"}],
    [{"text": "2. 📋 Mis horas", "callback_data": "cmd:mis_citas"}],
    [{"text": "3. ❌ Cancelar hora", "callback_data": "cmd:cancelar_hora"}],
    [{"text": "4. 🔄 Reagendar hora", "callback_data": "cmd:reagendar_hora"}],
    [{"text": "5. 📊 Reporte", "callback_data": "cmd:reporte"}],
    [{"text": "6. ⏰ Recordatorios", "callback_data": "cmd:recordatorios"}],
    [{"text": "7. ℹ️ Información", "callback_data": "cmd:info"}],  # noqa: RUF001
    [{"text": "8. 👤 Mis datos", "callback_data": "cmd:perfil"}],
]

_NUMERIC_INTENT_MAP: Final[dict[str, str]] = {
    "1": "book_appointment",
    "2": "my_bookings",
    "3": "cancelar_hora",
    "4": "reagendar_hora",
    "5": "generar_reporte",
    "6": "recordatorios",
    "7": "informacion",
    "8": "mis_datos",
}


def parse_user_option(text: str) -> str | None:
    lower = text.lower().strip()
    # Callback command passthrough
    if lower.startswith("cmd:"):
        val = lower[4:]
        cmd_map: dict[str, str] = {
            "agendar": "book_appointment",
            "mis_citas": "my_bookings",
            "cancelar_hora": "cancelar_hora",
            "reagendar_hora": "reagendar_hora",
            "reporte": "generar_reporte",
            "recordatorios": "recordatorios",
            "info": "informacion",
            "perfil": "mis_datos",
            "book": "book_appointment",
            "mybookings": "my_bookings",
        }
        return cmd_map.get(val)
    # Numeric fast-path
    numeric = _NUMERIC_INTENT_MAP.get(lower)
    if numeric:
        return numeric
    # Keyword fallback
    if "agendar" in lower:
        return "book_appointment"
    if "mis citas" in lower or "mis horas" in lower:
        return "my_bookings"
    if "cancelar" in lower:
        return "cancelar_hora"
    if "reagendar" in lower:
        return "reagendar_hora"
    return None


class MenuController:
    async def handle(self, input_data: MenuInput) -> MenuResponse:
        if input_data.action in ["start", "show"]:
            return MenuResponse(
                handled=True,
                response_text="🏥 *AutoAgenda - Menú Principal*\n\n¿Cómo podemos ayudarte hoy?",
                inline_buttons=MAIN_MENU_INLINE,
            )

        if input_data.action == "select_option":
            user_input = input_data.user_input or ""
            parsed = parse_user_option(user_input)

            if parsed:
                # Si reconoció la acción, cedemos el control al orquestador
                return MenuResponse(handled=False, response_text="", inline_buttons=[])
            else:
                # Opción inválida, repite el menú
                return MenuResponse(
                    handled=True,
                    response_text="⚠️ Opción no reconocida.\n\n🏥 *AutoAgenda - Menú Principal*\n\nSelecciona una opción:",  # noqa: E501
                    inline_buttons=MAIN_MENU_INLINE,
                )

        return MenuResponse(handled=False, response_text="", inline_buttons=[])
