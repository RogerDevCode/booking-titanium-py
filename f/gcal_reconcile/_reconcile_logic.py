from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypeVar, cast

import httpx

from ..internal.gcal_utils import BookingEventData, build_gcal_event

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ._reconcile_models import BookingRow, SyncResult

T = TypeVar("T")

GCAL_BASE = "https://www.googleapis.com/calendar/v3"


async def retry_with_backoff[T](fn: Callable[[], Awaitable[T]], max_retries: int) -> T:
    last_error = "Unknown error"
    for attempt in range(max_retries):
        try:
            data = await fn()
            return data
        except Exception as e:
            last_error = str(e)
            if "(permanent)" in last_error:
                raise RuntimeError(str(e)) from e

            if attempt < max_retries - 1:
                backoff_s = 3.0**attempt
                await asyncio.sleep(backoff_s)

    raise RuntimeError(f"Failed after {max_retries} retries: {last_error}")


async def call_gcal_api(
    method: str, calendar_id: str, path: str, body: dict[str, object] | None = None
) -> dict[str, object]:
    from ..internal._wmill_adapter import get_variable

    access_token = get_variable("GCAL_ACCESS_TOKEN")
    if not access_token:
        raise RuntimeError("GCAL_ACCESS_TOKEN not configured")

    import urllib.parse

    url = f"{GCAL_BASE}/calendars/{urllib.parse.quote(calendar_id)}/{path}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = await client.request(method, url, headers=headers, json=body)

            if response.status_code >= 400:
                raise RuntimeError(f"GCal API {response.status_code}: {response.text}")

            if method == "DELETE":
                res_del: dict[str, object] = {}
                return res_del

            data = response.json()
            return cast("dict[str, object]", data)
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Network error: {e}") from e


async def sync_booking_to_gcal(booking: BookingRow, max_retries: int) -> SyncResult:
    result: SyncResult = {
        "providerEventId": booking["gcal_provider_event_id"],
        "clientEventId": booking["gcal_client_event_id"],
        "errors": [],
    }

    event_data: BookingEventData = {
        "booking_id": booking["booking_id"],
        "status": booking["status"],
        "start_time": booking["start_time"],
        "end_time": booking["end_time"],
        "provider_name": booking["provider_name"],
        "service_name": booking["service_name"],
    }

    event_body = cast("dict[str, object]", build_gcal_event(event_data))

    # Sync Provider
    if booking["provider_calendar_id"]:
        cal_id = booking["provider_calendar_id"]

        async def sync_op() -> dict[str, object]:
            if result["providerEventId"]:
                return await call_gcal_api("PUT", cal_id, f"events/{result['providerEventId']}", event_body)
            return await call_gcal_api("POST", cal_id, "events", event_body)

        try:
            data_p = await retry_with_backoff(sync_op, max_retries)
            result["providerEventId"] = str(data_p.get("id"))
        except Exception as err_p:
            result["errors"].append(f"Provider: {err_p}")

    # Sync Client
    if booking["client_calendar_id"]:
        cal_id = booking["client_calendar_id"]

        async def sync_op_cli() -> dict[str, object]:
            if result["clientEventId"]:
                return await call_gcal_api("PUT", cal_id, f"events/{result['clientEventId']}", event_body)
            return await call_gcal_api("POST", cal_id, "events", event_body)

        try:
            data_c = await retry_with_backoff(sync_op_cli, max_retries)
            result["clientEventId"] = str(data_c.get("id"))
        except Exception as err_c:
            result["errors"].append(f"Client: {err_c}")

    # Handle Deletion if Cancelled
    if booking["status"] == "cancelled":
        if result["providerEventId"] and booking["provider_calendar_id"]:
            cal_id_del = booking["provider_calendar_id"]
            eid = result["providerEventId"]
            try:
                await retry_with_backoff(
                    lambda: call_gcal_api("DELETE", cal_id_del, f"events/{eid}"),
                    max_retries,
                )
                result["providerEventId"] = None
            except Exception as err_d:
                result["errors"].append(f"Provider delete: {err_d}")

        if result["clientEventId"] and booking["client_calendar_id"]:
            cal_id_del_cli = booking["client_calendar_id"]
            eid_cli = result["clientEventId"]
            try:
                await retry_with_backoff(
                    lambda: call_gcal_api("DELETE", cal_id_del_cli, f"events/{eid_cli}"),
                    max_retries,
                )
                result["clientEventId"] = None
            except Exception as err_d_cli:
                result["errors"].append(f"Client delete: {err_d_cli}")

    return result
