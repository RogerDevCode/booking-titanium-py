import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from app.services.gcal_service import GCalService
from app.core.config import Settings
from app.domain.protocols import DatabaseClientProtocol


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock(spec=DatabaseClientProtocol)
    # Mocking transaction context manager
    tx_mock = AsyncMock()
    tx_mock.__aenter__.return_value = None
    tx_mock.__aexit__.return_value = None
    db.transaction.return_value = tx_mock
    return db


@pytest.fixture
def mock_settings() -> Settings:
    s = Settings(
        DATABASE_URL="postgresql://test",
        TELEGRAM_BOT_TOKEN="test_token",
        TELEGRAM_ID=123,
    )
    s.GCALENDAR_CLIENT_ID = "global-client-id"
    s.GCALENDAR_CLIENT_SECRET = "global-client-secret"
    s.GCALENDAR_API_KEY = "global-api-key"
    return s


@pytest.fixture
def gcal_service(mock_db, mock_settings) -> GCalService:
    return GCalService(db=mock_db, settings=mock_settings)


@pytest.mark.asyncio
async def test_sync_booking_to_gcal_create_new(gcal_service, mock_db):
    """
    Test when booking is CONFIRMED and has no previous event in gcal_events.
    Should call GCal API with POST and insert event into gcal_events.
    """
    booking_id = 100
    provider_id = 5

    # Mock DB queries
    mock_db.fetchrow.side_effect = [
        # 1. _fetch_booking_details
        {
            "booking_id": booking_id,
            "status": "CONFIRMED",
            "start_time": datetime.now(),
            "end_time": datetime.now() + timedelta(minutes=30),
            "provider_id": provider_id,
            "provider_name": "Dra. González",
            "gcal_calendar_id": "primary",
            "specialty_name": "Medicina General",
            "user_name": "Juan Pérez",
        },
        # 2. Check if event already synced (gcal_events)
        None,
        # 3. Provider credentials select (inside _call_gcal_api)
        {
            "gcal_access_token": "valid-access-token",
            "gcal_refresh_token": "valid-refresh-token",
            "gcal_client_id": None,
            "gcal_client_secret": None,
        },
    ]

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "google-event-id-999"}

    with patch("httpx.AsyncClient.request", return_value=mock_response) as mock_request:
        await gcal_service.sync_booking_to_gcal(booking_id)

        # Assert httpx called correctly
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        method, url = args
        assert method == "POST"
        assert "calendars/primary/events" in url
        assert kwargs["json"]["summary"] == "Hora Médica - Dra. González"
        assert kwargs["json"]["status"] == "confirmed"

        # Assert insertion to database
        mock_db.execute.assert_called_once()
        exec_args = mock_db.execute.call_args[0]
        assert "INSERT INTO gcal_events" in exec_args[0]
        assert exec_args[1] == booking_id
        assert exec_args[2] == "google-event-id-999"
        assert exec_args[3] == "primary"


@pytest.mark.asyncio
async def test_sync_booking_to_gcal_update_existing(gcal_service, mock_db):
    """
    Test when booking has already been synced to GCal.
    Should call GCal API with PUT and update synced_at timestamp.
    """
    booking_id = 101
    provider_id = 6

    mock_db.fetchrow.side_effect = [
        # 1. _fetch_booking_details
        {
            "booking_id": booking_id,
            "status": "CONFIRMED",
            "start_time": datetime.now(),
            "end_time": datetime.now() + timedelta(minutes=30),
            "provider_id": provider_id,
            "provider_name": "Dr. Pérez",
            "gcal_calendar_id": "c-123",
            "specialty_name": "Odontología",
            "user_name": "Ana Gómez",
        },
        # 2. Check if event already synced (gcal_events)
        {"gcal_event_id": "existing-event-777"},
        # 3. Provider credentials select
        {
            "gcal_access_token": "valid-access-token",
            "gcal_refresh_token": "valid-refresh-token",
            "gcal_client_id": None,
            "gcal_client_secret": None,
        },
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "existing-event-777"}

    with patch("httpx.AsyncClient.request", return_value=mock_response) as mock_request:
        await gcal_service.sync_booking_to_gcal(booking_id)

        # Assert httpx PUT request is made
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        method, url = args
        assert method == "PUT"
        assert "calendars/c-123/events/existing-event-777" in url

        # Assert database update
        mock_db.execute.assert_called_once()
        exec_args = mock_db.execute.call_args[0]
        assert "UPDATE gcal_events" in exec_args[0]
        assert exec_args[1] == booking_id


