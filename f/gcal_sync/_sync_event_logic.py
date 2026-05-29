from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from ..internal.gcal_utils import TokenInfo, build_gcal_event, get_valid_access_token
from ._gcal_api_adapter import call_gcal_api

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._gcal_sync_models import BookingDetails


async def sync_event(
    db: DBClient,
    details: BookingDetails,
    target: Literal["provider", "client"],
    action: Literal["create", "update", "delete"],
) -> str | None:
    calendar_id = details["provider_calendar_id"] if target == "provider" else details["client_calendar_id"]
    event_id = details["gcal_provider_event_id"] if target == "provider" else details["gcal_client_event_id"]

    if not calendar_id:
        res_none: str | None = None
        return res_none

    # 1. Get valid access token
    token_info: TokenInfo = {
        "accessToken": details["provider_gcal_access_token"] or "",
        "clientId": details["provider_gcal_client_id"],
        "clientSecret": details["provider_gcal_client_secret"],
        "refreshToken": details["provider_gcal_refresh_token"],
    }

    access_token = await get_valid_access_token(details["provider_id"], token_info, db)

    # 2. Build event payload
    event_body_raw = build_gcal_event(details, target)
    event_body = cast("dict[str, object] | None", event_body_raw)

    # 3. Determine API Method and Path
    method = "POST"
    path = "events"

    if action == "delete" and event_id:
        method = "DELETE"
        path = f"events/{event_id}"
        event_body = None
    elif (action == "update" or action == "create") and event_id:
        # If we have an ID, we update even if action was 'create' (idempotency)
        method = "PUT"
        path = f"events/{event_id}"

    # 4. Call GCal API
    api_res = await call_gcal_api(method, path, calendar_id, access_token, event_body)

    if method == "DELETE":
        res_del: str | None = None
        return res_del

    new_event_id = str(api_res.get("id")) if api_res else None
    if not new_event_id:
        raise RuntimeError("GCal API did not return event ID")

    return new_event_id
