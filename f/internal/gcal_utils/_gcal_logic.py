from typing import Literal

from f.internal._config import DEFAULT_TIMEZONE

from ._gcal_models import BookingEventData, GoogleCalendarEvent


def build_gcal_event(
    booking: BookingEventData, calendar_type: Literal["provider", "client"] = "provider"
) -> GoogleCalendarEvent:
    # calendar_type reserved for future per-audience event customization

    title = (
        f"[CANCELLED] Hora Médica - {booking['provider_name']}"
        if booking["status"] == "cancelled"
        else f"Hora Médica - {booking['provider_name']}"
    )

    description_parts = [
        f"Servicio: {booking['service_name']}",
        f"ID de reserva: {booking['booking_id']}",
        f"Estado: {booking['status']}",
        "",
        "Esta hora ha sido cancelada."
        if booking["status"] == "cancelled"
        else "Para cancelar o reagendar, contacta a través de Telegram.",
    ]
    description = "\n".join(description_parts)

    return {
        "summary": title,
        "description": description,
        "start": {"dateTime": booking["start_time"], "timeZone": DEFAULT_TIMEZONE},
        "end": {"dateTime": booking["end_time"], "timeZone": DEFAULT_TIMEZONE},
        "status": "cancelled" if booking["status"] == "cancelled" else "confirmed",
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 1440},  # 24h
                {"method": "popup", "minutes": 120},  # 2h
                {"method": "popup", "minutes": 30},  # 30min
            ],
        },
    }
