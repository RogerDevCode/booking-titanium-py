from typing import Callable
from app.domain.protocols import TelegramSenderProtocol
from app.core.logging import logger
from app.domain.enums import FSMState
from app.domain.models import ConversationState

class FAQFlowHandlers:
    def __init__(self, sender: TelegramSenderProtocol, on_idle: Callable) -> None:
        self._sender = sender
        self._on_idle = on_idle

    async def waiting_faq_handler(self, state: ConversationState, text: str):
        """
        Handles user questions using RAG (Retrieval Augmented Generation).
        """
        logger.info("Handling FAQ query", chat_id=state.chat_id, text=text)

        if text.lower() in ["volver", "salir", "menu", "4", "2", "volver al menú"]:
            state.transition_to(FSMState.IDLE)
            await self._sender.send_message(
                state.chat_id, "Volviendo al menú principal."
            )
            await self._on_idle(state, "")
            return

        # Use the precomputed answer to avoid holding DB lock
        preflight = state.context.get("preflight", {})
        answer = preflight.get("rag_answer", "Lo siento, hubo un problema técnico interno. Intenta más tarde.")

        # 3. Post-process: Append dynamic medical disclaimer
        rag_categories = preflight.get("rag_categories", [])
        has_provider_faq = preflight.get("has_provider_faq", False)
    
        disclaimer = ""
        if "Salud" in rag_categories:
            disclaimer = "\n_⚠️ IA: No es consejo médico. Consulte a su doctor._\n"
        elif has_provider_faq:
            disclaimer = "\n_⚠️ IA: Sujeto a condiciones del médico._\n"
    
        msg = (
            f"🤖 *Respuesta:* \n\n{answer}\n"
            f"{disclaimer}\n"
            "--- \n"
            "¿Tienes otra duda? (o escribe *VOLVER* para salir)"
        )
        kb = self._sender.build_inline_keyboard(
            ["Hacer otra pregunta"], state.version, include_nav=True
        )
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)

