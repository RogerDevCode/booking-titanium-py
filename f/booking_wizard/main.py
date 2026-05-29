# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "email-validator>=2.2.0",
#   "asyncpg>=0.30.0",
#   "cryptography>=48.0.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "redis>=7.4.0",
#   "typing-extensions>=4.12.0"
# ]
# ///
from __future__ import annotations

import asyncio
import re
import traceback
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel

from ..internal._booking_utils import get_active_booking_for_provider

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Multi-step appointment booking flow (availability → confirmation → creation)
# DB Tables Used  : bookings, providers, clients, services, provider_schedules
# Concurrency Risk: YES — booking creation uses GIST constraint
# GCal Calls      : NO — handled by async sync
# Idempotency Key : YES — deterministic key used
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates parameters
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._wizard_logic import WizardRepository, WizardUI
from ._wizard_models import InputSchema, StepView, WizardState

MODULE = "booking_wizard"


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"invalid_input: {e}") from e

    conn = await create_db_client()
    try:
        # Determine Tenant
        tenant_id: str | None = input_data.provider_id
        if not tenant_id and input_data.wizard_state:
            tenant_id = str(input_data.wizard_state.get("client_id", ""))

        if not tenant_id:
            raise RuntimeError("authentication_error: tenant_id_required")

        # 2. Execute within Tenant Context
        async def operation() -> dict[str, object]:
            repo = WizardRepository(conn)

            # Initial state
            raw_state = input_data.wizard_state or {}
            state = WizardState(
                step=int(raw_state.get("step", 0)),  # type: ignore[call-overload]
                client_id=str(raw_state.get("client_id", "")),
                chat_id=str(raw_state.get("chat_id", "")),
                selected_date=str(raw_state.get("selected_date")) if raw_state.get("selected_date") else None,
                selected_time=str(raw_state.get("selected_time")) if raw_state.get("selected_time") else None,
            )

            # Resolve Service Duration
            duration = 30
            if input_data.service_id:
                d = await repo.get_service_duration(input_data.service_id)
                if d:
                    duration = d

            # Resolve Provider Timezone
            provider_tz = "UTC"
            if input_data.provider_id:
                provider_tz = await repo.get_provider_tz(input_data.provider_id)

            view: StepView | None = None
            action = input_data.action

            if action == "start":
                view = WizardUI.build_date_selection(state, 0, provider_tz)

            elif action == "select_date":
                if input_data.user_input and "Semana" in input_data.user_input:
                    offset = 7 if "siguiente" in input_data.user_input else 0
                    view = WizardUI.build_date_selection(state, offset, provider_tz)
                else:
                    match = re.search(r"(\d{4}-\d{2}-\d{2})", input_data.user_input or "")
                    d_str = match.group(1) if match else state.selected_date
                    if d_str:
                        state.selected_date = d_str
                        slots = await repo.get_available_slots(input_data.provider_id or "", d_str, duration)
                        view = WizardUI.build_time_selection(state, slots)
                    else:
                        view = WizardUI.build_date_selection(state, 0, provider_tz)

            elif action == "select_time":
                state.selected_time = input_data.user_input
                names = await repo.get_names(input_data.provider_id or "", input_data.service_id or "")
                if not names:
                    raise RuntimeError("names_not_found")
                view = WizardUI.build_confirmation(state, names["provider"], names["service"])

            elif action == "confirm":
                if not input_data.provider_id or not input_data.service_id:
                    raise RuntimeError("missing_data_for_confirm")

                # Check for duplicate active booking (Rule BE-02)
                active_booking = await get_active_booking_for_provider(conn, state.client_id, input_data.provider_id)
                if active_booking:
                    st = active_booking["start_time"]
                    fmt_time = st.strftime("%d/%m %H:%M") if isinstance(st, datetime) else str(st)

                    target_date = state.selected_date
                    target_time = state.selected_time

                    ars_callback = f"ars:{active_booking['booking_id']}:{target_date}:{target_time}"

                    message = (
                        f"\u2139\ufe0f *Ya tienes una hora activa*\n\n"
                        f"Tienes una hora con *{active_booking['provider_name']}* para el *{fmt_time}*.\n\n"
                        f"\u00bfDeseas reagendar esa hora para el nuevo horario "
                        f"(*{target_date}* a las *{target_time}*) o prefieres volver al men\u00fa?"
                    )

                    reply_kb = [
                        [{"text": "\ud83d\udd04 S\u00ed, reagendar hora", "callback_data": ars_callback}],
                        ["\u00ab Volver al men\u00fa"],
                    ]

                    return {
                        "message": message,
                        "reply_keyboard": reply_kb,
                        "new_state": state,
                        "force_reply": False,
                        "reply_placeholder": "",
                        "is_complete": False,
                    }

                await repo.create_booking(
                    state.client_id,
                    input_data.provider_id,
                    input_data.service_id,
                    state.selected_date or "",
                    state.selected_time or "",
                    input_data.timezone,
                    duration,
                )

                state.step = 99
                view = {
                    "message": "✅ *¡Hora confirmada!*\n\nTu hora ha sido agendada. Recibirás un recordatorio.",
                    "reply_keyboard": [["« Volver al menú"]],
                    "new_state": state,
                    "force_reply": False,
                    "reply_placeholder": "",
                }

            elif action == "cancel":
                state.step = 0
                view = {
                    "message": "❌ Proceso cancelado. ¿En qué más puedo ayudarte?",
                    "reply_keyboard": [["📅 Agendar cita", "📋 Mis citas"]],
                    "new_state": state,
                    "force_reply": False,
                    "reply_placeholder": "",
                }

            elif action == "back":
                prev_step = max(0, state.step - 1)
                state.step = prev_step
                view = WizardUI.build_date_selection(state, 0, provider_tz)

            if not view:
                raise RuntimeError("no_view_generated")

            res: dict[str, object] = {
                "message": view["message"],
                "reply_keyboard": view["reply_keyboard"],
                "force_reply": view["force_reply"],
                "reply_placeholder": view["reply_placeholder"],
                "wizard_state": view["new_state"].model_dump(),
                "is_complete": view["new_state"].step == 99,
            }
            return res

        return await with_tenant_context(conn, tenant_id, operation)

    except Exception as e:
        log("Wizard Orchestrator Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result: Any = asyncio.run(_main_async(validated.model_dump()))

        if isinstance(result, BaseModel):
            return cast("dict[str, object]", result.model_dump())
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
