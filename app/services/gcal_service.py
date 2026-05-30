import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional
import httpx

from app.core.config import Settings
from app.core.logging import logger
from app.domain.protocols import DatabaseClientProtocol

GCAL_BASE = "https://www.googleapis.com/calendar/v3"
DEFAULT_TIMEZONE = "America/Santiago"


class GCalService:
    def __init__(self, db: DatabaseClientProtocol, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    async def _refresh_access_token(
        self, provider_id: int, client_id: str, client_secret: str, refresh_token: str
    ) -> str:
        """
        Refreshes the OAuth2 access token using the refresh token,
        updates the database, and returns the new access token.
        """
        logger.info("Refreshing GCal access token", provider_id=provider_id)
        url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, data=payload)
                if response.status_code != 200:
                    raise RuntimeError(f"Google OAuth refresh failed: {response.text}")

                data = response.json()
                access_token = data.get("access_token")
                if not access_token:
                    raise RuntimeError("No access token returned from Google OAuth")

                # Update token in DB
                await self._db.execute(
                    "UPDATE providers SET gcal_access_token = $1, updated_at = NOW() WHERE id = $2",
                    access_token,
                    provider_id,
                )
                logger.info("Successfully persisted new access token", provider_id=provider_id)
                return str(access_token)

        except Exception as e:
            logger.error("OAuth token refresh failed", provider_id=provider_id, error=str(e))
            raise RuntimeError(f"Failed to refresh access token for provider {provider_id}: {e}") from e

    async def _call_gcal_api(
        self,
        provider_id: int,
        method: str,
        path: str,
        calendar_id: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Makes a request to the Google Calendar API. Handles expired tokens by refreshing
        and retrying the request once.
        """
        # Fetch provider credentials
        provider = await self._db.fetchrow(
            """
            SELECT gcal_access_token, gcal_refresh_token, gcal_client_id, gcal_client_secret
            FROM providers
            WHERE id = $1
            """,
            provider_id,
        )

        if not provider:
            raise ValueError(f"Provider {provider_id} not found")

        access_token = provider["gcal_access_token"]
        refresh_token = provider["gcal_refresh_token"]
        client_id = provider["gcal_client_id"] or self._settings.GCALENDAR_CLIENT_ID
        client_secret = provider["gcal_client_secret"] or self._settings.GCALENDAR_CLIENT_SECRET

        if not access_token and not refresh_token:
            raise RuntimeError(f"No GCal credentials available for provider {provider_id}")

        url = f"{GCAL_BASE}/calendars/{urllib.parse.quote(calendar_id)}/{path}"

        async def make_request(token: str) -> httpx.Response:
            req_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await client.request(method, url, headers=req_headers, json=body)

        # 1. Attempt with current access token
        response = None
        if access_token:
            try:
                response = await make_request(access_token)
            except Exception as e:
                logger.warning("GCal API call failed on network, retrying...", provider_id=provider_id, error=str(e))

        # 2. If token expired (401) or not present, refresh and retry
        if response is None or response.status_code == 401:
            if not refresh_token or not client_id or not client_secret:
                raise RuntimeError(
                    f"Access token expired/invalid and missing refresh credentials for provider {provider_id}"
                )

            new_token = await self._refresh_access_token(provider_id, client_id, client_secret, refresh_token)
            response = await make_request(new_token)

        # 3. Handle response errors
        if response.status_code >= 400:
            if response.status_code == 404 and method == "DELETE":
                # If trying to delete and event is already gone, count as success
                return {}
            raise RuntimeError(f"GCal API error ({response.status_code}): {response.text}")

        if method == "DELETE":
            return {}

        return response.json()

    async def _fetch_booking_details(self, booking_id: int) -> Optional[Dict[str, Any]]:
        query = """
            SELECT 
                b.id as booking_id,
                b.status,
                s.start_time,
                s.end_time,
                p.id as provider_id,
                p.name as provider_name,
                p.gcal_calendar_id,
                sp.name as specialty_name,
                u.first_name || ' ' || COALESCE(u.last_name, '') as user_name
            FROM bookings b
            JOIN slots s ON b.slot_id = s.id
            JOIN providers p ON s.provider_id = p.id
            JOIN specialties sp ON p.specialty_id = sp.id
            JOIN users u ON b.user_id = u.id
            WHERE b.id = $1
        """
        row = await self._db.fetchrow(query, booking_id)
        if not row:
            return None
        return dict(row)

    def _build_event_body(self, details: Dict[str, Any]) -> Dict[str, Any]:
        title = (
            f"[CANCELADO] Hora Médica - {details['provider_name']}"
            if details["status"] == "CANCELLED"
            else f"Hora Médica - {details['provider_name']}"
        )

        description_parts = [
            f"Paciente: {details['user_name']}",
            f"Servicio: {details['specialty_name']}",
            f"ID de reserva: {details['booking_id']}",
            f"Estado: {details['status']}",
            "",
            "Esta hora ha sido cancelada."
            if details["status"] == "CANCELLED"
            else "Para cancelar o reagendar, utiliza el menú de Telegram.",
        ]
        description = "\n".join(description_parts)

        # Format ISO datetimes
        start_time: datetime = details["start_time"]
        end_time: datetime = details["end_time"]

        return {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_time.isoformat(), "timeZone": DEFAULT_TIMEZONE},
            "end": {"dateTime": end_time.isoformat(), "timeZone": DEFAULT_TIMEZONE},
            "status": "cancelled" if details["status"] == "CANCELLED" else "confirmed",
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 1440},  # 24h
                    {"method": "popup", "minutes": 120},  # 2h
                ],
            },
        }

    async def sync_booking_to_gcal(self, booking_id: int) -> None:
        """
        Synchronizes a booking (creation or update) to Google Calendar.
        """
        logger.info("Starting GCal sync for booking", booking_id=booking_id)
        details = await self._fetch_booking_details(booking_id)
        if not details:
            logger.warning("Skipping GCal sync: Booking details not found", booking_id=booking_id)
            return

        calendar_id = details["gcal_calendar_id"]
        if not calendar_id:
            logger.info("Skipping GCal sync: Provider has no calendar ID configured", provider_id=details["provider_id"])
            return

        # Check if event already synced
        gcal_event = await self._db.fetchrow(
            "SELECT gcal_event_id FROM gcal_events WHERE booking_id = $1", booking_id
        )

        event_body = self._build_event_body(details)
        provider_id = details["provider_id"]

        try:
            if gcal_event:
                # Update existing event
                event_id = gcal_event["gcal_event_id"]
                logger.info("Updating existing GCal event", booking_id=booking_id, event_id=event_id)
                await self._call_gcal_api(provider_id, "PUT", f"events/{event_id}", calendar_id, event_body)
                await self._db.execute(
                    "UPDATE gcal_events SET synced_at = NOW() WHERE booking_id = $1", booking_id
                )
            else:
                # Create new event
                logger.info("Creating new GCal event", booking_id=booking_id)
                res = await self._call_gcal_api(provider_id, "POST", "events", calendar_id, event_body)
                new_event_id = res.get("id")
                if not new_event_id:
                    raise RuntimeError("GCal API call did not return an event ID")

                await self._db.execute(
                    """
                    INSERT INTO gcal_events (booking_id, gcal_event_id, gcal_calendar_id, synced_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (booking_id) DO UPDATE 
                    SET gcal_event_id = EXCLUDED.gcal_event_id, gcal_calendar_id = EXCLUDED.gcal_calendar_id, synced_at = NOW()
                    """,
                    booking_id,
                    new_event_id,
                    calendar_id,
                )
            logger.info("GCal sync successful", booking_id=booking_id)
        except Exception as e:
            logger.error("Failed to sync booking to GCal", booking_id=booking_id, error=str(e))
            raise

    async def delete_gcal_event(self, booking_id: int) -> None:
        """
        Deletes the corresponding event in Google Calendar if the booking is cancelled.
        """
        logger.info("Deleting GCal event for booking", booking_id=booking_id)
        gcal_event = await self._db.fetchrow(
            "SELECT gcal_event_id, gcal_calendar_id FROM gcal_events WHERE booking_id = $1", booking_id
        )

        if not gcal_event:
            logger.info("No GCal event found for booking, skipping deletion", booking_id=booking_id)
            return

        event_id = gcal_event["gcal_event_id"]
        calendar_id = gcal_event["gcal_calendar_id"]

        # Fetch provider_id for oauth validation
        row = await self._db.fetchrow(
            "SELECT s.provider_id FROM bookings b JOIN slots s ON b.slot_id = s.id WHERE b.id = $1", booking_id
        )
        provider_id_str = row["provider_id"] if row else None
        if not provider_id_str:
            # Fallback search in audit_log or slots directly if booking slots deleted
            logger.warning("Could not determine provider for booking, skipping API call but removing row", booking_id=booking_id)
            await self._db.execute("DELETE FROM gcal_events WHERE booking_id = $1", booking_id)
            return

        provider_id = int(provider_id_str)

        try:
            logger.info("Calling GCal DELETE", booking_id=booking_id, event_id=event_id)
            await self._call_gcal_api(provider_id, "DELETE", f"events/{event_id}", calendar_id)
            await self._db.execute("DELETE FROM gcal_events WHERE booking_id = $1", booking_id)
            logger.info("GCal deletion successful", booking_id=booking_id)
        except Exception as e:
            logger.error("Failed to delete GCal event", booking_id=booking_id, error=str(e))
            raise

    async def reconcile_all(self, max_retries: int = 5, batch_size: int = 20) -> Dict[str, Any]:
        """
        Identifies and corrects discrepancies between the local database bookings and Google Calendar.
        """
        logger.info("Starting Google Calendar reconciliation run")

        # 1. Identify bookings that are CONFIRMED but have no entry in gcal_events (needs sync)
        unsynced_confirmed = await self._db.fetch(
            """
            SELECT b.id
            FROM bookings b
            JOIN slots s ON b.slot_id = s.id
            JOIN providers p ON s.provider_id = p.id
            LEFT JOIN gcal_events ge ON b.id = ge.booking_id
            WHERE b.status = 'CONFIRMED'
              AND ge.booking_id IS NULL
              AND p.gcal_calendar_id IS NOT NULL
            ORDER BY b.created_at ASC
            LIMIT $1
            """,
            batch_size,
        )

        # 2. Identify bookings that are CANCELLED but still have an entry in gcal_events (needs deletion)
        unsynced_cancelled = await self._db.fetch(
            """
            SELECT b.id
            FROM bookings b
            JOIN gcal_events ge ON b.id = ge.booking_id
            WHERE b.status = 'CANCELLED'
            ORDER BY b.updated_at ASC
            LIMIT $1
            """,
            batch_size,
        )

        results = {
            "created": 0,
            "deleted": 0,
            "failed_create": 0,
            "failed_delete": 0,
        }

        for row in unsynced_confirmed:
            booking_id = row["id"]
            try:
                await self.sync_booking_to_gcal(booking_id)
                results["created"] += 1
            except Exception as e:
                logger.error("Reconciliation failed to create event", booking_id=booking_id, error=str(e))
                results["failed_create"] += 1

        for row in unsynced_cancelled:
            booking_id = row["id"]
            try:
                await self.delete_gcal_event(booking_id)
                results["deleted"] += 1
            except Exception as e:
                logger.error("Reconciliation failed to delete event", booking_id=booking_id, error=str(e))
                results["failed_delete"] += 1

        logger.info("Google Calendar reconciliation completed", results=results)
        return results
