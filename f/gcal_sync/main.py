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

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Synchronize medical booking with Google Calendar
# DB Tables Used  : bookings, providers, clients, services, booking_audit
# Concurrency Risk: LOW — row-level updates on booking sync status
# GCal Calls      : YES — POST/PUT/DELETE events
# Idempotency Key : YES — uses gcal_provider_event_id to prevent duplicates
# RLS Tenant ID   : YES — with_tenant_context wraps all DB ops
# Pydantic Schemas: YES — InputSchema validates all inputs
# ============================================================================
from typing import Any, Literal, cast

from pydantic import BaseModel

from ..internal._db_client import create_db_client
from ..internal._wmill_adapter import log
from ._gcal_api_adapter import fetch_booking_details
from ._gcal_sync_models import GCalSyncResult, InputSchema
from ._sync_event_logic import sync_event
from ._update_sync_status import update_booking_sync_status

MODULE = "gcal_sync"


async def _main_async(args: dict[str, object]) -> GCalSyncResult:
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"Validation error: {e}") from e

    conn = await create_db_client()
    try:
        # 1. Fetch Details
        details = await fetch_booking_details(conn, input_data.tenant_id, input_data.booking_id)

        errors: list[str] = []
        provider_event_id: str | None = details["gcal_provider_event_id"]
        client_event_id: str | None = details["gcal_client_event_id"]

        # 2. Sync Provider Calendar
        try:
            new_prov_id = await sync_event(conn, details, "provider", input_data.action)
        except RuntimeError as err_prov:
            errors.append(f"Provider sync failed: {err_prov}")
        else:
            provider_event_id = new_prov_id or provider_event_id

        # 3. Sync Client Calendar (if available)
        if details["client_calendar_id"]:
            try:
                new_cli_id = await sync_event(conn, details, "client", input_data.action)
            except RuntimeError as err_cli:
                errors.append(f"Client sync failed: {err_cli}")
            else:
                client_event_id = new_cli_id or client_event_id

        # 4. Finalize Status
        sync_status: Literal["synced", "partial", "pending"] = "synced"
        if errors:
            sync_status = "partial" if provider_event_id or client_event_id else "pending"

        await update_booking_sync_status(
            conn,
            input_data.tenant_id,
            input_data.booking_id,
            provider_event_id,
            client_event_id,
            sync_status,
            0,  # retry_count managed by reconcile
            "\n".join(errors) if errors else None,
        )

        result: GCalSyncResult = {
            "booking_id": input_data.booking_id,
            "provider_event_id": provider_event_id,
            "client_event_id": client_event_id,
            "sync_status": sync_status,
            "retry_count": 0,
            "errors": errors,
        }

        return result

    except Exception as e:
        log("Unexpected error in gcal_sync", error=str(e), module=MODULE)
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
