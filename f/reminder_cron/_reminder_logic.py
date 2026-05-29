from __future__ import annotations

from typing import TYPE_CHECKING

from ..reminder_config._config_models import InlineButton
from ._reminder_models import BookingDetails, ReminderMessage

if TYPE_CHECKING:
    from datetime import datetime

    from ..reminder_config._config_models import ReminderChannel, ReminderPreferences, ReminderWindow
    from ._reminder_models import BookingRecord


def format_date_es(dt: datetime) -> str:
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
    day_name = days[dt.weekday()]
    month_name = months[dt.month - 1]
    return f"{day_name}, {dt.day} de {month_name} de {dt.year}"


def format_time_es(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def get_client_preference(prefs: ReminderPreferences | None, channel: ReminderChannel, window: ReminderWindow) -> bool:
    if not prefs:
        return True

    if channel == "telegram" and not prefs.channels.telegram:
        return False
    if channel == "email" and not prefs.channels.email:
        return False

    attr = f"w_{window}"
    return bool(getattr(prefs.windows, attr, True))


def build_booking_details(booking: BookingRecord) -> BookingDetails:
    st = booking.start_time

    return BookingDetails(
        date=format_date_es(st),
        time=format_time_es(st),
        provider_name=booking.provider_name or "Tu doctor",
        service=booking.service_name or "Consulta",
        booking_id=f"{booking.booking_id[:2].upper()}-{booking.booking_id[2:5].upper()}-{booking.booking_id[5:8].upper()}",
        client_name=booking.client_name or "Paciente",
    )


def build_inline_buttons(booking_id: str, window: ReminderWindow) -> list[list[InlineButton]]:
    if window == "24h":
        return [
            [
                InlineButton(text="✅ Confirmar", callback_data=f"cnf:{booking_id}"),
                InlineButton(text="❌ Cancelar", callback_data=f"cxl:{booking_id}"),
            ],
            [InlineButton(text="🔄 Reprogramar", callback_data=f"res:{booking_id}")],
        ]

    if window == "2h":
        return [
            [
                InlineButton(text="✅ Voy a asistir", callback_data=f"ack:{booking_id}"),
                InlineButton(text="❌ Cancelar", callback_data=f"cxl:{booking_id}"),
            ]
        ]

    return [[InlineButton(text="👍 En camino", callback_data=f"ack:{booking_id}")]]


def build_reminder_message(booking: BookingRecord, window: ReminderWindow) -> ReminderMessage:
    details = build_booking_details(booking)
    return ReminderMessage(
        text=(
            "🔔 Recordatorio de tu hora:\n\n"
            f"Doctor: {details.provider_name}\n"
            f"Fecha: {details.date}\n"
            f"Hora: {details.time}"
        ),
        inline_buttons=build_inline_buttons(booking.booking_id, window),
        booking_details=details,
    )
