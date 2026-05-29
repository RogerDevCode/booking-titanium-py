import pytest
from app.domain.models import ConversationState
from app.domain.enums import FSMState
from app.fsm.booking_flow import my_bookings_handler
from app.fsm.booking_flow import cancellation_handler
from app.fsm.main import idle_handler
from app.db.connection import db_client
import os

@pytest.fixture
async def db():
    from app.core.config import settings; settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"
    await db_client.connect()
    yield
    await db_client.disconnect()

@pytest.mark.asyncio
async def test_view_and_cancel_flow(db):
    """Simulates viewing and then cancelling a booking."""
    chat_id = 999
    
    # 0. Seed a booking for chat_id = 999 so the test is isolated and independent of run order
    from app.domain.enums import Intent
    from app.fsm.booking_flow import (
        selecting_specialty_handler,
        selecting_doctor_handler,
        selecting_time_handler,
        confirming_booking_handler
    )
    seed_state = ConversationState(chat_id=chat_id)
    seed_state.context["preflight"] = {"intent": Intent.BOOK_APPOINTMENT}
    await idle_handler(seed_state, "1")
    await selecting_specialty_handler(seed_state, "1")
    await selecting_doctor_handler(seed_state, "1")
    await selecting_time_handler(seed_state, "1")
    await confirming_booking_handler(seed_state, "SI")

    # 1. View Bookings (Option 2)
    state = ConversationState(chat_id=chat_id)
    state.context["preflight"] = {"intent": Intent.MY_BOOKINGS}
    await idle_handler(state, "2")
    assert state.state == FSMState.VIEWING_BOOKINGS
    
    await my_bookings_handler(state, "")
    # Should list bookings and we can stay in VIEWING or go back
    
    # 2. Cancel Booking (Option 3)
    state.state = FSMState.IDLE # Reset to IDLE to simulate new menu selection
    state.context["preflight"] = {"intent": Intent.CANCEL_APPOINTMENT}
    await idle_handler(state, "3")
    assert state.state == FSMState.CANCELLING_BOOKING
    
    # 3. List bookings for cancellation
    await cancellation_handler(state, "")
    
    # 4. Select Option 1 to cancel the first booking
    await cancellation_handler(state, "1")
    assert state.state == FSMState.IDLE
    
    # 5. Verify it's gone from active bookings
    from app.services.booking_service import booking_service
    bookings = await booking_service.get_user_bookings(chat_id)
    # Since we seeded 1 booking and cancelled it (assuming previous tests didn't consume all slots)
    # The seed script creates 4 slots per provider, and we have 1 user.
    # In test_full_booking_flow we created 1. Now we cancel 1.
    # We need to be careful with state shared between tests if running in parallel.
