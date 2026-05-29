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
# Mission         : Admin CRUD for tag categories and tags
# DB Tables Used  : tag_categories, tags, users
# Concurrency Risk: NO
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : YES — with_tenant_context enforces isolation
# Pydantic Schemas: YES — InputSchema validates all parameters
# ============================================================================
from typing import Any, cast

from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._tags_logic import TagRepository, verify_admin_access
from ._tags_models import InputSchema

MODULE = "web_admin_tags"


async def _main_async(args: dict[str, Any]) -> object:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"VALIDATION_ERROR: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Execute with Multi-Tenant Context
        async def operation() -> object:
            # Verify Admin Access
            await verify_admin_access(conn, input_data.admin_user_id)

            repo = TagRepository(conn)
            action = input_data.action

            if action == "list_categories":
                return await repo.list_categories()
            elif action == "create_category":
                if not input_data.name:
                    raise RuntimeError("REQUIRED: name")
                return await repo.create_category(input_data.name, input_data.description, input_data.sort_order or 0)
            elif action == "update_category":
                if not input_data.category_id:
                    raise RuntimeError("REQUIRED: category_id")
                return await repo.update_category(input_data.category_id, input_data)
            elif action == "delete_category":
                if not input_data.category_id:
                    raise RuntimeError("REQUIRED: category_id")
                return await repo.delete_category(input_data.category_id)
            elif action == "activate_category" or action == "deactivate_category":
                if not input_data.category_id:
                    raise RuntimeError("REQUIRED: category_id")
                return await repo.set_category_status(input_data.category_id, action == "activate_category")

            elif action == "list_tags":
                return await repo.list_tags(input_data.category_id)
            elif action == "create_tag":
                if not input_data.category_id or not input_data.name:
                    raise RuntimeError("REQUIRED: category_id, name")
                return await repo.create_tag(
                    input_data.category_id,
                    input_data.name,
                    input_data.description,
                    input_data.color or "#808080",
                    input_data.sort_order or 0,
                )
            elif action == "update_tag":
                if not input_data.tag_id:
                    raise RuntimeError("REQUIRED: tag_id")
                return await repo.update_tag(input_data.tag_id, input_data)
            elif action == "delete_tag":
                if not input_data.tag_id:
                    raise RuntimeError("REQUIRED: tag_id")
                return await repo.delete_tag(input_data.tag_id)
            elif action == "activate_tag" or action == "deactivate_tag":
                if not input_data.tag_id:
                    raise RuntimeError("REQUIRED: tag_id")
                return await repo.set_tag_status(input_data.tag_id, action == "activate_tag")

            elif action == "list_all":
                cats = await repo.list_categories()
                tags = await repo.list_tags()
                return {"categories": cats, "tags": tags}

            raise RuntimeError(f"UNKNOWN_ACTION: {action}")

        return await with_tenant_context(conn, input_data.admin_user_id, operation)

    except Exception as e:
        log("Admin Tags Internal Error", error=str(e), module=MODULE)
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
