import pytest
from app.domain.models import ConversationState
from app.domain.enums import FSMState

@pytest.mark.asyncio
async def test_outbox_split_brain_prevention(integration_container, clean_db_and_redis):
    """
    Simulates a failure during state transition processing to ensure that:
    1. The DB transaction rolls back.
    2. No messages are left in the Outbox (preventing split-brain where user gets message but state isn't saved).
    """
    chat_id = 88888
    await integration_container.db_client.execute("DELETE FROM conversation_states WHERE chat_id = $1", chat_id)
    
    # Pre-condition: User is IDLE
    initial_state = ConversationState(chat_id=chat_id, state=FSMState.IDLE)
    await integration_container.conversation_tx.set_state(initial_state)

    # Let's mock integration_container.fsm_router.route to raise an Exception AFTER queueing a message
    original_route = integration_container.fsm_router.route
    
    async def failing_route(state, text):
        # 1. Queue a message (happens inside the FSM)
        await integration_container.telegram_sender.send_message(state.chat_id, "Este mensaje NUNCA debe llegar al usuario.")
        
        # 2. Crash before state is saved!
        raise RuntimeError("Catastrophic failure in FSM logic!")

    integration_container.fsm_router.route = failing_route

    # Run the transaction block as the worker would
    try:
        async with integration_container.db_client.transaction():
            state = await integration_container.conversation_tx.get_state(chat_id)
            await integration_container.fsm_router.route(state, "1")
            await integration_container.conversation_tx.set_state(state)
    except RuntimeError:
        pass  # Expected
    finally:
        # Restore router
        integration_container.fsm_router.route = original_route

    # Validation:
    # Because it crashed inside the transaction block, the outbox insert MUST have rolled back.
    outbox_count = await integration_container.db_client.fetchrow("SELECT count(*) FROM outbox_messages WHERE chat_id = $1", chat_id)
    assert outbox_count["count"] == 0, "Split Brain detected! Message was saved to outbox despite transaction failure."
    
    # And state must still be IDLE (version 1 since we initialized it)
    final_state = await integration_container.conversation_tx.get_state(chat_id)
    assert final_state.state == FSMState.IDLE
