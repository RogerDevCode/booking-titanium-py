from typing import Callable
from app.domain.protocols import UserServiceProtocol, TelegramSenderProtocol
import re
from app.core.logging import logger
from app.domain.enums import FSMState
from app.domain.models import ConversationState

class ProfileFlowHandlers:
    def __init__(self, user_service: UserServiceProtocol, sender: TelegramSenderProtocol, on_idle: Callable) -> None:
        self._user_svc = user_service
        self._sender = sender
        self._on_idle = on_idle

    async def my_data_handler(self, state: ConversationState, text: str):
        """Handles the user profile management flow."""
        logger.info("Handling my_data", chat_id=state.chat_id, text=text)

        user = await self._user_svc.get_user(state.chat_id)
        if not user:
            await self._sender.send_message(
                state.chat_id, "❌ No encontré tu perfil. Por favor inicia con /start."
            )
            state.transition_to(FSMState.IDLE)
            await self._on_idle(state, "")
            return

        step = state.context.get("step", "menu")

        if step == "menu":
            if text.lower() in ["nombre", "1", "a"]:
                state.context["step"] = "awaiting_value"
                state.context["field"] = "first_name"
                # Retain the previous message ID to edit it, or just send a new one
                await self._sender.send_message(
                    state.chat_id, "Escribe tu nuevo nombre:"
                )
            elif text.lower() in ["teléfono", "telefono", "2", "b"]:
                state.context["step"] = "awaiting_value"
                state.context["field"] = "phone"
                await self._sender.send_message(
                    state.chat_id, "Escribe tu nuevo teléfono (ej: +569...):"
                )
            elif text.lower() in ["email", "3", "c"]:
                state.context["step"] = "awaiting_value"
                state.context["field"] = "email"
                await self._sender.send_message(
                    state.chat_id, "Escribe tu nuevo correo electrónico:"
                )
            elif text.lower() in ["dirección", "direccion", "4", "d"]:
                state.context["step"] = "awaiting_value"
                state.context["field"] = "address"
                await self._sender.send_message(
                    state.chat_id, "Escribe tu nueva dirección de residencia:"
                )
            elif text.lower() in ["rut (opcional)", "rut", "5", "e"]:
                state.context["step"] = "awaiting_value"
                state.context["field"] = "rut"
                await self._sender.send_message(
                    state.chat_id, "Escribe tu RUT (con puntos y guión, ej: 12.345.678-9):"
                )
            elif text.lower() in ["volver al menú", "volver al menu", "volver", "atras", "6", "f"]:
                state.transition_to(FSMState.IDLE)
                state.context = {}
                await self._on_idle(state, "")
            else:
                msg = (
                    "👤 *[H] Mis Datos*\n\n"
                    f"📝 *Nombre:* {user.first_name}\n"
                    f"📞 *Teléfono:* {user.phone or 'No registrado'}\n"
                    f"📧 *Email:* {user.email or 'No registrado'}\n"
                    f"🏠 *Dirección:* {user.address or 'No registrado'}\n"
                    f"🪪 *RUT:* {user.rut or 'No registrado'}\n\n"
                    "¿Qué deseas actualizar?"
                )
                # Use strict callbacks via telegram_sender
                kb = self._sender.build_inline_keyboard(["Nombre", "Teléfono", "Email", "Dirección", "RUT (Opcional)", "Volver al Menú"], state.version)
                await self._sender.send_message(state.chat_id, msg, reply_markup=kb)

        elif step == "awaiting_value":
            field = state.context.get("field")
            if not field:
                state.context["step"] = "menu"
                return
        
            # User typed "volver" manually while waiting for input
            if text.lower() in ["volver", "cancelar", "atras"]:
                state.context["step"] = "menu"
                await self.my_data_handler(state, "")
                return

            # Validation
            if field == "email" and not re.match(r"[^@]+@[^@]+\.[^@]+", text):
                await self._sender.send_message(
                    state.chat_id, "❌ Email inválido. Por favor intenta de nuevo (o escribe *cancelar*):"
                )
                return

            if field == "phone" and not re.match(r"^\+?[\d\s\-]{7,15}$", text):
                await self._sender.send_message(
                    state.chat_id, "❌ Teléfono inválido. Por favor intenta de nuevo (o escribe *cancelar*):"
                )
                return

            if field == "first_name" and len(text.strip()) < 2:
                await self._sender.send_message(
                    state.chat_id, "❌ El nombre es muy corto. Por favor intenta de nuevo:"
                )
                return
            
            if field == "address" and len(text.strip()) < 5:
                await self._sender.send_message(
                    state.chat_id, "❌ La dirección parece estar incompleta. Por favor intenta de nuevo:"
                )
                return

            # Save to DB
            success = await self._user_svc.update_field(state.chat_id, str(field), text.strip())
            if success:
                field_name_map = {
                    "first_name": "Nombre",
                    "phone": "Teléfono",
                    "email": "Email",
                    "address": "Dirección",
                    "rut": "RUT"
                }
                field_name = field_name_map.get(str(field), "Dato")
                await self._sender.send_message(
                    state.chat_id, f"✅ *{field_name}* actualizado correctamente."
                )
            else:
                await self._sender.send_message(
                    state.chat_id, "❌ Hubo un error al actualizar."
                )

            # Go back to menu
            state.context["step"] = "menu"
            user = await self._user_svc.get_user(state.chat_id)
            if user:
                msg = (
                    f"👤 *[H] Mis Datos* (Actualizado)\n\n"
                    f"📝 *Nombre:* {user.first_name}\n"
                    f"📞 *Teléfono:* {user.phone or 'No registrado'}\n"
                    f"📧 *Email:* {user.email or 'No registrado'}\n"
                    f"🏠 *Dirección:* {user.address or 'No registrado'}\n"
                    f"🪪 *RUT:* {user.rut or 'No registrado'}\n\n"
                    "¿Deseas cambiar algo más?"
                )
                kb = self._sender.build_inline_keyboard(["Nombre", "Teléfono", "Email", "Dirección", "RUT (Opcional)", "Volver al Menú"], state.version)
                await self._sender.send_message(state.chat_id, msg, reply_markup=kb)

