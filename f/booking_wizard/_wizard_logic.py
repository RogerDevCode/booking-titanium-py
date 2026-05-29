from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, cast

from ..internal.scheduling_engine._scheduling_logic import get_availability

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._wizard_models import StepView, WizardState

# Constants
START_HOUR: Final[int] = 8
END_HOUR: Final[int] = 18


class DateUtils:
    @staticmethod
    def format_es(date_str: str) -> str:
        dt = date.fromisoformat(date_str)
        days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        months = [
            "Enero",
            "Febrero",
            "Marzo",
            "Abril",
            "Mayo",
            "Junio",
            "Julio",
            "Agosto",
            "Septiembre",
            "Octubre",
            "Noviembre",
            "Diciembre",
        ]
        return f"{days[dt.weekday()]}, {dt.day} de {months[dt.month - 1]}"

    @staticmethod
    def get_week_dates(offset: int, tz_name: str = "UTC") -> list[dict[str, str]]:
        tz = zoneinfo.ZoneInfo(tz_name)
        dates: list[dict[str, str]] = []
        today = datetime.now(tz).date() + timedelta(days=offset)
        days_es = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
        months_es = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

        for i in range(7):
            d = today + timedelta(days=i)
            dates.append(
                {"date": d.isoformat(), "label": f"{d.day} {months_es[d.month - 1]}", "dayName": days_es[d.weekday()]}
            )
        return dates

    @staticmethod
    def generate_time_slots(start_h: int, end_h: int, duration_min: int) -> list[str]:
        return [f"{h:02d}:{m:02d}" for h in range(start_h, end_h) for m in range(0, 60, duration_min)]


class WizardUI:
    @staticmethod
    def build_date_selection(state: WizardState, week_offset: int = 0, tz_name: str = "UTC") -> StepView:
        dates = DateUtils.get_week_dates(week_offset, tz_name)
        keyboard: list[list[str]] = []
        for i in range(0, len(dates), 2):
            row = [f"{d['dayName']} {d['label']}" for d in dates[i : i + 2]]
            keyboard.append(row)

        nav = ["Semana siguiente »"]
        if week_offset > 0:
            nav.insert(0, "« Semana anterior")
        keyboard.append(nav)
        keyboard.append(["❌ Cancelar"])

        return {
            "message": "📅 *Elige una fecha*\n\n(Toca el día que prefieras)",
            "reply_keyboard": keyboard,
            "new_state": state.model_copy(update={"step": 1}),
            "force_reply": False,
            "reply_placeholder": "",
        }

    @staticmethod
    def build_time_selection(state: WizardState, slots: list[str]) -> StepView:
        keyboard: list[list[str]] = [slots[i : i + 3] for i in range(0, len(slots), 3)]
        keyboard.append(["« Volver a fechas", "❌ Cancelar"])

        date_label = DateUtils.format_es(state.selected_date) if state.selected_date else "fecha"
        return {
            "message": f"🕐 *Elige un horario*\n\nPara el {date_label}:",
            "reply_keyboard": keyboard,
            "new_state": state.model_copy(update={"step": 2}),
            "force_reply": False,
            "reply_placeholder": "",
        }

    @staticmethod
    def build_confirmation(state: WizardState, provider_name: str, service_name: str) -> StepView:
        date_label = DateUtils.format_es(state.selected_date) if state.selected_date else "?"
        return {
            "message": f"✅ *Confirma tu hora*\n\n📅 Fecha: {date_label}\n🕐 Hora: {state.selected_time}\n👨‍⚕️ Doctor: {provider_name}\n📋 Servicio: {service_name}\n\n¿Confirmas estos detalles?",  # noqa: E501
            "reply_keyboard": [["✅ Confirmar", "🔄 Cambiar hora"], ["« Volver a fechas", "❌ Cancelar"]],
            "new_state": state.model_copy(update={"step": 3}),
            "force_reply": False,
            "reply_placeholder": "",
        }


