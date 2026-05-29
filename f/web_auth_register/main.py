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
# Mission         : Register new user via web (hash password, validate RUT)
# DB Tables Used  : users
# Concurrency Risk: YES — handled by unique constraints
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_admin_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates all fields
# ============================================================================
from typing import Any, cast

from ..internal._db_client import create_db_client
from ..internal._result import with_admin_context
from ..internal._wmill_adapter import log
from ._register_logic import hash_password_sync, validate_password_strength, validate_rut
from ._register_models import InputSchema, RegisterResult

MODULE = "web_auth_register"


async def _main_async(args: dict[str, Any]) -> RegisterResult:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    if input_data.password != input_data.password_confirm:
        raise RuntimeError("Passwords do not match")

    pwd_err = validate_password_strength(input_data.password)
    if pwd_err:
        raise RuntimeError(pwd_err)

    if not validate_rut(input_data.rut):
        raise RuntimeError("Invalid Chilean RUT format or verification digit")

    conn = await create_db_client()
    try:

        async def operation() -> RegisterResult:
            # Check for existing user
            rows = await conn.fetch(
                "SELECT user_id FROM users WHERE email = $1 OR rut = $2 LIMIT 1", input_data.email, input_data.rut
            )
            if rows:
                raise RuntimeError("A user with this email or RUT already exists")

            # Hash and Insert
            pwd_hash = hash_password_sync(input_data.password)

            insert_rows = await conn.fetch(
                """
                INSERT INTO users (
                  full_name, rut, email, address, phone, password_hash,
                  role, is_active, timezone
                ) VALUES (
                  $1, $2, $3, $4, $5, $6, 'client', true, $7
                )
                RETURNING user_id, email, full_name, role
                """,
                input_data.full_name,
                input_data.rut,
                input_data.email,
                input_data.address,
                input_data.phone,
                pwd_hash,
                input_data.timezone,
            )

            if not insert_rows:
                raise RuntimeError("Failed to create user record")

            r = insert_rows[0]
            result: RegisterResult = {
                "user_id": str(r["user_id"]),
                "email": str(r["email"]),
                "full_name": str(r["full_name"]),
                "role": str(r["role"]),
            }
            return result

        result = await with_admin_context(conn, operation)
        return result

    except Exception as e:
        msg = str(e)
        if "duplicate key" in msg or "unique constraint" in msg:
            raise RuntimeError("A user with this email or RUT already exists") from e
        log("Internal error in register", error=msg, module=MODULE)
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
