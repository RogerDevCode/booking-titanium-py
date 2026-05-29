from app.core.logging import logger
from app.domain.enums import FSMState
from app.domain.enums import Intent
from app.domain.models import ConversationState
from app.telegram.callback import decode
from typing import Callable, Awaitable, Dict

from app.domain.protocols import (
    BookingServiceProtocol,
    UserServiceProtocol,
    TelegramSenderProtocol,
    BookingRepositoryProtocol,
    DatabaseClientProtocol,
)

from app.fsm.booking_flow import BookingFlowHandlers
from app.fsm.profile_flow import ProfileFlowHandlers
from app.fsm.faq_flow import FAQFlowHandlers
from app.fsm.report_flow import ReportFlowHandlers

HandlerType = Callable[['ConversationState', str], Awaitable[None]]


class FSMRouter:
    def __init__(
        self,
        booking_service: BookingServiceProtocol,
        user_service: UserServiceProtocol,
        sender: TelegramSenderProtocol,
        booking_repo: BookingRepositoryProtocol,
        db: DatabaseClientProtocol,
    ) -> None:
        self._sender = sender
        self._booking_svc = booking_service
        self._user_svc = user_service
        self._repo = booking_repo
        self._db = db

        self._booking_flow = BookingFlowHandlers(
            booking_service=booking_service,
            sender=sender,
            booking_repo=booking_repo,
            on_idle=self._idle_handler,
        )
        self._profile_flow = ProfileFlowHandlers(
            user_service=user_service,
            sender=sender,
            on_idle=self._idle_handler,
        )
        self._faq_flow = FAQFlowHandlers(
            sender=sender,
            on_idle=self._idle_handler,
        )
        self._report_flow = ReportFlowHandlers(
            booking_repo=booking_repo,
            sender=sender,
            on_idle=self._idle_handler,
        )

        self._handlers: Dict[FSMState, HandlerType] = {
            FSMState.IDLE: self._idle_handler,
            FSMState.SELECTING_SPECIALTY: self._booking_flow.selecting_specialty_handler,
            FSMState.SELECTING_DOCTOR: self._booking_flow.selecting_doctor_handler,
            FSMState.SELECTING_TIME: self._booking_flow.selecting_time_handler,
            FSMState.CONFIRMING_BOOKING: self._booking_flow.confirming_booking_handler,
            FSMState.VIEWING_BOOKINGS: self._booking_flow.my_bookings_handler,
            FSMState.CANCELLING_BOOKING: self._booking_flow.cancellation_handler,
            FSMState.RESCHEDULING_BOOKING: self._booking_flow.reschedule_handler,
            FSMState.UPDATING_PROFILE: self._profile_flow.my_data_handler,
            FSMState.WAITING_FAQ: self._faq_flow.waiting_faq_handler,
            FSMState.JOINING_WAITLIST: self._booking_flow.joining_waitlist_handler,
            FSMState.VIEWING_REPORT: self._report_flow.report_handler,
        }

    async def _idle_handler(self, state: ConversationState, text: str) -> None:
        logger.info("Handling IDLE state", chat_id=state.chat_id, text=text)

        preflight = state.context.get("preflight", {})
        intent = preflight.get("intent", Intent.UNKNOWN)

        if intent == Intent.BOOK_APPOINTMENT:
            state.transition_to(FSMState.SELECTING_SPECIALTY)
            specialties = await self._booking_svc.get_all_specialties()
            msg = "🏥 *[B] Agendar Hora*\n\n¡Excelente! Vamos a agendar tu hora. ¿Qué especialidad buscas?"
            options = [s.name for s in specialties]
            kb = self._sender.build_inline_keyboard(options, state.version, include_nav=True)
            await self._sender.send_message(state.chat_id, msg, reply_markup=kb)

        elif intent == Intent.MY_BOOKINGS:
            state.transition_to(FSMState.VIEWING_BOOKINGS)
            msg = "📅 *[F] Mis Horas*\n\nAquí tienes tus próximas citas:"
            await self._booking_flow.my_bookings_handler(state, "")

        elif intent == Intent.CANCEL_APPOINTMENT:
            state.transition_to(FSMState.CANCELLING_BOOKING)
            await self._booking_flow.cancellation_handler(state, "")

        elif intent == Intent.RESCHEDULING_BOOKING or intent == Intent.RESCHEDULE_APPOINTMENT:
            state.transition_to(FSMState.RESCHEDULING_BOOKING)
            await self._booking_flow.reschedule_handler(state, "")

        elif intent == Intent.GET_REPORT:
            state.transition_to(FSMState.VIEWING_REPORT)
            await self._report_flow.report_handler(state, "")
        elif intent == Intent.GET_INFO:
            state.transition_to(FSMState.WAITING_FAQ)
            await self._sender.send_message(
                state.chat_id,
                "ℹ️ *[I] Información*\n\nSoy tu asistente experto. ¿Qué dudas tienes sobre la clínica o tu salud?\n\n(Escribe *VOLVER* para salir)",
            )
        elif intent == Intent.MANAGE_PROFILE:
            state.transition_to(FSMState.UPDATING_PROFILE)
            state.context["step"] = "menu"
            await self._profile_flow.my_data_handler(state, "")

        elif intent == Intent.MANAGE_REMINDERS:
            user = await self._user_svc.get_user(state.chat_id)
            if user and not user.email:
                msg = "🔔 *Recordatorios por Email*\n\nPara recibir alertas y notificaciones de tus reservas por correo, primero debes registrar tu email.\n\n¿Deseas agregarlo ahora?"
                state.transition_to(FSMState.UPDATING_PROFILE)
                state.context["step"] = "awaiting_value"
                state.context["field"] = "email"
                kb = self._sender.build_inline_keyboard(["Volver al Menú"], state.version)
                await self._sender.send_message(state.chat_id, msg, reply_markup=kb)
            else:
                msg = "🔔 *Recordatorios*\n\nPróximamente podrás gestionar tus notificaciones aquí."
                kb = self._sender.build_inline_keyboard(["Volver al Menú"], state.version)
                await self._sender.send_message(state.chat_id, msg, reply_markup=kb)

        else:
            menu_text = "🌟 *[A] Bienvenido al Sistema de Reservas Titanium*\n\n¿En qué puedo ayudarte hoy?"
            options = [
                "Agendar hora",
                "Mis horas",
                "Cancelar hora",
                "Reagendar hora",
                "Reporte",
                "Recordatorios",
                "Información",
                "Mis datos",
            ]
            kb = self._sender.build_inline_keyboard(options, state.version)
            await self._sender.send_message(state.chat_id, menu_text, reply_markup=kb)

    def register(self, state: FSMState, handler: HandlerType) -> None:
        self._handlers[state] = handler

    async def route(self, state: ConversationState, text: str) -> None:
        payload = decode(text)
        if payload is not None:
            if payload.version != state.version:
                logger.info(
                    "Stale callback discarded", 
                    chat_id=state.chat_id, 
                    payload_version=payload.version, 
                    state_version=state.version
                )
                return
            text = payload.value

        text_lower = text.strip().lower()
        
        if text_lower in ["/start", "home"]:
            logger.info(f"Global {text_lower} received, resetting state", chat_id=state.chat_id)
            
            await self._db.execute("UPDATE outbox_messages SET status = 'CANCELLED' WHERE chat_id =  AND status = 'PENDING'", state.chat_id)

            if text_lower == "home" and state.state == FSMState.IDLE and state.version > 0:
                return

            state.transition_to(FSMState.IDLE)
            state.context = {}
            state.booking_draft = {}
            await self._idle_handler(state, "")
            return

        if text_lower == "cancel":
            if state.state == FSMState.IDLE:
                return
            await self._sender.send_message(state.chat_id, "❌ Operación cancelada. Volviendo al inicio.")
            state.transition_to(FSMState.IDLE)
            state.context = {}
            state.booking_draft = {}
            await self._idle_handler(state, "")
            return
            
        if text_lower == "back":
            if state.state == FSMState.IDLE:
                return
            if state.state == FSMState.SELECTING_DOCTOR:
                state.transition_to(FSMState.SELECTING_SPECIALTY)
                state.context = {}
                state.booking_draft.pop("specialty_id", None)
                state.booking_draft.pop("specialty_name", None)
                state.context["preflight"] = {"intent": Intent.BOOK_APPOINTMENT}
                await self._idle_handler(state, "")
                return
            elif state.state == FSMState.SELECTING_TIME:
                state.transition_to(FSMState.SELECTING_DOCTOR)
                state.context = {}
                state.booking_draft.pop("doctor_id", None)
                state.booking_draft.pop("doctor_name", None)
                await self._booking_flow.selecting_specialty_handler(state, state.booking_draft.get("specialty_name", ""))
                return
            elif state.state == FSMState.CONFIRMING_BOOKING:
                state.transition_to(FSMState.SELECTING_TIME)
                state.context = {}
                state.booking_draft.pop("slot_id", None)
                state.booking_draft.pop("slot_time", None)
                await self._booking_flow.selecting_doctor_handler(state, state.booking_draft.get("doctor_name", ""))
                return
            else:
                state.transition_to(FSMState.IDLE)
                state.context = {}
                state.booking_draft = {}
                await self._idle_handler(state, "")
                return

        handler = self._handlers.get(state.state)
        if handler:
            await handler(state, text)
        else:
            pass


# Temporary singleton for backward compatibility until Phase 9
from app.services.booking_service import booking_service
from app.services.user_service import user_service
from app.telegram.sender import telegram_sender
from app.db.repositories.booking_repo import booking_repo
from app.db.connection import db_client

fsm_router = FSMRouter(
    booking_service=booking_service,
    user_service=user_service,
    sender=telegram_sender,
    booking_repo=booking_repo,
    db=db_client
)


async def idle_handler(state, text):
    return await fsm_router._idle_handler(state, text)
