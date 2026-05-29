from typing import TypedDict

import jwt

from ._wmill_adapter import get_variable_strict


class TokenPayload(TypedDict):
    sub: str
    role: str


def verify_access_token(token: str) -> TokenPayload:
    secret = get_variable_strict("u/admin/ENCRYPTION_KEY")
    if not secret:
        raise RuntimeError("ENCRYPTION_KEY not configured")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return {"sub": str(payload.get("sub")), "role": str(payload.get("role"))}
    except Exception as e:
        raise RuntimeError(f"Invalid or expired token: {e}") from e
