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
#   "typing-extensions>=4.12.0"
# ]
# ///
import asyncio

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Complete profile for Telegram-registered user via web
# DB Tables Used  : users
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_admin_context used for initial discovery
# Pydantic Schemas: YES — InputSchema validates all fields
# ============================================================================
from typing import Any, cast

from ..internal._crypto import hash_password, validate_password_policy
from ..internal._db_client import create_db_client
from ..internal._result import with_admin_context
from ..internal._wmill_adapter import log
from ..web_auth_register._register_logic import validate_rut
from ._complete_profile_models import CompleteProfileResult, InputSchema

MODULE = "web_auth_complete_profile"


async def _main_async(args: dict[str, Any]) -> CompleteProfileResult:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    if input_data.password != input_data.password_confirm:
        raise RuntimeError("Passwords do not match")

    policy = validate_password_policy(input_data.password)
    if not policy["valid"]:
        raise RuntimeError(f"Password policy violation: {', '.join(policy['errors'])}")

    if not validate_rut(input_data.rut):
        raise RuntimeError("Invalid Chilean RUT format or verification digit")

    conn = await create_db_client()
    try:

        async def operation() -> CompleteProfileResult:
            # Find the user by Telegram Chat ID
            user_rows = await conn.fetch(
                "SELECT user_id, full_name, email, rut, role FROM users WHERE telegram_chat_id = $1 LIMIT 1",
                input_data.chat_id,
            )
            if not user_rows:
                raise RuntimeError("No Telegram user found. Please interact with the bot first.")

            user = user_rows[0]
            user_id = str(user["user_id"])

            # Check global uniqueness for email/RUT (bypass RLS via admin context)
            existing_rows = await conn.fetch(
                """
                SELECT user_id FROM users
                WHERE (email = $1 OR rut = $2)
                  AND user_id != $3::uuid
                LIMIT 1
                """,
                input_data.email,
                input_data.rut,
                user_id,
            )
            if existing_rows:
                raise RuntimeError("This email or RUT is already in use by another account")

            # Hash and Update
            pwd_hash = hash_password(input_data.password)

            update_rows = await conn.fetch(
                """
                UPDATE users SET
                  rut = $1,
                  email = $2,
                  address = $3,
                  phone = $4,
                  password_hash = $5,
                  timezone = $6,
                  updated_at = NOW()
                WHERE user_id = $7::uuid
                RETURNING user_id, full_name, email, rut, role
                """,
                input_data.rut,
                input_data.email,
                input_data.address,
                input_data.phone,
                pwd_hash,
                input_data.timezone,
                user_id,
            )

            if not update_rows:
                raise RuntimeError("Failed to update profile")

            r = update_rows[0]
            result: CompleteProfileResult = {
                "user_id": str(r["user_id"]),
                "full_name": str(r["full_name"]),
                "email": str(r["email"]),
                "rut": str(r["rut"]),
                "role": str(r["role"]),
            }
            return result

        result = await with_admin_context(conn, operation)
        return result

    except Exception as e:
        msg = str(e)
        if "duplicate key" in msg or "unique constraint" in msg:
            raise RuntimeError("This email or RUT is already in use by another account") from e
        log("Internal error in profile completion", error=msg, module=MODULE)
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
