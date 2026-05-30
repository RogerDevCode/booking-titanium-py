import pytest
from unittest.mock import patch, MagicMock

from app.worker.tasks import make_sync_booking_to_gcal, make_delete_gcal_event, make_cron_reconcile_gcal


@pytest.fixture
def mock_gcal_api():
    """
    Mock out the httpx calls to Google Calendar.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "integration-gcal-event-999"}
    
    with patch("httpx.AsyncClient.request", return_value=mock_resp) as mock_req:
        yield mock_req


@pytest.fixture
def mock_gcal_oauth():
    """
    Mock Google Calendar OAuth Token endpoint.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "integration-access-token"}
    
    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        yield mock_post


@pytest.mark.asyncio
async def test_gcal_integration_flow(integration_container, clean_db_and_redis, mock_gcal_api):
    db = integration_container.db_client
    chat_id = 99999
    
    # 0. Setup test user
    await db.execute("INSERT INTO users (id, first_name) VALUES ($1, 'TestUser') ON CONFLICT DO NOTHING", chat_id)
    
    # 1. Setup specialties, providers, schedules, and slots in DB
    spec_id = 500
    doc_id = 600
    await db.execute(
        f"INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES ({spec_id}, 'General') ON CONFLICT DO NOTHING"
    )
    await db.execute(
        f"INSERT INTO providers (id, name, specialty_id, is_active, gcal_calendar_id, gcal_access_token) "
        f"OVERRIDING SYSTEM VALUE VALUES ({doc_id}, 'Dra. González', {spec_id}, true, 'primary-cal-id', 'valid-token') ON CONFLICT DO NOTHING"
    )
    
    # Create slots
    slot_id = 700
    await db.execute(
        f"INSERT INTO slots (id, provider_id, start_time, end_time, is_available) "
        f"OVERRIDING SYSTEM VALUE VALUES ({slot_id}, {doc_id}, '2030-05-30 10:00:00+00', '2030-05-30 10:30:00+00', true)"
    )

    # 2. Directly create a booking via BookingService (simulate FSM router)
    booking = await integration_container.booking_service.create_booking(chat_id, str(slot_id))
    assert booking is not None
    assert booking.status.value == "CONFIRMED"
    
    # Verify booking exists in DB
    booking_row = await db.fetchrow("SELECT status FROM bookings WHERE id = $1", booking.id)
    assert booking_row["status"] == "CONFIRMED"
    
    # 3. Trigger GCal sync task directly (Worker Job)
    sync_task = make_sync_booking_to_gcal(integration_container)
    await sync_task({}, booking.id)
    
    # Check that event was successfully registered in gcal_events table!
    gcal_row = await db.fetchrow("SELECT gcal_event_id, gcal_calendar_id FROM gcal_events WHERE booking_id = $1", booking.id)
    assert gcal_row is not None
    assert gcal_row["gcal_event_id"] == "integration-gcal-event-999"
    assert gcal_row["gcal_calendar_id"] == "primary-cal-id"
    
    # 4. Cancel the booking
    await integration_container.booking_service.cancel_booking(chat_id, booking.id)
    
    # Verify booking cancelled in DB
    booking_row = await db.fetchrow("SELECT status FROM bookings WHERE id = $1", booking.id)
    assert booking_row["status"] == "CANCELLED"
    
    # 5. Trigger GCal delete task directly (Worker Job)
    delete_task = make_delete_gcal_event(integration_container)
    await delete_task({}, booking.id)
    
    # Check that event was deleted from gcal_events table!
    gcal_row = await db.fetchrow("SELECT gcal_event_id FROM gcal_events WHERE booking_id = $1", booking.id)
    assert gcal_row is None


@pytest.mark.asyncio
async def test_gcal_reconciliation_flow(integration_container, clean_db_and_redis, mock_gcal_api):
    db = integration_container.db_client
    chat_id = 99998
    spec_id = 501
    doc_id = 601
    
    # Setup test user
    await db.execute("INSERT INTO users (id, first_name) VALUES ($1, 'TestUser') ON CONFLICT DO NOTHING", chat_id)
    
    # Setup DB
    await db.execute(
        f"INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES ({spec_id}, 'Dental') ON CONFLICT DO NOTHING"
    )
    await db.execute(
        f"INSERT INTO providers (id, name, specialty_id, is_active, gcal_calendar_id, gcal_access_token) "
        f"OVERRIDING SYSTEM VALUE VALUES ({doc_id}, 'Dr. Pérez', {spec_id}, true, 'provider-cal-id', 'valid-token') ON CONFLICT DO NOTHING"
    )
    
    slot_id_1 = 701
    slot_id_2 = 702
    await db.execute(
        f"INSERT INTO slots (id, provider_id, start_time, end_time, is_available) "
        f"OVERRIDING SYSTEM VALUE VALUES ({slot_id_1}, {doc_id}, '2030-06-01 10:00:00+00', '2030-06-01 10:30:00+00', true)"
    )
    await db.execute(
        f"INSERT INTO slots (id, provider_id, start_time, end_time, is_available) "
        f"OVERRIDING SYSTEM VALUE VALUES ({slot_id_2}, {doc_id}, '2030-06-01 11:00:00+00', '2030-06-01 11:30:00+00', true)"
    )

    # 1. Create a booking (confirmed, but we won't sync it yet to simulate unsynced state)
    booking1 = await integration_container.booking_service.create_booking(chat_id, str(slot_id_1))
    
    # 2. Create another booking and manually insert it into gcal_events, then cancel it in DB (unsynced cancellation state)
    booking2 = await integration_container.booking_service.create_booking(chat_id, str(slot_id_2))
    await db.execute(
        "INSERT INTO gcal_events (booking_id, gcal_event_id, gcal_calendar_id) VALUES ($1, $2, $3)",
        booking2.id, "google-event-delete-later", "provider-cal-id"
    )
    await integration_container.booking_service.cancel_booking(chat_id, booking2.id)

    # Validate initial states
    gcal_row_1 = await db.fetchrow("SELECT * FROM gcal_events WHERE booking_id = $1", booking1.id)
    gcal_row_2 = await db.fetchrow("SELECT * FROM gcal_events WHERE booking_id = $1", booking2.id)
    assert gcal_row_1 is None  # Confirmed but not in gcal_events
    assert gcal_row_2 is not None  # Cancelled but still in gcal_events
    
    # 3. Trigger reconciliation cron
    cron_task = make_cron_reconcile_gcal(integration_container)
    await cron_task({})
    
    # 4. Verify self-healing corrections
    gcal_row_1_after = await db.fetchrow("SELECT gcal_event_id FROM gcal_events WHERE booking_id = $1", booking1.id)
    gcal_row_2_after = await db.fetchrow("SELECT gcal_event_id FROM gcal_events WHERE booking_id = $1", booking2.id)
    
    assert gcal_row_1_after is not None
    assert gcal_row_1_after["gcal_event_id"] == "integration-gcal-event-999"  # Auto-created
    assert gcal_row_2_after is None  # Auto-deleted
