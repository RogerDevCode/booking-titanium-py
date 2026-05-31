import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from app.worker.tasks import make_process_message
from app.domain.entities import TelegramUser

@pytest.mark.asyncio
async def test_faq_multi_turn_history_and_timeout(fake_container) -> None:
    # 1. Setup mock services
    fake_container.rag_service.search = AsyncMock(return_value=[])
    fake_container.rag_service.format_context = MagicMock(return_value="[RAG Context Documents]")
    
    # We will capture the context passed to the AI service
    captured_contexts = []
    async def mock_get_response(user_text, context=None):
        captured_contexts.append(context)
        return f"Response to {user_text}"
        
    fake_container.ai_service.get_response = mock_get_response
    fake_container.ai_service.api_key = "fake_key"
    
    # 2. Setup user state in WAITING_FAQ state
    chat_id = 77777
    state = ConversationState(
        chat_id=chat_id,
        state=FSMState.WAITING_FAQ,
        context={}
    )
    
    # Mock conversation transaction to return this state
    fake_container.conversation_tx.get_state = AsyncMock(return_value=state)
    fake_container.conversation_tx.set_state = AsyncMock()
    
    # Mock user_service upsert to succeed
    fake_container.user_service.upsert_user = AsyncMock(return_value=(TelegramUser(id=chat_id, first_name="Test"), False))
    
    # Instantiate the message processor task
    process_message = make_process_message(fake_container)
    
    # --- Question 1 ---
    payload1 = {
        "message": {
            "chat": {"id": chat_id, "first_name": "Test"},
            "text": "¿Cómo puedo agendar?"
        }
    }
    await process_message({}, payload1)
    
    # Verify first call context had no conversation history
    assert len(captured_contexts) == 1
    assert "[RAG Context Documents]" in captured_contexts[0]
    assert "Historial reciente" not in captured_contexts[0]
    
    # Verify state history was updated
    assert len(state.context["faq_history"]) == 1
    assert state.context["faq_history"][0]["question"] == "¿Cómo puedo agendar?"
    assert state.context["faq_history"][0]["answer"] == "Response to ¿Cómo puedo agendar?"
    assert state.context["faq_last_interaction"] is not None
    
    # --- Question 2 ---
    payload2 = {
        "message": {
            "chat": {"id": chat_id},
            "text": "¿Cuánto cuesta?"
        }
    }
    await process_message({}, payload2)
    
    # Verify second call context includes the history of Question 1
    assert len(captured_contexts) == 2
    assert "Historial reciente de la conversación" in captured_contexts[1]
    assert "¿Cómo puedo agendar?" in captured_contexts[1]
    assert "Response to ¿Cómo puedo agendar?" in captured_contexts[1]
    
    # Verify history grows
    assert len(state.context["faq_history"]) == 2
    assert state.context["faq_history"][1]["question"] == "¿Cuánto cuesta?"
    
    # --- Question 3 (simulate inactivity timeout) ---
    # Manually backdate the last interaction to > 5 minutes ago
    state.context["faq_last_interaction"] = time.time() - 310
    
    payload3 = {
        "message": {
            "chat": {"id": chat_id},
            "text": "¿Cuáles son sus horarios?"
        }
    }
    await process_message({}, payload3)
    
    # Verify history was cleared due to inactivity timeout
    assert len(captured_contexts) == 3
    assert "¿Cómo puedo agendar?" not in captured_contexts[2]
    assert "¿Cuánto cuesta?" not in captured_contexts[2]
    assert len(state.context["faq_history"]) == 1
    assert state.context["faq_history"][0]["question"] == "¿Cuáles son sus horarios?"
