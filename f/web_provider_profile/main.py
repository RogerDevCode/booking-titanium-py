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
import traceback

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Provider self-service profile management (get/update/change password)
# DB Tables Used  : providers, honorifics, specialties, timezones, regions, communes
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates action and provider fields
# ============================================================================
from typing import Any, cast

from pydantic import BaseModel

from ..internal._crypto import hash_password, validate_password_policy, verify_password
from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._profile_logic import ProfileRepository
from ._profile_models import InputSchema

MODULE = "web_provider_profile"


async def _main_async(args: dict[str, Any]) -> object:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute within Tenant Context (provider_id)
        async def operation() -> object:
            repo = ProfileRepository(conn)
            action = input_data.action

            if action == "get_profile":
                return await repo.find_by_id(input_data.provider_id)

            elif action == "update_profile":
                await repo.update(input_data.provider_id, input_data)
                return await repo.find_by_id(input_data.provider_id)

            elif action == "change_password":
                if not input_data.current_password or not input_data.new_password:
                    raise RuntimeError("missing_password_fields")

                # 1. Validate Policy
                policy = validate_password_policy(input_data.new_password)
                if not policy["valid"]:
                    raise RuntimeError(f"policy_violation: {', '.join(policy['errors'])}")

                # 2. Verify Current
                cur_hash = await repo.get_password_hash(input_data.provider_id)
                if not cur_hash:
                    raise RuntimeError("password_hash_not_found")

                if not verify_password(input_data.current_password, cur_hash):
                    raise RuntimeError("invalid_current_password")

                # 3. Update
                new_h = hash_password(input_data.new_password)
                await repo.update_password(input_data.provider_id, new_h)

                return {"success": True, "message": "password_changed"}

            raise RuntimeError(f"Unsupported action: {action}")

        return await with_tenant_context(conn, input_data.provider_id, operation)

    except Exception as e:
        log("Provider Profile Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()  # pyright: ignore[reportUnknownMemberType]


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result: Any = asyncio.run(_main_async(validated.model_dump()))

        if isinstance(result, BaseModel):
            return cast("dict[str, object]", result.model_dump())
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
