from __future__ import annotations

from typing import TYPE_CHECKING

from f.internal._config import DEFAULT_TIMEZONE

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._patient_models import ClientResult, InputSchema


async def upsert_client(db: DBClient, input_data: InputSchema) -> ClientResult:
    """
    Business logic to create or update a patient record.
    Priority identification: Telegram > Email > Phone.
    """
    try:
        # 1. Search for existing client
        existing_id: str | None = None

        # Identification by Telegram
        if input_data.telegram_chat_id:
            try:
                rows = await db.fetch(
                    "SELECT client_id FROM clients WHERE telegram_chat_id = $1 LIMIT 1", input_data.telegram_chat_id
                )
                if rows:
                    existing_id = str(rows[0]["client_id"])
            except Exception as e:
                raise RuntimeError(f"db_search_telegram_failed: {e}") from e

        # Identification by Email (if telegram didn't match)
        if not existing_id and input_data.email:
            try:
                rows = await db.fetch("SELECT client_id FROM clients WHERE email = $1 LIMIT 1", input_data.email)
                if rows:
                    existing_id = str(rows[0]["client_id"])
            except Exception as e:
                raise RuntimeError(f"db_search_email_failed: {e}") from e

        # Identification by Phone (if still not found)
        if not existing_id and input_data.phone:
            try:
                rows = await db.fetch("SELECT client_id FROM clients WHERE phone = $1 LIMIT 1", input_data.phone)
                if rows:
                    existing_id = str(rows[0]["client_id"])
            except Exception as e:
                raise RuntimeError(f"db_search_phone_failed: {e}") from e

        # 2. Update or Insert
        if existing_id:
            try:
                update_rows = await db.fetch(
                    """
                    UPDATE clients SET
                      name = $1,
                      email = COALESCE($2, email),
                      phone = COALESCE($3, phone),
                      telegram_chat_id = COALESCE($4, telegram_chat_id),
                      timezone = COALESCE($5, timezone),
                      updated_at = NOW()
                    WHERE client_id = $6::uuid
                    RETURNING client_id, name, email, phone, telegram_chat_id, timezone
                    """,
                    input_data.name,
                    input_data.email,
                    input_data.phone,
                    input_data.telegram_chat_id,
                    input_data.timezone,
                    existing_id,
                )
                if not update_rows:
                    raise RuntimeError("db_update_returned_empty")
                created = False
                r = update_rows[0]
            except Exception as e:
                raise RuntimeError(f"db_update_failed: {e}") from e
        else:
            try:
                insert_rows = await db.fetch(
                    """
                    INSERT INTO clients (name, email, phone, telegram_chat_id, timezone)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING client_id, name, email, phone, telegram_chat_id, timezone
                    """,
                    input_data.name,
                    input_data.email,
                    input_data.phone,
                    input_data.telegram_chat_id,
                    input_data.timezone,
                )
                if not insert_rows:
                    raise RuntimeError("db_insert_returned_empty")
                created = True
                r = insert_rows[0]
            except Exception as e:
                raise RuntimeError(f"db_insert_failed: {e}") from e

        return {
            "client_id": str(r["client_id"]),
            "name": str(r["name"]),
            "email": str(r["email"]) if r.get("email") else None,
            "phone": str(r["phone"]) if r.get("phone") else None,
            "telegram_chat_id": str(r["telegram_chat_id"]) if r.get("telegram_chat_id") else None,
            "timezone": str(r["timezone"]) if r.get("timezone") else DEFAULT_TIMEZONE,
            "created": created,
        }

    except Exception as e:
        raise RuntimeError(f"unexpected_logic_error: {e}") from e
