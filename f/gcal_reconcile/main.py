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

if TYPE_CHECKING:
    from collections.abc import Coroutine

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Cron job to retry pending GCal syncs (every 5 minutes)
# DB Tables Used  : bookings, providers, clients, services
# Concurrency Risk: YES — batch-based processing
# GCal Calls      : YES — POST/PUT/DELETE events
# Idempotency Key : YES — managed by sync logic
# RLS Tenant ID   : YES — with_tenant_context wraps each provider's batch
# Pydantic Schemas: YES — InputSchema validates all inputs
# ============================================================================
from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._reconcile_logic import sync_booking_to_gcal
from ._reconcile_models import BookingRow, InputSchema, ReconcileResult, SyncResult

MODULE = "gcal_reconcile"


async def _main_async(args: dict[str, object]) -> ReconcileResult:
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 1. Fetch all active providers (admin mode - no RLS)
        providers = await conn.fetch("SELECT provider_id FROM providers WHERE is_active = True")

        aggregate: ReconcileResult = {
            "processed": 0,
            "synced": 0,
            "partial": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        }

        for p in providers:
            p_id = str(p["provider_id"])

            async def provider_batch() -> ReconcileResult:
                # Fetch pending bookings for this provider
                booking_rows = await conn.fetch(
                    """
                    SELECT b.booking_id, b.status, b.start_time, b.end_time,
                           b.gcal_provider_event_id, b.gcal_client_event_id,
                           b.gcal_retry_count,
                           p.name as provider_name, p.gcal_calendar_id as provider_calendar_id,
                           pt.name as client_name, pt.gcal_calendar_id as client_calendar_id,
                           s.name as service_name
                    FROM bookings b
                    JOIN providers p ON p.provider_id = b.provider_id
                    JOIN clients pt ON pt.client_id = b.client_id
                    JOIN services s ON s.service_id = b.service_id
                    WHERE b.provider_id = $1::uuid
                      AND b.gcal_sync_status IN ('pending', 'partial')
                      AND b.gcal_retry_count < $2
                    ORDER BY b.created_at ASC
                    LIMIT $3
                    """,
                    p_id,  # noqa: B023
                    input_data.max_gcal_retries,
                    input_data.batch_size,
                )

                res: ReconcileResult = {
                    "processed": 0,
                    "synced": 0,
                    "partial": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": [],
                }

                bookings_list: list[BookingRow] = []
                tasks: list[Coroutine[Any, Any, SyncResult]] = []
                for row_raw in booking_rows:
                    res["processed"] += 1
                    if input_data.dry_run:
                        res["skipped"] += 1
                        continue

                    row = row_raw
                    booking = cast(
                        "BookingRow",
                        {
                            "booking_id": str(row["booking_id"]),
                            "status": str(row["status"]),
                            "start_time": str(row["start_time"]),
                            "end_time": str(row["end_time"]),
                            "gcal_provider_event_id": str(row["gcal_provider_event_id"])
                            if row.get("gcal_provider_event_id")
                            else None,
                            "gcal_client_event_id": str(row["gcal_client_event_id"])
                            if row.get("gcal_client_event_id")
                            else None,
                            "gcal_retry_count": int(cast("Any", row["gcal_retry_count"])),
                            "provider_name": str(row["provider_name"]),
                            "provider_calendar_id": str(row["provider_calendar_id"])
                            if row.get("provider_calendar_id")
                            else None,
                            "client_name": str(row["client_name"]),
                            "client_calendar_id": str(row["client_calendar_id"])
                            if row.get("client_calendar_id")
                            else None,
                            "service_name": str(row["service_name"]),
                        },
                    )
                    bookings_list.append(booking)
                    tasks.append(sync_booking_to_gcal(booking, input_data.max_retries))

                if tasks:
                    sync_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for booking, sync_res in zip(bookings_list, sync_results, strict=False):
                        if isinstance(sync_res, BaseException):
                            res["failed"] += 1
                            res["errors"].append(f"Booking {booking['booking_id']}: Exception {sync_res}")
                            continue

                        status: str
                        if not sync_res["errors"]:
                            status = "synced"
                            res["synced"] += 1
                        elif sync_res["providerEventId"] or sync_res["clientEventId"]:
                            status = "partial"
                            res["partial"] += 1
                        else:
                            status = "pending"
                            res["failed"] += 1

                        if sync_res["errors"]:
                            res["errors"].append(f"Booking {booking['booking_id']}: {'; '.join(sync_res['errors'])}")

                        await conn.execute(
                            """
                            UPDATE bookings
                            SET gcal_provider_event_id = $1,
                                gcal_client_event_id = $2,
                                gcal_sync_status = $3,
                                gcal_retry_count = gcal_retry_count + 1,
                                gcal_last_sync = NOW()
                            WHERE booking_id = $4::uuid
                            """,
                            sync_res["providerEventId"],
                            sync_res["clientEventId"],
                            status,
                            booking["booking_id"],
                        )
                return res

            try:
                res_batch = await with_tenant_context(conn, p_id, provider_batch)
            except RuntimeError as err_batch:
                aggregate["errors"].append(f"Provider {p_id}: {err_batch}")
                continue

            aggregate["processed"] += res_batch["processed"]
            aggregate["synced"] += res_batch["synced"]
            aggregate["partial"] += res_batch["partial"]
            aggregate["failed"] += res_batch["failed"]
            aggregate["skipped"] += res_batch["skipped"]
            aggregate["errors"].extend(res_batch["errors"])

        return aggregate

    except Exception as e:
        log("Unexpected error in gcal_reconcile", error=str(e), module=MODULE)
        raise RuntimeError(f"Internal error: {e}") from e
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
