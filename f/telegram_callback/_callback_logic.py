from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx

from ..internal._wmill_adapter import log

if TYPE_CHECKING:
    from ..internal._result import DBClient

ACTION_MAP: dict[str, str] = {
    "cnf": "confirm",
    "cxl": "cancel",
    "cxr": "cancel_reason",
    "res": "reagendar_cita",
    "ars": "auto_reschedule",
    "act": "activate_reminders",
    "dea": "deactivate_reminders",
    "ack": "acknowledge",
}


def _safe_uuid(val: str) -> str | None:
    try:
        return str(uuid.UUID(val))
    except ValueError:
        return None


def parse_callback_data(data: str) -> dict[str, str] | None:
    # 0. Strip session suffix if present (format: prefix:id:extra|session_id)
    raw_payload = data
    session_id = ""
    if "|" in data:
        parts_session = data.split("|")
        raw_payload = parts_session[0]
        session_id = parts_session[1]

    parts = raw_payload.split(":")
    if len(parts) < 2:
        return None
    action_code = parts[0]
    booking_id_raw = parts[1]

    action = ACTION_MAP.get(action_code)
    if not action:
        return None

    booking_id = _safe_uuid(booking_id_raw)
    if not booking_id:
        return None

    res = {"action": action, "booking_id": booking_id, "session_id": session_id}

    if action == "auto_reschedule" and len(parts) == 4:
        res["date"] = parts[2]
        res["time"] = parts[3]

    if action == "cancel_reason" and len(parts) == 3:
        res["reason_code"] = parts[2]

    return res


async def confirm_booking(db: DBClient, booking_id: str, client_id: str | None) -> bool:
    """Atomic confirm using UPDATE ... RETURNING (eliminates SELECT→UPDATE race)."""
    row = await db.fetchrow(
        """
        UPDATE bookings
        SET status = 'confirmed', updated_at = NOW()
        WHERE booking_id = $1::uuid
          AND status = 'pending'
        RETURNING booking_id, status, client_id
        """,
        booking_id,
    )
    if not row:
        raise RuntimeError("Booking not found or not in pending status")

    if client_id and str(row["client_id"]) != client_id:
        # Rollback would be handled by the caller's transaction wrapper
        raise RuntimeError("Unauthorized: client mismatch")

    await db.execute(
        """
        INSERT INTO booking_audit (booking_id, from_status, to_status, changed_by, actor_id, reason)
        VALUES ($1::uuid, $2, 'confirmed', 'client', $3::uuid, 'Confirmed via Telegram inline button')
        """,
        booking_id,
        "pending",
        client_id,
    )
    return True


async def update_booking_status(
    db: DBClient, booking_id: str, new_status: str, client_id: str | None, actor: str
) -> bool:
    """Atomic status update using UPDATE ... RETURNING (eliminates SELECT→UPDATE race)."""
    row = await db.fetchrow(
        """
        UPDATE bookings
        SET status = $1,
            cancelled_by = $2,
            updated_at = NOW()
        WHERE booking_id = $3::uuid
          AND status NOT IN ('cancelled', 'completed', 'no_show', 'rescheduled')
        RETURNING booking_id, status, client_id, start_time, end_time
        """,
        new_status,
        actor if new_status == "cancelled" else None,
        booking_id,
    )
    if not row:
        raise RuntimeError("Booking not found or already terminal")

    if client_id and str(row["client_id"]) != client_id:
        raise RuntimeError("Unauthorized: client mismatch")

    reason = "Cancelled via Telegram inline button" if new_status == "cancelled" else "Status updated via Telegram"
    await db.execute(
        """
        INSERT INTO booking_audit (booking_id, from_status, to_status, changed_by, actor_id, reason)
        VALUES ($1::uuid, $2, $3, $4, $5::uuid, $6)
        """,
        booking_id,
        row["status"],
        new_status,
        actor,
        client_id,
        reason,
    )
    return True


async def answer_callback_query(bot_token: str, callback_query_id: str, text: str, show_alert: bool = False) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            payload: dict[str, object] = {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            }
            res = await client.post(url, json=payload)
            return res.status_code == 200
    except Exception as e:
        log("answer_callback_query failed", error=str(e), module="telegram_callback")
        return False


async def send_followup_message(
    bot_token: str,
    chat_id: str,
    text: str,
    reply_markup: dict[str, object] | None = None,
) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload: dict[str, object] = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            res = await client.post(url, json=payload)
            return res.status_code == 200
    except Exception as e:
        log("send_followup_message failed", error=str(e), module="telegram_callback")
        return False


async def clean_message_reply_markup(
    bot_token: str,
    chat_id: str,
    message_id: str,
) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            payload: dict[str, object] = {
                "chat_id": chat_id,
                "message_id": int(message_id),
                "reply_markup": {"inline_keyboard": []},
            }
            res = await client.post(url, json=payload)
            return res.status_code == 200
    except Exception as e:
        log("clean_message_reply_markup failed", error=str(e), module="telegram_callback")
        return False
