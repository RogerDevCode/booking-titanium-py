from typing import Callable
from app.domain.protocols import BookingRepositoryProtocol, TelegramSenderProtocol
import asyncio
from datetime import datetime
from app.core.logging import logger
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from app.telegram.callback import encode

class ReportFlowHandlers:
    def __init__(self, booking_repo: BookingRepositoryProtocol, sender: TelegramSenderProtocol, on_idle: Callable) -> None:
        self._repo = booking_repo
        self._sender = sender
        self._on_idle = on_idle

    async def report_handler(self, state: ConversationState, text: str):
        logger.info("Handling report flow", chat_id=state.chat_id, text=text)

        # Convert text to standard action
        action = text.lower().strip()

        if action in ["volver", "atras", "salir", "home", "cancelar", "4", "volver al menú", "volver al menu"]:
            state.transition_to(FSMState.IDLE)
            state.context = {}
            await self._on_idle(state, "")
            return

        if action in ["pdf", "generar pdf", "descargar pdf", "3"]:
            await self._sender.send_message(
                state.chat_id, "⏳ *Procesando tu historial médico...* Recibirás el PDF en unos segundos."
            )
            from app.worker.tasks import make_generate_user_report_pdf
            from app.container import build_container
            generate_user_report_pdf = make_generate_user_report_pdf(build_container())
            asyncio.create_task(generate_user_report_pdf(state.chat_id))
            return

        now = datetime.now()
        current_year = state.context.get("report_year", now.year)
        current_month = state.context.get("report_month", now.month)

        if action in ["1", "page_prev", "anterior"]:
            current_month -= 1
            if current_month < 1:
                current_month = 12
                current_year -= 1
        elif action in ["2", "page_next", "siguiente"]:
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

        state.context["report_year"] = current_year
        state.context["report_month"] = current_month

        min_date = datetime(now.year, now.month, 1)
        min_year = min_date.year - 2
        min_month = min_date.month

        bookings = await self._repo.get_history_by_month(state.chat_id, current_year, current_month)

        month_names = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        month_name = month_names[current_month - 1]

        msg = f"📊 *[E] Reporte Médico - {month_name} {current_year}*\n\n"
        if bookings:
            for b in bookings:
                dt_str = b.start_time.strftime("%d/%m/%Y %H:%M")
                status_map = {"CONFIRMED": "🟢", "CANCELLED": "🔴", "PENDING": "🟡", "COMPLETED": "🔵"}
                icon = status_map.get(b.status.value, "⚪")
                msg += f"{icon} *{dt_str}* - {b.specialty_name} con {b.provider_name}\n\n"
        else:
            msg += "No tienes registros médicos en este mes.\n\n"

        kb = []
        nav_row = []
        if current_year > min_year or (current_year == min_year and current_month >= min_month):
            nav_row.append({"text": "⬅️ Anterior", "callback_data": encode(state.version, "select", "1")})
        if current_year < now.year + 1:
            nav_row.append({"text": "Siguiente ➡️", "callback_data": encode(state.version, "select", "2")})
    
        if nav_row:
            kb.append(nav_row)
        
        kb.append([{"text": "📄 Descargar PDF", "callback_data": encode(state.version, "select", "3")}])
        kb.append([{"text": "🏠 Volver al Menú", "callback_data": encode(state.version, "select", "4")}])

        await self._sender.send_message(state.chat_id, msg, reply_markup={"inline_keyboard": kb})

