import pytest
from unittest.mock import patch, AsyncMock
from app.worker.tasks import process_message
from app.db.connection import db_client

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
async def test_worker_resilience_catches_unhandled_exceptions(setup_db):
    """
    Red Team Test: Simulates a catastrophic failure inside the FSM router
    to ensure the worker doesn't silently die, but instead queues an error message
    for the user in the outbox.
    """
    chat_id = 999111222
    payload = {
        "message": {
            "chat": {"id": chat_id},
            "text": "Hola"
        }
    }
    
    # Mock the FSM router to raise an unexpected runtime exception
    with patch("app.worker.tasks.fsm_router.route", new_callable=AsyncMock) as mock_route:
        mock_route.side_effect = RuntimeError("Simulated Database or System Crash")
        
        # We also mock flush_outbox so it doesn't actually try to send to Telegram HTTP API
        with patch("app.telegram.sender.TelegramSender.flush_outbox", new_callable=AsyncMock):
            
            # This should NOT raise an exception, it should be caught and handled
            await process_message({}, payload)
            
    # Check if the outbox has the fallback error message
    query = "SELECT text FROM outbox_messages WHERE chat_id = $1"
    messages = await db_client.fetch(query, chat_id)
    
    assert len(messages) > 0, "No fallback message was queued after crash"
    assert "problema interno" in messages[-1]["text"], "The message is not the expected internal error alert"