class WizardRepository:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def get_provider_tz(self, provider_id: str) -> str:
        row = await self.db.fetchrow(
            """
            SELECT t.name as tz_name
            FROM providers p
            LEFT JOIN timezones t ON t.id = p.timezone_id
            WHERE p.provider_id = $1::uuid
            LIMIT 1
            """,
            provider_id,
        )
        if row and row["tz_name"]:
            return str(row["tz_name"])
        return "UTC"

    async def get_service_duration(self, service_id: str) -> int:
        rows = await self.db.fetch(
            "SELECT duration_minutes FROM services WHERE service_id = $1::uuid AND is_active = true LIMIT 1", service_id
        )
        if not rows:
            raise RuntimeError(f"service_not_found: {service_id}")
        return int(cast("Any", rows[0]["duration_minutes"]))

    async def get_available_slots(self, provider_id: str, date_str: str, duration_min: int) -> list[str]:
        # Fallback to first service if wizard state doesn't have it explicitly mapped yet
        service_row = await self.db.fetchrow(
            "SELECT service_id FROM services WHERE provider_id = $1::uuid AND is_active = true LIMIT 1",
            provider_id,
        )
        if not service_row:
            raise RuntimeError("no_active_services_for_provider")

        service_id = str(service_row["service_id"])

        avail_res = await get_availability(
            self.db, {"provider_id": provider_id, "date": date_str, "service_id": service_id}
        )

        if not avail_res:
            raise RuntimeError("availability_check_failed")

        tz_name = str(avail_res.get("timezone", "UTC"))
        tz = zoneinfo.ZoneInfo(tz_name)

        available: list[str] = []
        for s in avail_res.get("slots", []):
            if s.get("available"):
                start_str = str(s["start"])
                dt_utc = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                dt_local = dt_utc.astimezone(tz)
                available.append(dt_local.strftime("%H:%M"))

        return available

    async def get_names(self, provider_id: str, service_id: str) -> dict[str, str]:
        p = await self.db.fetch("SELECT name FROM providers WHERE provider_id = $1::uuid LIMIT 1", provider_id)
        s = await self.db.fetch("SELECT name FROM services WHERE service_id = $1::uuid LIMIT 1", service_id)
        if not p or not s:
            raise RuntimeError("integrity_error")
        return {"provider": str(p[0]["name"]), "service": str(s[0]["name"])}

    async def create_booking(
        self,
        client_id: str,
        provider_id: str,
        service_id: str,
        date_str: str,
        time_str: str,
        tz: str,
        duration_min: int,
    ) -> str:
        local_ts_str = f"{date_str}T{time_str}:00"
        try:
            # We don't attach TZ here because SQL uses AT TIME ZONE $5
            # So we pass a naive timestamp and the TZ name separately
            local_dt = datetime.fromisoformat(local_ts_str)
        except ValueError:
            raise RuntimeError("invalid_timestamp_format") from None

        ik = f"wizard-{client_id}-{provider_id}-{service_id}-{date_str}-{time_str}"
        await self.db.execute("BEGIN")
        try:
            rows = await self.db.fetch(
                """
                INSERT INTO bookings (
                  client_id, provider_id, service_id, start_time, end_time,
                  status, idempotency_key, gcal_sync_status
                ) VALUES (
                  $1::uuid, $2::uuid, $3::uuid,
                  ($4::timestamp AT TIME ZONE $5),
                  ($4::timestamp AT TIME ZONE $5 + ($6 || ' minutes')::interval),
                  'confirmed', $7, 'pending'
                )
                ON CONFLICT (idempotency_key) DO UPDATE SET updated_at = NOW()
                RETURNING booking_id
                """,
                client_id,
                provider_id,
                service_id,
                local_dt,
                tz,
                duration_min,
                ik,
            )
            if not rows:
                await self.db.execute("ROLLBACK")
                raise RuntimeError("insert_failed")
            bid = str(rows[0]["booking_id"])

            await self.db.execute(
                """
                INSERT INTO booking_audit (booking_id, from_status, to_status, changed_by, actor_id, reason, metadata)
                VALUES ($1::uuid, null, 'confirmed', 'client', $2::uuid, 'Booking created via wizard', '{"channel": "telegram"}'::jsonb)  # noqa: E501
                """,  # noqa: E501
                bid,
                client_id,
            )
            await self.db.execute("COMMIT")
            return bid
        except Exception as exc:
            await self.db.execute("ROLLBACK")
            msg = str(exc)
            if "no_overlapping_active_bookings" in msg or "exclusion constraint" in msg:
                raise RuntimeError("time_slot_occupied") from exc
            raise RuntimeError(f"create_failed: {exc}") from exc
