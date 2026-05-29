import traceback
from datetime import datetime
from typing import Any, cast

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ..services.booking._booking_models import BookingCancelRequest, BookingRescheduleRequest, BookingResult
from ..services.booking.core import cancel_booking, reschedule_booking
from ..services.booking.repo import PgBookingRepo
from ._callback_logic import confirm_booking
from ._callback_models import ActionContext, ActionHandler, ActionResult


class ConfirmHandler:
    async def handle(self, context: ActionContext) -> ActionResult:
        # Legacy/edge-case: bookings are now created as confirmed by default.
        conn = await create_db_client()
        try:

            async def operation() -> bool:
                return await confirm_booking(conn, context["booking_id"], context["client_id"])

            success = await with_tenant_context(conn, context["tenantId"], operation)

            if success:
                return {
                    "responseText": "✅ Hora confirmada",
                    "followUpText": "Tu hora ha sido confirmada. ¡Te esperamos!",
                }
            else:
                return {
                    "responseText": "❌ No se pudo confirmar",
                    "followUpText": "No pudimos confirmar tu hora. La hora no existe o ya fue modificada. Contacta a soporte.",  # noqa: E501
                }
        except Exception as e:
            log("CONFIRM_CALLBACK_FAILED", error=str(e), traceback=traceback.format_exc(), module="callback_router")
            return {
                "responseText": "❌ No se pudo confirmar",
                "followUpText": "No pudimos confirmar tu hora. Motivo: error interno. Contacta a soporte si necesitas ayuda.",  # noqa: E501
            }
        finally:
            await conn.close()


class CancelHandler:
    async def handle(self, context: ActionContext) -> ActionResult:
        # Instead of cancelling immediately, show reasons
        booking_id = context["booking_id"]
        sid = context.get("session_id")
        suffix = f"|{sid}" if sid else ""
        return {
            "responseText": "¿Por qué deseas cancelar tu hora? 🧐",
            "followUpText": None,
            "inlineButtons": [
                [{"text": "📅 Cambiar de fecha/hora", "callback_data": f"cxr:{booking_id}:CH{suffix}"}],
                [{"text": "🚨 Emergencia personal", "callback_data": f"cxr:{booking_id}:EM{suffix}"}],
                [{"text": "❌ Ya no lo necesito", "callback_data": f"cxr:{booking_id}:NN{suffix}"}],
                [{"text": "✏️ Error al agendar", "callback_data": f"cxr:{booking_id}:ER{suffix}"}],
            ],
        }


class CancelReasonHandler:
    async def handle(self, context: ActionContext) -> ActionResult:
        reason_code = context.get("reason_code") or "ER"
        reason_map = {
            "CH": "Cambio de fecha/hora",
            "EM": "Emergencia personal",
            "NN": "Ya no lo necesito",
            "ER": "Error al agendar",
        }
        reason_text = reason_map.get(reason_code, "Otro")

        conn = await create_db_client()
        try:
            repo = PgBookingRepo(conn)
            req = BookingCancelRequest(
                booking_id=context["booking_id"],
                actor="client",
                actor_id=context["client_id"],
                reason=f"Motivo: {reason_text}",
            )

            async def operation_cancel() -> BookingResult:
                return await cancel_booking(req, repo)

            await with_tenant_context(conn, context["tenantId"], operation_cancel)

            cancel_count = 0
            if context.get("client_id"):
                try:
                    val = await conn.fetchval(
                        """
                        SELECT COUNT(*)::int
                        FROM bookings
                        WHERE client_id = $1::uuid
                          AND status = 'cancelled'
                          AND updated_at >= NOW() - INTERVAL '30 days'
                        """,
                        context["client_id"],
                    )
                    if isinstance(val, int):
                        cancel_count = val
                    elif isinstance(val, str | bytes) and val.isdigit():
                        cancel_count = int(val)
                except Exception as ex:
                    log("QUERY_CANCEL_COUNT_FAILED", error=str(ex), module="callback_router")

            follow_up = f"Tu hora ha sido cancelada (Motivo: {reason_text})."
            if cancel_count >= 2:
                follow_up += (
                    "\n\n⚠️ Notamos que has cancelado varias horas recientemente. "
                    "Si necesitas ayuda o prefieres asistencia personalizada, "
                    "puedes comunicarte directamente con soporte técnico escribiendo a soporte@ejemplo.com."
                )

            if reason_code == "CH":
                follow_up += "\n\n🔄 ¿Te gustaría agendar una nueva hora ahora mismo?"

            sid = context.get("session_id")
            suffix = f"|{sid}" if sid else ""
            res_obj: ActionResult = {
                "responseText": "✅ Hora cancelada",
                "followUpText": follow_up,
            }
            if reason_code == "CH":
                res_obj["inlineButtons"] = [
                    [{"text": "📅 Agendar nueva hora", "callback_data": f"cmd:agendar{suffix}"}]
                ]
            return res_obj
        except Exception as e:
            log(
                "CANCEL_REASON_CALLBACK_FAILED",
                error=str(e),
                traceback=traceback.format_exc(),
                module="callback_router",
            )
            return {
                "responseText": "❌ No se pudo cancelar",
                "followUpText": "No pudimos procesar la cancelación. Contacta a soporte.",
            }
        finally:
            await conn.close()


class AcknowledgeHandler:
    async def handle(self, context: ActionContext) -> ActionResult:
        return {"responseText": "Entendido", "followUpText": None}


