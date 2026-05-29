from __future__ import annotations

import asyncio
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ._gmail_models import ActionLink


def safe_string(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str | int | float | bool):
        return str(value)
    return fallback


def build_email_content(
    message_type: str, details: dict[str, object], action_links: list[ActionLink]
) -> tuple[str, str]:
    date = safe_string(details.get("date"), "Por confirmar")
    time_val = safe_string(details.get("time"), "Por confirmar")
    provider_name = safe_string(details.get("provider_name"), "Tu doctor")
    service = safe_string(details.get("service"), "Consulta")
    booking_id = safe_string(details.get("booking_id"), "")
    reason = safe_string(details.get("cancellation_reason"), "")
    custom_subject = safe_string(details.get("subject"), "")
    custom_body = safe_string(details.get("html_body"), "")

    subject = ""
    body = ""
    icon = ""
    color = "#4CAF50"

    if message_type == "booking_created":
        subject = "✅ Hora Médica Agendada"
        icon = "✅"
        color = "#4CAF50"
        body = f"""<h2 style="color: {color};">Hora Agendada Exitosamente</h2>
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
              <tr><td style="padding: 8px 0; font-weight: bold;">📅 Fecha:</td><td>{date}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">🕐 Hora:</td><td>{time_val}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">👨‍⚕️ Doctor:</td><td>{provider_name}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">📋 Servicio:</td><td>{service}</td></tr>
              {"<tr><td style='padding: 8px 0; font-weight: bold;'>🆔 ID:</td><td><code>" + booking_id + "</code></td></tr>" if booking_id else ""}  # noqa: E501
            </table>
            <p style="color: #666;">Para cancelar o reagendar, usa los botones de abajo o responde a este correo.</p>"""  # noqa: E501

    elif message_type == "booking_confirmed":
        subject = "✅ Hora Confirmada"
        icon = "✅"
        body = f"""<h2 style="color: {color};">Tu Hora Ha Sido Confirmada</h2>
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
              <tr><td style="padding: 8px 0; font-weight: bold;">📅 Fecha:</td><td>{date}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">🕐 Hora:</td><td>{time_val}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">👨‍⚕️ Doctor:</td><td>{provider_name}</td></tr>
            </table>
            <p style="color: #666;">Te esperamos. Recuerda llegar 10 minutos antes.</p>"""

    elif message_type == "booking_cancelled":
        subject = "❌ Hora Cancelada"
        icon = "❌"
        color = "#F44336"
        body = f"""<h2 style="color: {color};">Hora Cancelada</h2>
            <p>Tu hora ha sido cancelada:</p>
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
              <tr><td style="padding: 8px 0; font-weight: bold;">📅 Fecha:</td><td>{date}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">🕐 Hora:</td><td>{time_val}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">👨‍⚕️ Doctor:</td><td>{provider_name}</td></tr>
            </table>
            {"<p><strong>Motivo:</strong> " + reason + "</p>" if reason else ""}
            <p style="color: #666;">Si deseas agendar una nueva hora, contáctanos por Telegram o responde a este correo.</p>"""  # noqa: E501

    elif message_type in {
        "reminder_1day",
        "reminder_24h",
        "reminder_12h",
        "reminder_6h",
        "reminder_2h",
        "reminder_1h",
        "reminder_30min",
    }:
        subject_map = {
            "reminder_1day": "⏰ Recordatorio: Tu hora es mañana",
            "reminder_24h": "⏰ Recordatorio: Tu hora es en 24 horas",
            "reminder_12h": "⏰ Recordatorio: Tu hora es en 12 horas",
            "reminder_6h": "⏰ Recordatorio: Tu hora es en 6 horas",
            "reminder_2h": "⏰ Recordatorio: Tu hora es en 2 horas",
            "reminder_1h": "⏰ Recordatorio: Tu hora es en 1 hora",
            "reminder_30min": "⏰ Recordatorio: Tu hora es en 30 minutos",
        }
        subject = subject_map[message_type]
        icon = "⏰"
        color = "#2196F3"
        body = f"""<h2 style="color: {color};">Recordatorio de Hora</h2>
            <p style="font-size: 18px;">No olvides tu próxima hora:</p>
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
              <tr><td style="padding: 8px 0; font-weight: bold;">📅 Fecha:</td><td>{date}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">🕐 Hora:</td><td>{time_val}</td></tr>
              <tr><td style="padding: 8px 0; font-weight: bold;">👨‍⚕️ Doctor:</td><td>{provider_name}</td></tr>
            </table>"""

    elif message_type == "custom":
        subject = custom_subject or "Notificación del Sistema"
        body = custom_body or "<p>Tienes una notificación.</p>"

    else:
        subject = "Notificación del Sistema"
        body = f"<p>Tienes una notificación: {message_type}</p>"

    buttons_html = ""
    if action_links:
        links_html: list[str] = []
        for link in action_links:
            bg = "#F44336" if link.style == "danger" else "#757575" if link.style == "secondary" else "#4CAF50"
            links_html.append(
                f'<a href="{link.url}" style="display: inline-block; padding: 12px 24px; margin: 0 8px 8px 0; background-color: {bg}; color: white; text-decoration: none; border-radius: 4px; font-weight: bold;">{link.text}</a>'  # noqa: E501
            )
        buttons_html = f'<div style="margin: 30px 0;">{"".join(links_html)}</div>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
  <div style="text-align: center; font-size: 48px; margin-bottom: 20px;">{icon}</div>
  {body}
  {buttons_html}
  <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
  <p style="color: #999; font-size: 12px;">Este es un mensaje automático del sistema de citas médicas. No respondas directamente a este correo.</p>  # noqa: E501
</body></html>"""  # noqa: E501

    return subject, html


async def send_with_retry(
    smtp_config: dict[str, object], from_addr: str, to_addr: str, subject: str, html: str, max_retries: int = 3
) -> tuple[Exception | None, str | None]:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            # Sync wrapper for SMTP
            def do_send() -> None:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = from_addr
                msg["To"] = to_addr
                msg.attach(MIMEText(html, "html"))

                with smtplib.SMTP(str(smtp_config["host"]), int(cast("Any", smtp_config["port"]))) as server:
                    if int(cast("Any", smtp_config["port"])) == 587:
                        server.starttls()
                    server.login(str(smtp_config["user"]), str(smtp_config["password"]))
                    server.send_message(msg)

            # Execute in thread pool to not block event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, do_send)
            return None, f"msg-{int(time.time())}"

        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                await asyncio.sleep(2.0**attempt)

    return last_err, None
