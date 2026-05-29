from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import httpx

from ..internal._result import DBClient, with_tenant_context

if TYPE_CHECKING:
    from ._gcal_sync_models import BookingDetails

GCAL_BASE = "https://www.googleapis.com/calendar/v3"


async def fetch_booking_details(db: DBClient, tenant_id: str, booking_id: str) -> BookingDetails:
    async def operation() -> BookingDetails:
        rows = await db.fetch(
            """
            SELECT b.booking_id, b.provider_id, b.status, b.start_time, b.end_time,
                   b.gcal_provider_event_id, b.gcal_client_event_id,
                   p.name as provider_name, p.gcal_calendar_id as provider_calendar_id,
                   p.gcal_access_token as provider_gcal_access_token,
                   p.gcal_refresh_token as provider_gcal_refresh_token,
                   p.gcal_client_id as provider_gcal_client_id,
                   p.gcal_client_secret as provider_gcal_client_secret,
                   pt.name as client_name, pt.gcal_calendar_id as client_calendar_id,
                   s.name as service_name
            FROM bookings b
            JOIN providers p ON p.provider_id = b.provider_id
            JOIN clients pt ON pt.client_id = b.client_id
            JOIN services s ON s.service_id = b.service_id
            WHERE b.booking_id = $1::uuid
            LIMIT 1
            """,
            booking_id,
        )

        if not rows:
            raise RuntimeError(f"Booking {booking_id} not found")

        r = rows[0]
        details: BookingDetails = {
            "booking_id": str(r["booking_id"]),
            "provider_id": str(r["provider_id"]),
            "status": str(r["status"]),
            "start_time": r["start_time"].isoformat()
            if isinstance(r["start_time"], datetime)
            else str(r["start_time"]),
            "end_time": r["end_time"].isoformat() if isinstance(r["end_time"], datetime) else str(r["end_time"]),
            "provider_name": str(r["provider_name"]),
            "service_name": str(r["service_name"]),
            "gcal_provider_event_id": str(r["gcal_provider_event_id"]) if r.get("gcal_provider_event_id") else None,
            "gcal_client_event_id": str(r["gcal_client_event_id"]) if r.get("gcal_client_event_id") else None,
            "provider_calendar_id": str(r["provider_calendar_id"]) if r.get("provider_calendar_id") else None,
            "provider_gcal_access_token": str(r["provider_gcal_access_token"])
            if r.get("provider_gcal_access_token")
            else None,
            "provider_gcal_refresh_token": str(r["provider_gcal_refresh_token"])
            if r.get("provider_gcal_refresh_token")
            else None,
            "provider_gcal_client_id": str(r["provider_gcal_client_id"]) if r.get("provider_gcal_client_id") else None,
            "provider_gcal_client_secret": str(r["provider_gcal_client_secret"])
            if r.get("provider_gcal_client_secret")
            else None,
            "client_calendar_id": str(r["client_calendar_id"]) if r.get("client_calendar_id") else None,
        }
        return details

    return await with_tenant_context(db, tenant_id, operation)


async def call_gcal_api(
    method: str, path: str, calendar_id: str, access_token: str, body: dict[str, object] | None = None
) -> dict[str, Any]:
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
                res_del: dict[str, Any] = {}
                return res_del

            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("GCal API returned non-object response")

            return cast("dict[str, Any]", data)
    except Exception as e:
        raise RuntimeError(f"Network error: {e}") from e
