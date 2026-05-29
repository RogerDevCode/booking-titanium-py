import pytest
import asyncio
from unittest.mock import AsyncMock
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from app.worker.tasks import make_process_message

@pytest.mark.asyncio
async def test_intent_classifier_timeout(integration_container, clean_db_and_redis):
    chat_id = 10001
    state = ConversationState(chat_id=chat_id, state=FSMState.IDLE)
    await integration_container.conversation_tx.set_state(state)

    payload = {
        "message": {
            "chat": {"id": chat_id},
            "text": "quiero agendar una hora"
        }
    }

    async def slow_classify(*args, **kwargs):
        await asyncio.sleep(5.0)
        return "AGENDA_HORA"

    original_classify = integration_container.classifier.classify
    integration_container.classifier.classify = AsyncMock(side_effect=slow_classify)

    original_send = integration_container.telegram_sender.send_message
    mock_send = AsyncMock()
    integration_container.telegram_sender.send_message = mock_send

    original_flush = integration_container.telegram_sender.flush_outbox
    integration_container.telegram_sender.flush_outbox = AsyncMock()

    try:
        start_time = asyncio.get_event_loop().time()
        await make_process_message(integration_container)({}, payload)
        elapsed = asyncio.get_event_loop().time() - start_time
        
        assert elapsed < 4.5, f"Timeout failed! Took {elapsed}s"
        
        state_after = await integration_container.conversation_tx.get_state(chat_id)
        assert state_after.state == FSMState.IDLE
        mock_send.assert_called()
        call_args = mock_send.call_args[0]
        assert "Bienvenido al Sistema de Reservas Titanium" in call_args[1]
    finally:
        integration_container.classifier.classify = original_classify
        integration_container.telegram_sender.send_message = original_send
        integration_container.telegram_sender.flush_outbox = original_flush

@pytest.mark.asyncio
async def test_ai_service_timeout(integration_container, clean_db_and_redis):
    chat_id = 10002
    state = ConversationState(chat_id=chat_id, state=FSMState.WAITING_FAQ)
    await integration_container.conversation_tx.set_state(state)

    payload = {
        "message": {
            "chat": {"id": chat_id},
            "text": "¿Cómo puedo llegar a la clínica?"
        }
    }

    async def slow_get_response(*args, **kwargs):
        await asyncio.sleep(5.0)
        return "Respuesta simulada que nunca debe llegar"

    original_get_response = integration_container.ai_service.get_response
    integration_container.ai_service.get_response = AsyncMock(side_effect=slow_get_response)

    original_rag = integration_container.rag_service.search
    integration_container.rag_service.search = AsyncMock(return_value=[])

    original_send = integration_container.telegram_sender.send_message
    mock_send = AsyncMock()
    integration_container.telegram_sender.send_message = mock_send

    original_flush = integration_container.telegram_sender.flush_outbox
    integration_container.telegram_sender.flush_outbox = AsyncMock()

    try:
        start_time = asyncio.get_event_loop().time()
        await make_process_message(integration_container)({}, payload)
        elapsed = asyncio.get_event_loop().time() - start_time
        
        assert elapsed < 4.5, f"Timeout failed! Took {elapsed}s"
        
        state_after = await integration_container.conversation_tx.get_state(chat_id)
        assert state_after.state == FSMState.WAITING_FAQ
        mock_send.assert_called()
        call_args = mock_send.call_args[0]
        assert "tardando demasiado en responder" in call_args[1]
    finally:
        integration_container.ai_service.get_response = original_get_response
        integration_container.rag_service.search = original_rag
        integration_container.telegram_sender.send_message = original_send
        integration_container.telegram_sender.flush_outbox = original_flush
