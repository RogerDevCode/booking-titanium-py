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
from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ._noshow_models import NoShowStats

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Mark expired confirmed bookings as no_show
# DB Tables Used  : providers, bookings, booking_audit
# Concurrency Risk: YES — batch updates
# GCal Calls      : NO
# Idempotency Key : YES — state machine transition is idempotent
# RLS Tenant ID   : YES — with_tenant_context per provider
# Pydantic Schemas: YES — InputSchema validates parameters
# ============================================================================
from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._noshow_logic import BookingRepository
from ._noshow_models import InputSchema, NoShowStats

MODULE = "noshow_trigger"


async def _main_async(args: dict[str, object]) -> NoShowStats:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"validation_error: {e}") from e

    conn = await create_db_client()
    try:
        # 2. Fetch active providers
        provider_rows = await conn.fetch("SELECT provider_id FROM providers WHERE is_active = True")

        aggregate: NoShowStats = {"processed": 0, "marked": 0, "skipped": 0, "booking_ids": []}

        def make_batch(provider_id: str) -> Callable[[], Coroutine[Any, Any, NoShowStats]]:
            async def provider_batch() -> NoShowStats:
                repo = BookingRepository(conn)
                ids = await repo.find_expired_confirmed(input_data.lookback_minutes)
                if not ids:
                    res_empty: NoShowStats = {"processed": 0, "marked": 0, "skipped": 0, "booking_ids": []}
                    return res_empty

                marked = 0
                skipped = 0
                processed_ids: list[str] = []

                for bid in ids:
                    if input_data.dry_run:
                        skipped += 1
                        processed_ids.append(bid)
                        continue

                    try:
                        await repo.mark_as_no_show(bid)
                        marked += 1
                    except Exception as err_mark:
                        log(f"Failed to mark booking {bid} as no-show", error=str(err_mark), module=MODULE)
                        continue

                    processed_ids.append(bid)

                res_batch: NoShowStats = {
                    "processed": len(ids),
                    "marked": marked,
                    "skipped": skipped,
                    "booking_ids": processed_ids,
                }
                return res_batch

            return provider_batch

        for prow in provider_rows:
            p_id = str(prow["provider_id"])
            res_p = await with_tenant_context(conn, p_id, make_batch(p_id))
            aggregate["processed"] += res_p["processed"]
            aggregate["marked"] += res_p["marked"]
            aggregate["skipped"] += res_p["skipped"]
            aggregate["booking_ids"].extend(res_p["booking_ids"])

        return aggregate

    except Exception as e:
        log("No-Show Trigger Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"internal_error: {e}") from e
    finally:
        await conn.close()


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