@pytest.mark.asyncio
async def test_sync_booking_to_gcal_token_refresh(gcal_service, mock_db):
    """
    Test token refresh logic. If initial request returns 401,
    it should request a new access token, update the DB, and retry once.
    """
    booking_id = 102
    provider_id = 7

    mock_db.fetchrow.side_effect = [
        # 1. _fetch_booking_details
        {
            "booking_id": booking_id,
            "status": "CONFIRMED",
            "start_time": datetime.now(),
            "end_time": datetime.now() + timedelta(minutes=30),
            "provider_id": provider_id,
            "provider_name": "Dr. Pérez",
            "gcal_calendar_id": "c-123",
            "specialty_name": "Odontología",
            "user_name": "Ana Gómez",
        },
        # 2. Check if event already synced (gcal_events)
        None,
        # 3. Provider credentials select (first try)
        {
            "gcal_access_token": "expired-access-token",
            "gcal_refresh_token": "valid-refresh-token",
            "gcal_client_id": None,
            "gcal_client_secret": None,
        },
        # 4. Provider credentials select (retry try after refresh)
        {
            "gcal_access_token": "new-access-token",
            "gcal_refresh_token": "valid-refresh-token",
            "gcal_client_id": None,
            "gcal_client_secret": None,
        },
    ]

    # Mock GCal responses: first 401 Unauthorized, second 200 OK
    resp_expired = MagicMock()
    resp_expired.status_code = 401

    resp_success = MagicMock()
    resp_success.status_code = 200
    resp_success.json.return_value = {"id": "new-event-id"}

    # Mock Google Token Refresh endpoint response
    resp_refresh = MagicMock()
    resp_refresh.status_code = 200
    resp_refresh.json.return_value = {"access_token": "new-access-token", "expires_in": 3600}

    with patch("httpx.AsyncClient.request", side_effect=[resp_expired, resp_success]) as mock_request, \
         patch("httpx.AsyncClient.post", return_value=resp_refresh) as mock_post:
        
        await gcal_service.sync_booking_to_gcal(booking_id)

        # Verify Google OAuth endpoint called
        mock_post.assert_called_once()
        post_kwargs = mock_post.call_args[1]
        assert post_kwargs["data"]["client_id"] == "global-client-id"
        assert post_kwargs["data"]["refresh_token"] == "valid-refresh-token"

        # Verify new token persisted to provider record
        mock_db.execute.assert_any_call(
            "UPDATE providers SET gcal_access_token = $1, updated_at = NOW() WHERE id = $2",
            "new-access-token",
            provider_id
        )

        # Verify retry request was made
        assert mock_request.call_count == 2
        first_call = mock_request.call_args_list[0]
        second_call = mock_request.call_args_list[1]
        assert first_call[1]["headers"]["Authorization"] == "Bearer expired-access-token"
        assert second_call[1]["headers"]["Authorization"] == "Bearer new-access-token"


@pytest.mark.asyncio
async def test_delete_gcal_event_success(gcal_service, mock_db):
    """
    Test deleting a Google Calendar event.
    """
    booking_id = 103

    # Mock DB queries in sequence of fetchrow calls
    mock_db.fetchrow.side_effect = [
        # 1. Select event_id and calendar_id from gcal_events
        {
            "gcal_event_id": "google-event-delete-123",
            "gcal_calendar_id": "primary",
        },
        # 2. Select provider_id from bookings/slots
        {
            "provider_id": 8,
        },
        # 3. Select credentials from providers
        {
            "gcal_access_token": "valid-token",
            "gcal_refresh_token": "valid-refresh",
            "gcal_client_id": None,
            "gcal_client_secret": None,
        }
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.request", return_value=mock_response) as mock_request:
        await gcal_service.delete_gcal_event(booking_id)

        # Assert DELETE request
        mock_request.assert_called_once()
        args = mock_request.call_args[0]
        assert args[0] == "DELETE"
        assert "calendars/primary/events/google-event-delete-123" in args[1]

        # Assert record deletion in database
        mock_db.execute.assert_called_once()
        exec_args = mock_db.execute.call_args[0]
        assert "DELETE FROM gcal_events" in exec_args[0]
        assert exec_args[1] == booking_id


@pytest.mark.asyncio
async def test_reconcile_all(gcal_service, mock_db):
    """
    Test reconciliation query and processing.
    """
    # 1. Mock DB select for unsynced confirmed bookings
    mock_db.fetch.side_effect = [
        # Unsynced confirmed bookings
        [{"id": 201}, {"id": 202}],
        # Unsynced cancelled bookings
        [{"id": 301}],
    ]

    # Mock sync_booking_to_gcal and delete_gcal_event methods
    gcal_service.sync_booking_to_gcal = AsyncMock()
    gcal_service.delete_gcal_event = AsyncMock()

    results = await gcal_service.reconcile_all()

    # Verify calls
    assert gcal_service.sync_booking_to_gcal.call_count == 2
    gcal_service.sync_booking_to_gcal.assert_any_call(201)
    gcal_service.sync_booking_to_gcal.assert_any_call(202)

    assert gcal_service.delete_gcal_event.call_count == 1
    gcal_service.delete_gcal_event.assert_any_call(301)

    assert results["created"] == 2
    assert results["deleted"] == 1