class AutoRescheduleHandler:
    async def handle(self, context: ActionContext) -> ActionResult:
        booking_id = context["booking_id"]
        date = context.get("date")
        time = context.get("time")

        if not date or not time:
            return {
                "responseText": "⚠️ Error de datos",
                "followUpText": "No se pudo obtener la nueva fecha/hora para reagendar. Intenta manualmente.",
            }

        conn = await create_db_client()
        try:
            repo = PgBookingRepo(conn)

            # Note: The original logic didn't provide end_time.
            # We assume a 30 min default duration here, ideally it should fetch service duration.
            start_dt = datetime.fromisoformat(f"{date}T{time}:00".replace("Z", "+00:00"))
            import datetime as dt

            end_dt = start_dt + dt.timedelta(minutes=30)

            req = BookingRescheduleRequest(
                booking_id=booking_id,
                new_start_time=start_dt,
                new_end_time=end_dt,
                actor="client",
                actor_id=context["client_id"],
            )

            async def operation_reschedule() -> BookingResult:
                return await reschedule_booking(req, repo)

            await with_tenant_context(conn, context["tenantId"], operation_reschedule)
            err = None
        except Exception as e:
            log(
                "AUTORESCHEDULE_CALLBACK_FAILED",
                error=str(e),
                traceback=traceback.format_exc(),
                module="callback_router",
            )
            err = str(e)
        finally:
            await conn.close()

        if err:
            return {
                "responseText": "❌ No se pudo reagendar",
                "followUpText": f"Hubo un problema al reagendar: {err}",
            }

        return {
            "responseText": "✅ Reagendada con éxito",
            "followUpText": f"Tu hora ha sido movida al {date} a las {time}.",
        }


class RescheduleCitaHandler:
    async def handle(self, context: ActionContext) -> ActionResult:
        # User clicked '🔄 Reagendar Ref: SHORT_ID'.
        # We need to load their booking, find provider_id, specialty_id,
        # and transition their FSM state to selecting_time.
        booking_id = context["booking_id"]
        chat_id = context["chat_id"]
        session_id = context.get("session_id")

        from ..internal._db_client import create_db_client as _factory
        from ..internal._wmill_adapter import run_script
        from ..internal.booking_fsm import DraftBooking
        from ..internal.booking_fsm import build_time_slot_keyboard
        from ..internal.booking_prefetch.main import _fetch_slots_for_doctor

        conn = await _factory()
        try:
            row = await conn.fetchrow(
                """
                SELECT 
                    b.provider_id::text AS provider_id,
                    p.name AS provider_name,
                    p.specialty_id::text AS specialty_id,
                    sp.name AS specialty_name
                FROM bookings b
                JOIN providers p ON p.provider_id = b.provider_id
                JOIN specialties sp ON sp.specialty_id = p.specialty_id
                WHERE b.booking_id = $1::uuid
                LIMIT 1
                """,
                booking_id,
            )
            if not row:
                return {
                    "responseText": "⚠️ Hora no encontrada",
                    "followUpText": "No pudimos encontrar la hora que deseas reagendar.",
                }

            provider_id = str(row["provider_id"])
            provider_name = str(row["provider_name"])
            specialty_id = str(row["specialty_id"])
            specialty_name = str(row["specialty_name"])

            # Fetch slots for doctor
            slots = await _fetch_slots_for_doctor(conn, provider_id)

            # Update FSM State for the conversation
            # FSM state: selecting_time, draft_booking with doctor/specialty
            draft = DraftBooking(
                specialty_id=specialty_id,
                specialty_name=specialty_name,
                doctor_id=provider_id,
                doctor_name=provider_name,
            )

            # Use conversation_update script to update the state in DB
            update_payload: dict[str, object] = {
                "chat_id": chat_id,
                "booking_state": {
                    "name": "selecting_time",
                    "specialtyId": specialty_id,
                    "doctorId": provider_id,
                    "doctorName": provider_name,
                    "items": slots,
                },
                "booking_draft": draft.model_dump(),
            }

            err, _ = run_script("f/internal/conversation_update/main", update_payload)
            if err:
                raise err

            # Build time slot keyboard
            # Transform slots list of dicts to list of TimeSlotItem
            from ..internal.booking_fsm import TimeSlotItem

            slot_items = [
                TimeSlotItem(id=str(s["id"]), label=str(s["label"]), start_time=str(s["start_time"])) for s in slots
            ]
            keyboard = build_time_slot_keyboard(slot_items, session_id=session_id)

            return {
                "responseText": "🔄 Reagendando hora",
                "followUpText": (
                    f"Reagendando tu hora con *{provider_name}* ({specialty_name}).\n\n"
                    "Por favor, selecciona un nuevo horario:"
                ),
                "inlineButtons": cast("list[list[Any]]", keyboard),
            }

        except Exception as e:
            log(
                "RESCHEDULE_CITA_CALLBACK_FAILED",
                error=str(e),
                traceback=traceback.format_exc(),
                module="callback_router",
            )
            return {
                "responseText": "❌ Error al reagendar",
                "followUpText": "Hubo un error al iniciar la reagendación. Intenta más tarde.",
            }
        finally:
            await conn.close()


class TelegramRouter:
    def __init__(self) -> None:
        self.handlers: dict[str, ActionHandler] = {}

    def register(self, action: str, handler: ActionHandler) -> None:
        self.handlers[action] = handler

    async def route(self, action: str, context: ActionContext) -> ActionResult:
        handler = self.handlers.get(action)
        if not handler:
            return {"responseText": "⚠️ Acción no reconocida", "followUpText": None}
        return await handler.handle(context)
