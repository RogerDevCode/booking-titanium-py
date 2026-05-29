import pytest
from unittest.mock import AsyncMock
from app.worker.tasks import make_process_message

@pytest.mark.asyncio
async def test_worker_resilience_catches_unhandled_exceptions(integration_container, clean_db_and_redis):
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
    original_process_message = integration_container.fsm_router.route
    integration_container.fsm_router.route = AsyncMock(side_effect=RuntimeError("Simulated Database or System Crash"))
    
    # We also mock flush_outbox so it doesn't actually try to send to Telegram HTTP API
    original_flush = integration_container.telegram_sender.flush_outbox
    integration_container.telegram_sender.flush_outbox = AsyncMock()
    
    try:
        # This should NOT raise an exception, it should be caught and handled
        await make_process_message(integration_container)({}, payload)
    finally:
        integration_container.fsm_router.route = original_process_message
        integration_container.telegram_sender.flush_outbox = original_flush
            
    # Check if the outbox has the fallback error message
    query = "SELECT text FROM outbox_messages WHERE chat_id = $1"
    messages = await integration_container.db_client.fetch(query, chat_id)
    
    assert len(messages) > 0, "No fallback message was queued after crash"
    assert "problema interno" in messages[-1]["text"], "The message is not the expected internal error alert"
