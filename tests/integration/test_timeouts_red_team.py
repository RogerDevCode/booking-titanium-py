import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from app.worker.tasks import process_message
from app.db.connection import db_client
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from app.db.conversation_tx import ConversationTransaction

@pytest.fixture
async def setup_db():
    from app.core.config import settings
    from app.db.redis_client import redis_client
    settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"
    settings.REDIS_URL = "redis://localhost:6379"
    await db_client.connect()
    await redis_client.connect()
    yield
    await db_client.disconnect()
    await redis_client.disconnect()

@pytest.mark.asyncio
async def test_intent_classifier_timeout(setup_db):
    """
    Test that when the IntentClassifier hangs for 5 seconds, 
    the system correctly aborts at 2.5s and defaults to IDLE / UNKNOWN.
    """
    chat_id = 10001
    state = ConversationState(chat_id=chat_id, state=FSMState.IDLE)
    await ConversationTransaction.set_state(state)

    payload = {
        "message": {
            "chat": {"id": chat_id},
            "text": "quiero agendar una hora pero el modelo va a fallar"
        }
    }

    # Mock the classifier to sleep for 5 seconds
    async def slow_classify(*args, **kwargs):
        await asyncio.sleep(5.0)
        return "Intent.BOOK_APPOINTMENT", 1.0

    with patch('app.pipeline.classifier.IntentClassifier.classify', side_effect=slow_classify):
        # We also mock telegram sender to not actually hit the API
        with patch('app.telegram.sender.telegram_sender.send_message', new_callable=AsyncMock) as mock_send:
            with patch('app.telegram.sender.telegram_sender.flush_outbox', new_callable=AsyncMock):
                
                start_time = asyncio.get_event_loop().time()
                await process_message({}, payload)
                elapsed = asyncio.get_event_loop().time() - start_time
                
                # Should take approx 2.5 seconds, definitely less than 4.5
                assert elapsed < 4.5, f"Timeout failed! Took {elapsed}s"
                
                # Verify that it gracefully fell back to the Main Menu (Intent.UNKNOWN)
                state = await ConversationTransaction.get_state(chat_id)
                assert state.state == FSMState.IDLE
                
                # It should have queued the main menu text
                # We can check that send_message was called with the menu
                mock_send.assert_called()
                call_args = mock_send.call_args[0]
                assert "Bienvenido al Sistema de Reservas Titanium" in call_args[1]

@pytest.mark.asyncio
async def test_ai_service_timeout(setup_db):
    """
    Test that when the RAG/AI Service hangs, it aborts and notifies the user.
    """
    chat_id = 10002
    state = ConversationState(chat_id=chat_id, state=FSMState.WAITING_FAQ)
    await ConversationTransaction.set_state(state)

    payload = {
        "message": {
            "chat": {"id": chat_id},
            "text": "¿Cómo puedo llegar a la clínica?"
        }
    }

    async def slow_get_response(*args, **kwargs):
        await asyncio.sleep(5.0)
        return "Respuesta simulada que nunca debe llegar"

    with patch('app.services.ai_service.ai_service.get_response', side_effect=slow_get_response):
        # Mock RAG search to be instant
        with patch('app.services.rag_service.rag_service.search', new_callable=AsyncMock, return_value=[]):
            with patch('app.telegram.sender.telegram_sender.send_message', new_callable=AsyncMock) as mock_send:
                with patch('app.telegram.sender.telegram_sender.flush_outbox', new_callable=AsyncMock):
                    
                    start_time = asyncio.get_event_loop().time()
                    await process_message({}, payload)
                    elapsed = asyncio.get_event_loop().time() - start_time
                    
                    # Should take approx 2.5 seconds
                    assert elapsed < 4.5, f"Timeout failed! Took {elapsed}s"
                    
                    # Verify it stayed in WAITING_FAQ but sent the timeout message
                    state = await ConversationTransaction.get_state(chat_id)
                    assert state.state == FSMState.WAITING_FAQ
                    
                    mock_send.assert_called()
                    call_args = mock_send.call_args[0]
                    assert "tardando demasiado" in call_args[1]
