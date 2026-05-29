import pytest
from unittest.mock import AsyncMock, patch
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from app.fsm.faq_flow import waiting_faq_handler

@pytest.mark.asyncio
async def test_medical_disclaimer_appended():
    """Test category 'Salud' gets strict medical disclaimer."""
    state = ConversationState(chat_id=123, state=FSMState.WAITING_FAQ)
    state.context["preflight"] = {
        "rag_answer": "El ibuprofeno puede ayudar con el dolor de cabeza.",
        "rag_categories": ["Salud"],
        "has_provider_faq": False
    }

    with patch('app.telegram.sender.telegram_sender.send_message', new_callable=AsyncMock) as mock_send:
        await waiting_faq_handler(state, "Dime algo")
        mock_send.assert_called()
        sent_text = mock_send.call_args[0][1]
        assert "No es consejo médico" in sent_text

@pytest.mark.asyncio
async def test_provider_disclaimer_appended():
    """Test provider specific FAQ gets provider disclaimer."""
    state = ConversationState(chat_id=123, state=FSMState.WAITING_FAQ)
    state.context["preflight"] = {
        "rag_answer": "El Dr. Pérez no atiende los martes.",
        "rag_categories": ["Horarios"],
        "has_provider_faq": True
    }

    with patch('app.telegram.sender.telegram_sender.send_message', new_callable=AsyncMock) as mock_send:
        await waiting_faq_handler(state, "Dime algo")
        mock_send.assert_called()
        sent_text = mock_send.call_args[0][1]
        assert "Sujeto a condiciones del médico" in sent_text
        assert "No es consejo médico" not in sent_text

@pytest.mark.asyncio
async def test_no_disclaimer_for_administrative():
    """Test administrative FAQ gets no medical disclaimer."""
    state = ConversationState(chat_id=123, state=FSMState.WAITING_FAQ)
    state.context["preflight"] = {
        "rag_answer": "Estamos ubicados en Av. Vitacura.",
        "rag_categories": ["Administrativo", "Ubicación"],
        "has_provider_faq": False
    }

    with patch('app.telegram.sender.telegram_sender.send_message', new_callable=AsyncMock) as mock_send:
        await waiting_faq_handler(state, "Dime algo")
        mock_send.assert_called()
        sent_text = mock_send.call_args[0][1]
        assert "No es consejo médico" not in sent_text
        assert "Sujeto a condiciones del médico" not in sent_text
