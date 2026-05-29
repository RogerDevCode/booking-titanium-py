# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "email-validator>=2.2.0",
#   "asyncpg>=0.30.0",
#   "cryptography>=48.0.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "redis>=7.4.0",
#   "typing-extensions>=4.12.0",
#   "pyjwt>=2.12.1"
# ]
# ///
import asyncio
from datetime import UTC, datetime, timedelta

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Authenticate email+password, return session + role
# DB Tables Used  : users
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_admin_context bypasses RLS for user discovery
# Pydantic Schemas: YES — InputSchema validates email and password
# ============================================================================
from typing import Any, cast

import jwt

from ..internal._db_client import create_db_client
from ..internal._result import with_admin_context
from ..internal._wmill_adapter import get_variable_strict, log
from ._login_logic import verify_password_sync
from ._login_models import InputSchema, LoginResult, UserRow

MODULE = "web_auth_login"


async def _main_async(args: dict[str, Any]) -> LoginResult:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute Auth Transaction with Admin Context (bypass RLS)
        async def operation() -> LoginResult:
            # Lookup user by email
            rows = await conn.fetch(
                """
                SELECT user_id, email, full_name, role, password_hash, is_active,
                       CASE WHEN rut IS NOT NULL AND email IS NOT NULL AND password_hash IS NOT NULL
                            THEN true ELSE false END AS profile_complete
                FROM users
                WHERE email = $1
                LIMIT 1
                """,
                input_data.email,
            )

            if not rows:
                raise RuntimeError("Invalid email or password")

            r = rows[0]
            user: UserRow = {
                "user_id": str(r["user_id"]),
                "email": str(r["email"]),
                "full_name": str(r["full_name"]),
                "role": str(r["role"]),
                "password_hash": str(r["password_hash"]),
                "is_active": bool(r["is_active"]),
                "profile_complete": bool(r["profile_complete"]),
            }

            # Check account status
            if not user["is_active"]:
                raise RuntimeError("Account is disabled. Contact support.")

            # Verify password
            if not user["password_hash"] or user["password_hash"] == "null":
                raise RuntimeError("Invalid email or password")

            if not verify_password_sync(input_data.password, user["password_hash"]):
                raise RuntimeError("Invalid email or password")

            # Success: Update last login
            await conn.execute("UPDATE users SET last_login = NOW() WHERE user_id = $1::uuid", user["user_id"])

            # Generate JWT
            secret = get_variable_strict("u/admin/ENCRYPTION_KEY")
            payload = {
                "sub": user["user_id"],
                "role": user["role"],
                "exp": datetime.now(UTC) + timedelta(days=7),
                "iat": datetime.now(UTC),
            }
            token = jwt.encode(payload, secret, algorithm="HS256")

            result: LoginResult = {
                "email": user["email"],
                "full_name": user["full_name"],
                "role": user["role"],
                "profile_complete": user["profile_complete"],
                "access_token": token,
            }
            return result

        result = await with_admin_context(conn, operation)
        return result

    except Exception as e:
        log("Internal error in login", error=str(e), module=MODULE)
        raise RuntimeError(f"Internal error: {e}") from e
    finally:
        await conn.close()  # pyright: ignore[reportUnknownMemberType]


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    import traceback

    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result = asyncio.run(_main_async(validated.model_dump()))
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
