from typing import Callable
from app.domain.protocols import BookingServiceProtocol, TelegramSenderProtocol, BookingRepositoryProtocol
from app.core.logging import logger
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from datetime import datetime
from zoneinfo import ZoneInfo

CHILE_TZ = ZoneInfo("America/Santiago")

def format_chile_time(dt: datetime) -> str:
    local_time = dt.astimezone(CHILE_TZ)
    days = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
    day_str = days[local_time.weekday()]
    return f"{day_str} {local_time.strftime('%d/%m %H:%M')}"

def format_confirmation_date_time(iso_str: str) -> tuple[str, str]:  # type: ignore
    dt = datetime.fromisoformat(iso_str).astimezone(CHILE_TZ)
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    day_str = days[dt.weekday()]
    month_str = months[dt.month - 1]
    
    date_formatted = f"{day_str} {dt.day} de {month_str} de {dt.year}"
    time_formatted = dt.strftime("%H:%M")
    
    return date_formatted, time_formatted

class BookingFlowHandlers:
    def __init__(self, booking_service: BookingServiceProtocol, sender: TelegramSenderProtocol, booking_repo: BookingRepositoryProtocol, on_idle: Callable) -> None:
        self._svc = booking_service
        self._sender = sender
        self._repo = booking_repo
        self._on_idle = on_idle

    async def selecting_specialty_handler(self, state: ConversationState, text: str):
        """Handles the selection of a specialty."""
        logger.info("Handling selecting_specialty", chat_id=state.chat_id, text=text)

        specialties = await self._svc.get_all_specialties()
        selected_specialty = None

        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(specialties):
                selected_specialty = specialties[idx]
        else:
            for s in specialties:
                if s.name.lower() in text.lower():
                    selected_specialty = s
                    break

        if not selected_specialty:
            # Re-render with buttons
            await self._render_specialties_menu(state)
            return

        state.booking_draft["specialty_id"] = selected_specialty.id
        state.booking_draft["specialty_name"] = selected_specialty.name
        state.transition_to(FSMState.SELECTING_DOCTOR)

        doctors = await self._svc.get_providers_by_specialty(selected_specialty.id)
        if not doctors:
            await self._sender.send_message(
                state.chat_id,
                f"No hay doctores disponibles para {selected_specialty.name} por ahora.",
            )
            state.transition_to(FSMState.IDLE)
            return

        state.context["items"] = [{"id": d.id, "name": d.name} for d in doctors]
        state.context["page"] = 0
        await self._render_doctors_menu(state)


    async def _render_specialties_menu(self, state: ConversationState):
        specialties = await self._svc.get_all_specialties()
        msg = "🏥 *[B] Selecciona una especialidad:*\n\n"
        options = []
        for i, s in enumerate(specialties, 1):
            msg += f"{i}️⃣ {s.name}\n"
            options.append(s.name)
    
        kb = self._sender.build_inline_keyboard(options, state.version, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)


    async def _render_doctors_menu(self, state: ConversationState):
        items = state.context.get("items", [])
        specialty_name = state.booking_draft.get("specialty_name", "")
        msg = f"👨‍⚕️ *[C] Seleccionar Médico*\n\nHas elegido *{specialty_name}*. ¿Con qué doctor te gustaría atenderte?"
    
        page = state.context.get("page", 0)
        page_size = 5
        start = page * page_size
        page_items = items[start:start+page_size]
        total_pages = (len(items) + page_size - 1) // page_size
    
        kb = self._sender.build_paginated_keyboard(
            [d["name"] for d in page_items], 
            state.version,
            start_idx=start, 
            page=page, 
            total_pages=total_pages, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)


    async def selecting_doctor_handler(self, state: ConversationState, text: str):
        """Handles the selection of a doctor."""
        logger.info("Handling selecting_doctor", chat_id=state.chat_id, text=text)

        if text in ["page_prev", "page_next"]:
            page = state.context.get("page", 0)
            page = page + 1 if text == "page_next" else max(0, page - 1)
            state.context["page"] = page
            await self._render_doctors_menu(state)
            return

        items = state.context.get("items", [])
        selected_doctor_id = None
        selected_doctor_name = None

        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(items):
                selected_doctor_id = items[idx]["id"]
                selected_doctor_name = items[idx]["name"]
        else:
            for item in items:
                if item["name"].lower() in text.lower():
                    selected_doctor_id = item["id"]
                    selected_doctor_name = item["name"]
                    break

        if not selected_doctor_id:
            await self._render_doctors_menu(state)
            return

        state.booking_draft["doctor_id"] = selected_doctor_id
        state.booking_draft["doctor_name"] = selected_doctor_name

        slots = await self._svc.get_available_slots(selected_doctor_id)
        if not slots:
            msg = (
                f"El Dr. {selected_doctor_name} no tiene horas disponibles próximamente.\n\n"
                "¿Deseas anotarte en la lista de espera para que te avisemos apenas se libere un cupo?"
            )
            kb = self._sender.build_inline_keyboard(["Sí, anotarme", "No, volver"], state.version)
            state.transition_to(FSMState.JOINING_WAITLIST)
            await self._sender.send_message(state.chat_id, msg, reply_markup=kb)
            return

        state.transition_to(FSMState.SELECTING_TIME)
        state.context["items"] = [
            {"id": s.id, "time": s.start_time.isoformat()} for s in slots
        ]
        state.context["page"] = 0
        await self._render_time_menu(state)


    async def _render_time_menu(self, state: ConversationState):
        items = state.context.get("items", [])
        doctor_name = state.booking_draft.get("doctor_name", "")
        msg = f"📅 *[D] Seleccionar Horario*\n\nEl Dr. *{doctor_name}* tiene estas horas disponibles:"
    
        page = state.context.get("page", 0)
        page_size = 5
        start = page * page_size
        page_items = items[start:start+page_size]
        total_pages = (len(items) + page_size - 1) // page_size
    
        kb = self._sender.build_paginated_keyboard(
            [format_chile_time(datetime.fromisoformat(s['time'])) for s in page_items],
            state.version,
            start_idx=start,
            page=page,
            total_pages=total_pages, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)


    async def selecting_time_handler(self, state: ConversationState, text: str):
        """Handles the selection of a time slot."""
        logger.info("Handling selecting_time", chat_id=state.chat_id, text=text)

        if text in ["page_prev", "page_next"]:
            page = state.context.get("page", 0)
            page = page + 1 if text == "page_next" else max(0, page - 1)
            state.context["page"] = page
            await self._render_time_menu(state)
            return

        items = state.context.get("items", [])
        selected_slot_id = None
        selected_time_str = None

        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(items):
                selected_slot_id = items[idx]["id"]
                selected_time_str = items[idx]["time"]

        if not selected_slot_id:
            await self._render_time_menu(state)
            return

        state.booking_draft["slot_id"] = selected_slot_id
        state.booking_draft["slot_time"] = selected_time_str
        state.transition_to(FSMState.CONFIRMING_BOOKING)

        date_formatted, time_formatted = format_confirmation_date_time(selected_time_str)  # type: ignore
        msg = (
            "📝 *[E] Confirma tu reserva*\n\n"
            f"🏥 Especialidad: {state.booking_draft['specialty_name']}\n"
            f"👨‍⚕️ Profesional: {state.booking_draft['doctor_name']}\n"
            f"📅 Fecha: {date_formatted}\n"
            f"⏰ Hora: {time_formatted}\n\n"
            "¿Deseas confirmar esta reserva? (Responde *SÍ* o *NO*)"
        )
        kb = self._sender.build_inline_keyboard(["SÍ, confirmar", "NO, cancelar"], state.version, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)


    async def confirming_booking_handler(self, state: ConversationState, text: str):
        """Finalizes the booking."""
        if text.lower() in ["si", "sí", "confirmar", "ok", "1"]:
            try:
                await self._svc.create_booking(
                    state.chat_id, state.booking_draft["slot_id"]
                )
                await self._sender.send_message(
                    state.chat_id,
                    "🎉 ¡Reserva confirmada con éxito!",
                )
                state.transition_to(FSMState.IDLE)
                state.booking_draft = {}
                state.context = {}
                await self._on_idle(state, "")
            except Exception as e:
                logger.error("Booking creation failed", error=str(e))
                await self._sender.send_message(
                    state.chat_id,
                    "❌ Lo siento, hubo un problema al confirmar tu hora. Por favor intenta de nuevo.",
                )
                state.transition_to(FSMState.IDLE)
                state.booking_draft = {}
                state.context = {}
                await self._on_idle(state, "")
        elif text.lower() in ["no", "cancelar", "2"]:
            await self._sender.send_message(
                state.chat_id, "Reserva cancelada. Volviendo al menú principal."
            )
            state.transition_to(FSMState.IDLE)
            state.booking_draft = {}
            state.context = {}
            await self._on_idle(state, "")

    async def joining_waitlist_handler(self, state: ConversationState, text: str):
        """Handles joining the waitlist."""
        if text.lower() in ["si", "sí", "anotarme", "1", "sí, anotarme"]:
            provider_id = state.booking_draft.get("doctor_id")
        
            # We need the user DB ID. The chat_id is the user_id in Telegram.
            # But wait, our DB uses the chat_id as the primary key id in users table!
            try:
                await self._svc.add_to_waitlist(state.chat_id, provider_id)  # type: ignore
            
                await self._sender.send_message(
                    state.chat_id,
                    "✅ ¡Perfecto! Te hemos anotado en la lista de espera. "
                    "Te avisaremos inmediatamente si se libera una hora."
                )
            except Exception as e:
                logger.error("Error joining waitlist", error=str(e), chat_id=state.chat_id)
                await self._sender.send_message(
                    state.chat_id,
                    "❌ Hubo un problema al anotarte en la lista. Por favor intenta más tarde."
                )
            
            state.transition_to(FSMState.IDLE)
            state.booking_draft = {}
            state.context = {}
            await self._on_idle(state, "")
        
        elif text.lower() in ["no", "volver", "2", "no, volver"]:
            await self._sender.send_message(
                state.chat_id, "De acuerdo. Volviendo al menú principal."
            )
            state.transition_to(FSMState.IDLE)
            state.booking_draft = {}
            state.context = {}
            await self._on_idle(state, "")
        else:
            # Re-render confirmation
            date_formatted, time_formatted = format_confirmation_date_time(state.booking_draft['slot_time'])  # type: ignore
            msg = (
                "✅ *Confirma tu reserva*\n\n"
                f"🏥 Especialidad: {state.booking_draft['specialty_name']}\n"
                f"👨‍⚕️ Profesional: {state.booking_draft['doctor_name']}\n"
                f"📅 Fecha: {date_formatted}\n"
                f"⏰ Hora: {time_formatted}\n\n"
                "¿Deseas confirmar esta reserva?"
            )
            kb = self._sender.build_inline_keyboard(["SÍ, confirmar", "NO, cancelar"], state.version, include_nav=True)
            await self._sender.send_message(state.chat_id, msg, reply_markup=kb)


    async def cancellation_handler(self, state: ConversationState, text: str):
        """Handles the cancellation flow."""
        logger.info("Handling cancellation", chat_id=state.chat_id, text=text)

        if text in ["page_prev", "page_next"]:
            page = state.context.get("page", 0)
            page = page + 1 if text == "page_next" else max(0, page - 1)
            state.context["page"] = page
            await self._render_cancellation_menu(state)
            return

        bookings = await self._svc.get_user_bookings(state.chat_id)

        if not bookings:
            await self._sender.send_message(
                state.chat_id, "No tienes citas activas para cancelar."
            )
            state.transition_to(FSMState.IDLE)
            await self._on_idle(state, "")
            return

        # Initialize context items if empty
        if "items" not in state.context:
            state.context["items"] = [
                {
                    "id": b.id,
                    "doctor": b.provider_name,
                    "specialty": b.specialty_name,
                    "time": format_chile_time(b.start_time),
                }
                for b in bookings
            ]
            state.context["page"] = 0

        items = state.context["items"]

        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(items):
                selected_booking_id = items[idx]["id"]
                selected_specialty_name = items[idx]["specialty"]
                slot_id_cancelled = await self._svc.cancel_booking(
                    state.chat_id, selected_booking_id
                )
                if slot_id_cancelled:
                    await self._sender.send_message(
                        state.chat_id,
                        f"✅ Tu cita de *{selected_specialty_name}* ha sido cancelada.",
                    )
                
                    # Trigger waitlist
                    try:
                        from arq.connections import RedisSettings
                        from app.core.config import settings
                        from arq import create_pool
                        pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
                        provider_id = await self._svc.get_provider_id_by_slot(slot_id_cancelled)
                        if provider_id:
                            await pool.enqueue_job("notify_waitlist", str(slot_id_cancelled), str(provider_id))
                        await pool.close()
                    except Exception as e:
                        logger.error("Failed to enqueue waitlist on cancel", error=str(e))
                else:
                    await self._sender.send_message(
                        state.chat_id,
                        "❌ No se pudo cancelar la cita. Por favor intenta más tarde.",
                    )
                state.transition_to(FSMState.IDLE)
                state.context = {}
                await self._on_idle(state, "")
                return

        await self._render_cancellation_menu(state)


    async def _render_cancellation_menu(self, state: ConversationState):
        items = state.context.get("items", [])
        msg = "❌ *[G] Cancelar Cita*\n\n¿Cuál de estas citas deseas cancelar?"
    
        page = state.context.get("page", 0)
        page_size = 5
        start = page * page_size
        page_items = items[start:start+page_size]
        total_pages = (len(items) + page_size - 1) // page_size
    
        options = []
        for b in page_items:
            options.append(f"{b['specialty']} - {b['time']}")
        
        kb = self._sender.build_paginated_keyboard(
            options,
            state.version,
            start_idx=start,
            page=page,
            total_pages=total_pages, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)


    async def reschedule_handler(self, state: ConversationState, text: str):
        """Handles the rescheduling flow."""
        logger.info("Handling rescheduling", chat_id=state.chat_id, text=text)

        if text in ["page_prev", "page_next"]:
            page = state.context.get("page", 0)
            page = page + 1 if text == "page_next" else max(0, page - 1)
            state.context["page"] = page
            step = state.context.get("step", "select_booking")
            if step == "select_booking":
                await self._render_reschedule_bookings_menu(state)
            elif step == "select_new_slot":
                await self._render_reschedule_slots_menu(state)
            return

        bookings = await self._svc.get_user_bookings(state.chat_id)

        if not bookings:
            await self._sender.send_message(
                state.chat_id, "No tienes citas activas para reagendar."
            )
            state.transition_to(FSMState.IDLE)
            await self._on_idle(state, "")
            return

        step = state.context.get("step", "select_booking")

        if step == "select_booking":
            if "items" not in state.context:
                state.context["items"] = [
                    {
                        "id": b.id,
                        "specialty": b.specialty_name,
                        "doctor": b.provider_name,
                        "time": format_chile_time(b.start_time),
                    }
                    for b in bookings
                ]
                state.context["page"] = 0

            items = state.context["items"]

            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(items):
                    selected_booking_id = items[idx]["id"]
                    state.booking_draft["old_booking_id"] = selected_booking_id
                    state.booking_draft["doctor_id"] = await self._get_doctor_id_for_booking(
                        selected_booking_id
                    )
                    state.context["step"] = "select_new_slot"

                    slots = await self._svc.get_available_slots(
                        state.booking_draft["doctor_id"]
                    )
                    if not slots:
                        await self._sender.send_message(
                            state.chat_id,
                            "No hay otras horas disponibles para este doctor actualmente.",
                        )
                        state.transition_to(FSMState.IDLE)
                        state.context = {}
                        await self._on_idle(state, "")
                        return

                    state.transition_to(FSMState.SELECTING_TIME)
                    state.context["items"] = [
                        {"id": s.id, "time": s.start_time.isoformat()} for s in slots
                    ]
                    state.context["page"] = 0
                    await self._render_reschedule_slots_menu(state)
                    return

            await self._render_reschedule_bookings_menu(state)

        elif step == "select_new_slot":
            items = state.context.get("items", [])
            selected = False
            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(items):
                    selected = True
                    new_slot_id = items[idx]["id"]
                    try:
                        new_booking, old_slot_id = await self._svc.reschedule_booking(
                            state.chat_id,
                            state.booking_draft["old_booking_id"],
                            new_slot_id,
                        )
                        await self._sender.send_message(
                            state.chat_id,
                            "✅ Hora reagendada con éxito.",
                        )
                    
                        # Trigger waitlist for the old slot
                        try:
                            from arq.connections import RedisSettings
                            from app.core.config import settings
                            from arq import create_pool
                            pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
                            provider_id = await self._svc.get_provider_id_by_slot(old_slot_id)
                            if provider_id:
                                await pool.enqueue_job("notify_waitlist", str(old_slot_id), str(provider_id))
                            await pool.close()
                        except Exception as e:
                            logger.error("Failed to enqueue waitlist on reschedule", error=str(e))
                    except Exception as e:
                        logger.error("Rescheduling failed", error=str(e))
                        await self._sender.send_message(
                            state.chat_id,
                            "❌ No se pudo reagendar. Por favor intenta más tarde.",
                        )

                    state.transition_to(FSMState.IDLE)
                    state.context = {}
                    state.booking_draft = {}
                    await self._on_idle(state, "")
        
            if not selected:
                await self._render_reschedule_slots_menu(state)
                return


    async def _render_reschedule_bookings_menu(self, state: ConversationState):
        items = state.context.get("items", [])
        msg = "🔄 *[H] Reagendar Cita*\n\n¿Cuál de estas citas deseas cambiar?"
    
        page = state.context.get("page", 0)
        page_size = 5
        start = page * page_size
        page_items = items[start:start+page_size]
        total_pages = (len(items) + page_size - 1) // page_size
    
        options = []
        for b in page_items:
            options.append(f"{b['specialty']} - {b['time']}")
        
        kb = self._sender.build_paginated_keyboard(
            options,
            state.version,
            start_idx=start,
            page=page,
            total_pages=total_pages, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)


    async def _render_reschedule_slots_menu(self, state: ConversationState):
        items = state.context.get("items", [])
        msg = "🔄 *[H] Selecciona un nuevo horario:*"
    
        page = state.context.get("page", 0)
        page_size = 5
        start = page * page_size
        page_items = items[start:start+page_size]
        total_pages = (len(items) + page_size - 1) // page_size
    
        kb = self._sender.build_paginated_keyboard(
            [format_chile_time(datetime.fromisoformat(s['time'])) for s in page_items],
            state.version,
            start_idx=start,
            page=page,
            total_pages=total_pages, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)

    async def _get_doctor_id_for_booking(self, booking_id: int) -> str:
        return await self._repo.get_provider_id_by_booking(booking_id)

    async def my_bookings_handler(self, state: ConversationState, text: str):
        """Shows the user's active bookings."""
        logger.info("Handling viewing_bookings", chat_id=state.chat_id, text=text)

        if text == "1": # Cancelar
            state.transition_to(FSMState.CANCELLING_BOOKING)
            await self.cancellation_handler(state, "")
            return
        elif text == "2": # Reagendar
            state.transition_to(FSMState.RESCHEDULING_BOOKING)
            await self.reschedule_handler(state, "")
            return
        elif text == "3" or text.lower() in ["volver", "menu"]:
            state.transition_to(FSMState.IDLE)
            await self._on_idle(state, "")
            return

        bookings = await self._svc.get_user_bookings(state.chat_id)

        if not bookings:
            await self._sender.send_message(
                state.chat_id, "No tienes citas activas actualmente."
            )
            state.transition_to(FSMState.IDLE)
            await self._on_idle(state, "")
            return

        msg = "📅 *[F] Tus próximas citas:*\n\n"
        options = []
        for i, b in enumerate(bookings, 1):
            date_str = format_chile_time(b.start_time)
            msg += f"{i}️⃣ *{b.specialty_name}*\n   📅 {date_str} - {b.provider_name}\n\n"
            options.append(f"Gestionar #{b.id}")

        kb = self._sender.build_inline_keyboard(["Cancelar Cita", "Reagendar Cita"], state.version, include_nav=True)
        await self._sender.send_message(state.chat_id, msg, reply_markup=kb)
