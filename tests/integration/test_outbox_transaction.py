import pytest
from app.db.connection import db_client
from app.domain.models import ConversationState
from app.domain.enums import FSMState
from app.db.conversation_tx import ConversationTransaction
from app.telegram.sender import telegram_sender
from app.fsm.main import fsm_router
from app.core.config import settings

@pytest.fixture
async def setup_env():
    settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"
    settings.REDIS_URL = "redis://localhost:6379"
    await db_client.connect()
    
    # We clean up outbox and states for test
    await db_client.execute("DELETE FROM outbox_messages")
    yield
    await db_client.execute("DELETE FROM outbox_messages")
    await db_client.disconnect()

@pytest.mark.asyncio
async def test_outbox_split_brain_prevention(setup_env):
    """
    Simulates a failure during state transition processing to ensure that:
    1. The DB transaction rolls back.
    2. No messages are left in the Outbox (preventing split-brain where user gets message but state isn't saved).
    """
    chat_id = 88888
    await db_client.execute("DELETE FROM conversation_states WHERE chat_id = $1", chat_id)
    
    # Pre-condition: User is IDLE
    initial_state = ConversationState(chat_id=chat_id, state=FSMState.IDLE)
    await ConversationTransaction.set_state(initial_state)

    # Let's mock fsm_router.route to raise an Exception AFTER queueing a message
    original_route = fsm_router.route
    
    async def failing_route(state, text):
        # 1. Queue a message (happens inside the FSM)
        await telegram_sender.send_message(state.chat_id, "Este mensaje NUNCA debe llegar al usuario.")
        
        # 2. Crash before state is saved!
        raise RuntimeError("Catastrophic failure in FSM logic!")

    fsm_router.route = failing_route

    # Run the transaction block as the worker would
    try:
        async with db_client.transaction():
            state = await ConversationTransaction.get_state(chat_id)
            await fsm_router.route(state, "1")
            await ConversationTransaction.set_state(state)
    except RuntimeError:
        pass  # Expected
    finally:
        # Restore router
        fsm_router.route = original_route

    # Validation:
    # Because it crashed inside the transaction block, the outbox insert MUST have rolled back.
    outbox_count = await db_client.fetchrow("SELECT count(*) FROM outbox_messages WHERE chat_id = $1", chat_id)
    assert outbox_count["count"] == 0, "Split Brain detected! Message was saved to outbox despite transaction failure."
    
    # And state must still be IDLE (version 1 since we initialized it)
    final_state = await ConversationTransaction.get_state(chat_id)
    assert final_state.state == FSMState.IDLE
