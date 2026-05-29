from datetime import datetime

from ..internal._result import DBClient
from ._me_models import UserProfileResult


async def get_user_profile(db: DBClient, user_id: str) -> UserProfileResult:
    rows = await db.fetch(
        """
        SELECT user_id, email, full_name, role, rut, phone, address,
               telegram_chat_id, timezone, is_active, last_login,
               CASE WHEN rut IS NOT NULL AND email IS NOT NULL AND password_hash IS NOT NULL
                    THEN true ELSE false END AS profile_complete
        FROM users
        WHERE user_id = $1::uuid
        LIMIT 1
        """,
        user_id,
    )

    if not rows:
        raise RuntimeError("User not found")

    r = rows[0]
    if not r["is_active"]:
        raise RuntimeError("Account is disabled. Contact support.")

    result: UserProfileResult = {
        "user_id": str(r["user_id"]),
        "email": str(r["email"]) if r.get("email") else None,
        "full_name": str(r["full_name"]),
        "role": str(r["role"]),
        "rut": str(r["rut"]) if r.get("rut") else None,
        "phone": str(r["phone"]) if r.get("phone") else None,
        "address": str(r["address"]) if r.get("address") else None,
        "telegram_chat_id": str(r["telegram_chat_id"]) if r.get("telegram_chat_id") else None,
        "timezone": str(r["timezone"]),
        "is_active": bool(r["is_active"]),
        "profile_complete": bool(r["profile_complete"]),
        "last_login": r["last_login"].isoformat()
        if r.get("last_login") and isinstance(r["last_login"], datetime)
        else None,
    }

    return result
