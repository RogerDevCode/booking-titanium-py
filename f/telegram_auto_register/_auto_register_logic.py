from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._auto_register_models import InputSchema, RegisterResult


async def register_telegram_user(db: DBClient, input_data: InputSchema) -> RegisterResult:
    """UPSERT Telegram user into clients table. users table belongs to Windmill internals."""
    full_name = f"{input_data.first_name} {input_data.last_name or ''}".strip()

    rows = await db.fetch(
        "SELECT client_id, name, phone FROM clients WHERE telegram_chat_id = $1 LIMIT 1",
        input_data.chat_id,
    )
    is_new = not rows

    if rows:
        client_id = str(rows[0]["client_id"])
        name = str(rows[0]["name"] or "")
        phone: str | None = str(rows[0]["phone"]) if rows[0]["phone"] else None
    else:
        new_rows = await db.fetch(
            "INSERT INTO clients (name, telegram_chat_id) VALUES ($1, $2) RETURNING client_id, name",
            full_name,
            input_data.chat_id,
        )
        if not new_rows:
            raise RuntimeError("Failed to create client record")
        client_id = str(new_rows[0]["client_id"])
        name = str(new_rows[0]["name"] or full_name)
        phone = None

    return {"user_id": client_id, "client_id": client_id, "is_new": is_new, "name": name, "phone": phone}
