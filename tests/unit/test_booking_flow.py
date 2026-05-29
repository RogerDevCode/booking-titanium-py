import pytest
from app.domain.models import ConversationState
from app.domain.enums import FSMState
from app.fsm.booking_flow import (
    selecting_specialty_handler,
    selecting_doctor_handler,
    selecting_time_handler,
    confirming_booking_handler
)
from app.fsm.main import idle_handler
from app.db.connection import db_client

@pytest.fixture
async def db():
    from app.core.config import settings
    settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"
    await db_client.connect()
    yield
    await db_client.disconnect()

@pytest.mark.asyncio
async def test_full_booking_flow(db):
    """Simulates a full booking flow session."""
    state = ConversationState(chat_id=999)
    
    # 1. Start from IDLE, send "1"
    from app.domain.enums import Intent
    state.context["preflight"] = {"intent": Intent.BOOK_APPOINTMENT}
    await idle_handler(state, "1")
    assert state.state == FSMState.SELECTING_SPECIALTY
    
    # 2. Select Cardiología (Option 1)
    await selecting_specialty_handler(state, "1")
    assert state.state == FSMState.SELECTING_DOCTOR
    assert state.booking_draft["specialty_name"] == "Cardiología"
    
    # 3. Select Dr. Juan Pérez (Option 1)
    await selecting_doctor_handler(state, "1")
    assert state.state == FSMState.SELECTING_TIME
    assert state.booking_draft["doctor_name"] == "Dr. Juan Pérez"
    
    # 4. Select first available slot (Option 1)
    await selecting_time_handler(state, "1")
    assert state.state == FSMState.CONFIRMING_BOOKING
    assert "slot_id" in state.booking_draft
    
    # 5. Confirm with "SI"
    await confirming_booking_handler(state, "SI")
    assert state.state == FSMState.IDLE
    assert state.booking_draft == {}
