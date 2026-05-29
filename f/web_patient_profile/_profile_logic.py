from ..internal._result import DBClient
from ._profile_models import InputSchema, ProfileResult


def map_to_profile(r: dict[str, object]) -> ProfileResult:
    tz_raw = r.get("timezone_id")
    return {
        "client_id": str(r["client_id"]),
        "name": str(r["name"]),
        "email": str(r["email"]) if r.get("email") else None,
        "phone": str(r["phone"]) if r.get("phone") else None,
        "telegram_chat_id": str(r["telegram_chat_id"]) if r.get("telegram_chat_id") else None,
        "timezone_id": int(str(tz_raw)) if tz_raw is not None else None,
        "gcal_calendar_id": str(r["gcal_calendar_id"]) if r.get("gcal_calendar_id") else None,
    }


async def find_user(db: DBClient, user_id: str) -> dict[str, object]:
    try:
        rows = await db.fetch("SELECT * FROM users WHERE user_id = $1::uuid LIMIT 1", user_id)
        if not rows:
            raise RuntimeError("User not found")
        return dict(rows[0])
    except Exception as e:
        raise RuntimeError(f"DB_FETCH_ERROR (users): {e}") from e


async def find_or_create_client(db: DBClient, user_id: str, user: dict[str, object]) -> dict[str, object]:
    try:
        email = user.get("email")
        rows = await db.fetch("SELECT * FROM clients WHERE client_id = $1::uuid OR email = $2 LIMIT 1", user_id, email)
        if rows:
            return dict(rows[0])

        # Auto-create (no default timezone_id provided since it's an int and we don't know America/Santiago id)
        insert_rows = await db.fetch(
            """
            INSERT INTO clients (name, email, phone, telegram_chat_id)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            user.get("full_name"),
            email,
            user.get("phone"),
            user.get("telegram_chat_id"),
        )
        if not insert_rows:
            raise RuntimeError("Failed to create client record")
        return dict(insert_rows[0])
    except Exception as e:
        raise RuntimeError(f"DB_WRITE_ERROR (clients): {e}") from e


async def update_profile(db: DBClient, client_id: str, data: InputSchema) -> dict[str, object]:
    try:
        _ALLOWED = {"name", "email", "phone", "timezone_id"}
        fields: list[str] = []
        params: list[object] = []
        idx = 1
        for field in ["name", "email", "phone", "timezone_id"]:
            if field not in _ALLOWED:
                continue
            val = getattr(data, field)
            if val is not None:
                fields.append(f"{field} = ${idx}")
                params.append(val)
                idx += 1

        if not fields:
            rows = await db.fetch("SELECT * FROM clients WHERE client_id = $1::uuid LIMIT 1", client_id)
            if not rows:
                raise RuntimeError("Client not found")
            return dict(rows[0])

        params.append(client_id)
        query = f"UPDATE clients SET {', '.join(fields)}, updated_at = NOW() WHERE client_id = ${idx}::uuid RETURNING *"
        rows = await db.fetch(query, *params)
        if not rows:
            raise RuntimeError("Update failed: client record missing after write")
        return dict(rows[0])
    except Exception as e:
        raise RuntimeError(f"DB_UPDATE_ERROR (clients): {e}") from e
