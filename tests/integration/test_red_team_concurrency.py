import pytest
import asyncio
from unittest.mock import AsyncMock
from app.domain.models import ConversationState
from app.domain.enums import FSMState
from app.worker.tasks import make_process_message

@pytest.mark.asyncio
async def test_race_condition_fsm(integration_container, clean_db_and_redis):
    chat_id = 99999
    
    await integration_container.db_client.execute("DELETE FROM conversation_states WHERE chat_id = $1", chat_id)
    initial_state = ConversationState(chat_id=chat_id, state=FSMState.IDLE)
    await integration_container.conversation_tx.set_state(initial_state)

    payload = {
        "message": {
            "chat": {"id": chat_id},
            "text": "quiero agendar una hora"
        }
    }

    # Mock flush_outbox
    original_flush = integration_container.telegram_sender.flush_outbox
    mock_flush = AsyncMock()
    integration_container.telegram_sender.flush_outbox = mock_flush

    try:
        tasks = []
        for _ in range(10):
            tasks.append(make_process_message(integration_container)({}, payload))

        # We must gather them.
        await asyncio.gather(*tasks, return_exceptions=True)

        final_state = await integration_container.conversation_tx.get_state(chat_id)
        
        # Ensure version changed, showing at least one successful transaction
        assert final_state.version >= 1
    except Exception as e:
        pytest.fail(f"Test failed with exception {e}")
    finally:
        integration_container.telegram_sender.flush_outbox = original_flush
