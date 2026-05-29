import pytest
from app.domain.models import ConversationState
from app.domain.enums import FSMState
from app.fsm.faq_flow import waiting_faq_handler
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
async def test_faq_flow(db):
    """Simulates a user asking a question."""
    chat_id = 999
    state = ConversationState(chat_id=chat_id)
    
    # 1. Enter Information (Option 7)
    from app.domain.enums import Intent
    state.context["preflight"] = {"intent": Intent.GET_INFO}
    await idle_handler(state, "7")
    assert state.state == FSMState.WAITING_FAQ
    
    # 2. Ask a question
    # Note: AIService will return a stub message if API key is missing
    await waiting_faq_handler(state, "¿Cuáles son los horarios?")
    assert state.state == FSMState.WAITING_FAQ # Stay to allow follow-up
    
    # 3. Exit back to IDLE
    await waiting_faq_handler(state, "4")
    assert state.state == FSMState.IDLE
