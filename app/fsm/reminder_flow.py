from typing import Callable
from app.domain.protocols import UserServiceProtocol, TelegramSenderProtocol
from app.core.logging import logger
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from app.telegram.callback import encode

class ReminderFlowHandlers:
    def __init__(self, user_service: UserServiceProtocol, sender: TelegramSenderProtocol, on_idle: Callable) -> None:
        self._user_svc = user_service
        self._sender = sender
        self._on_idle = on_idle

    async def reminder_handler(self, state: ConversationState, text: str) -> None:
        logger.info("Handling reminder flow", chat_id=state.chat_id, text=text)

        action = text.lower().strip()

        if action in ["volver", "atras", "salir", "home", "cancelar", "volver al menú", "volver al menu", "back"]:
            state.transition_to(FSMState.IDLE)
            state.context = {}
            await self._on_idle(state, "")
            return

        # Check if the user is toggling a preference
        if action in ["telegram_enabled", "email_enabled", "window_24h", "window_2h", "all_off", "all_on"]:
            prefs = await self._user_svc.update_reminder_preference(state.chat_id, action)
        else:
            prefs = await self._user_svc.get_reminder_preferences(state.chat_id)

        user = await self._user_svc.get_user(state.chat_id)
        email_warning = ""
        if prefs.email_enabled and user and not user.email:
            email_warning = "\n\n⚠️ _Nota: Has activado notificaciones por email, pero aún no has registrado un correo en *Mis Datos*._"

        msg = (
            "🔔 *Configuración de Recordatorios*\n\n"
            "Toca las opciones del menú para activar o desactivar tus notificaciones y las alertas previas:"
            f"{email_warning}"
        )

        tg_status = "✅ Activado" if prefs.telegram_enabled else "❌ Desactivado"
        em_status = "✅ Activado" if prefs.email_enabled else "❌ Desactivado"
        w24_status = "✅ Sí" if prefs.window_24h else "❌ No"
        w2_status = "✅ Sí" if prefs.window_2h else "❌ No"

        kb = [
            [
                {"text": f"📱 Telegram: {tg_status}", "callback_data": encode(state.version, "select", "telegram_enabled")},
            ],
            [
                {"text": f"📧 Email: {em_status}", "callback_data": encode(state.version, "select", "email_enabled")},
            ],
            [
                {"text": f"⏰ Alerta 24h antes: {w24_status}", "callback_data": encode(state.version, "select", "window_24h")},
            ],
            [
                {"text": f"⏰ Alerta 2h antes: {w2_status}", "callback_data": encode(state.version, "select", "window_2h")},
            ],
            [
                {"text": "🔕 Desactivar todo", "callback_data": encode(state.version, "select", "all_off")},
                {"text": "🔔 Activar todo", "callback_data": encode(state.version, "select", "all_on")},
            ],
            [
                {"text": "🏠 Volver al Menú", "callback_data": encode(state.version, "select", "back")},
            ]
        ]

        await self._sender.send_message(state.chat_id, msg, reply_markup={"inline_keyboard": kb})
