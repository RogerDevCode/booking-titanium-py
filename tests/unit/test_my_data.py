import pytest
from app.domain.models import ConversationState
from app.domain.entities import TelegramUser
from app.domain.enums import FSMState
from app.fsm.profile_flow import my_data_handler
from app.fsm.main import idle_handler
from app.services.user_service import user_service
from app.db.connection import db_client
import os

@pytest.fixture
async def db():
    from app.core.config import settings; settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"
    await db_client.connect()
    # Ensure test user exists
    await user_service.upsert_user(TelegramUser(id=999, first_name="Test", last_name="User"))
    yield
    await db_client.disconnect()

@pytest.mark.asyncio
async def test_my_data_flow(db):
    """Simulates updating user profile data."""
    chat_id = 999
    state = ConversationState(chat_id=chat_id)
    
    # 1. Enter My Data (Option 8)
    from app.domain.enums import Intent
    state.context["preflight"] = {"intent": Intent.MANAGE_PROFILE}
    await idle_handler(state, "8")
    assert state.state == FSMState.UPDATING_PROFILE
    
    # 2. Show Menu (No input yet or invalid)
    await my_data_handler(state, "")
    assert state.context.get("step") == "menu"
    
    # 3. Select Update Phone (Option 2)
    await my_data_handler(state, "2")
    assert state.context.get("step") == "awaiting_value"
    assert state.context.get("field") == "phone"
    
    # 4. Provide invalid phone
    await my_data_handler(state, "blabla")
    assert state.context.get("step") == "awaiting_value" # Should stay here
    
    # 5. Provide valid phone
    new_phone = "+56912345678"
    await my_data_handler(state, new_phone)
    assert state.context.get("step") == "menu"
    
    # 6. Verify in DB
    user = await user_service.get_user(chat_id)
    assert user.phone == new_phone
    
    # 7. Go back to IDLE
    await my_data_handler(state, "4")
    assert state.state == FSMState.IDLE
