from datetime import datetime

from ..internal._result import DBClient
from ._user_models import InputSchema, UserInfo, UsersListResult


def map_row(r: dict[str, object]) -> UserInfo:
    last_login_raw = r.get("last_login")
    created_at_raw = r.get("created_at")
    return {
        "full_name": str(r["full_name"]),
        "email": str(r["email"]) if r.get("email") else None,
        "rut": str(r["rut"]) if r.get("rut") else None,
        "phone": str(r["phone"]) if r.get("phone") else None,
        "role": str(r["role"]),
        "is_active": bool(r["is_active"]),
        "telegram_chat_id": str(r["telegram_chat_id"]) if r.get("telegram_chat_id") else None,
        "last_login": last_login_raw.isoformat()
        if isinstance(last_login_raw, datetime)
        else str(last_login_raw)
        if last_login_raw
        else None,
        "created_at": created_at_raw.isoformat() if isinstance(created_at_raw, datetime) else str(created_at_raw),
    }


async def handle_user_actions(db: DBClient, input_data: InputSchema) -> UserInfo | UsersListResult:
    action = input_data.action

    if action == "list":
        rows = await db.fetch(
            """
            SELECT user_id, full_name, email, rut, phone, role, is_active,
                   telegram_chat_id, last_login, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT 200
            """
        )
        users = [map_row(r) for r in rows]
        count_rows = await db.fetch("SELECT COUNT(*) AS total FROM users")
        total = int(count_rows[0]["total"]) if count_rows else 0  # type: ignore[call-overload]
        return {"users": users, "total": total}

    if not input_data.target_user_id:
        raise RuntimeError(f"{action}_failed: target_user_id is required")

    if action == "get":
        rows = await db.fetch("SELECT * FROM users WHERE user_id = $1::uuid LIMIT 1", input_data.target_user_id)
        if not rows:
            raise RuntimeError("User not found")
        return map_row(rows[0])

    elif action == "update":
        _ALLOWED = {"full_name", "email", "phone", "role"}
        fields: list[str] = []
        params: list[object] = []
        idx = 1
        for field in ["full_name", "email", "phone", "role"]:
            if field not in _ALLOWED:
                continue
            val = getattr(input_data, field)
            if val is not None:
                fields.append(f"{field} = ${idx}")
                params.append(val)
                idx += 1

        if not fields:
            raise RuntimeError("update_failed: no fields provided")

        params.append(input_data.target_user_id)
        query = f"UPDATE users SET {', '.join(fields)}, updated_at = NOW() WHERE user_id = ${idx}::uuid RETURNING *"
        rows = await db.fetch(query, *params)
        if not rows:
            raise RuntimeError("User not found")
        return map_row(rows[0])

    elif action == "activate" or action == "deactivate":
        active = action == "activate"
        rows = await db.fetch(
            "UPDATE users SET is_active = $1, updated_at = NOW() WHERE user_id = $2::uuid RETURNING *",
            active,
            input_data.target_user_id,
        )
        if not rows:
            raise RuntimeError("User not found")
        return map_row(rows[0])

    raise RuntimeError(f"Unsupported action: {action}")
