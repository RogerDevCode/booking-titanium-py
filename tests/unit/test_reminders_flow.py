import pytest
from unittest.mock import AsyncMock
from app.domain.enums import FSMState
from app.domain.models import ConversationState
from app.domain.entities import ReminderPreferences, TelegramUser
from app.fsm.reminder_flow import ReminderFlowHandlers

@pytest.mark.asyncio
async def test_reminders_flow_back_navigation() -> None:
    user_svc = AsyncMock()
    sender = AsyncMock()
    on_idle = AsyncMock()
    
    handlers = ReminderFlowHandlers(user_service=user_svc, sender=sender, on_idle=on_idle)
    state = ConversationState(chat_id=123, state=FSMState.CONFIGURING_REMINDERS)
    
    await handlers.reminder_handler(state, "back")
    
    assert state.state == FSMState.IDLE
    on_idle.assert_called_once_with(state, "")

@pytest.mark.asyncio
async def test_reminders_flow_show_menu() -> None:
    user_svc = AsyncMock()
    sender = AsyncMock()
    on_idle = AsyncMock()
    
    prefs = ReminderPreferences(
        user_id=123,
        telegram_enabled=True,
        email_enabled=False,
        window_24h=True,
        window_2h=True
    )
    user_svc.get_reminder_preferences.return_value = prefs
    user_svc.get_user.return_value = TelegramUser(id=123, first_name="Test")
    
    handlers = ReminderFlowHandlers(user_service=user_svc, sender=sender, on_idle=on_idle)
    state = ConversationState(chat_id=123, state=FSMState.CONFIGURING_REMINDERS)
    
    await handlers.reminder_handler(state, "show")
    
    user_svc.get_reminder_preferences.assert_called_once_with(123)
    sender.send_message.assert_called_once()
    args, kwargs = sender.send_message.call_args
    assert args[0] == 123
    assert "Configuración de Recordatorios" in args[1]
    
    kb = kwargs["reply_markup"]["inline_keyboard"]
    assert "📱 Telegram: ✅ Activado" in kb[0][0]["text"]
    assert "📧 Email: ❌ Desactivado" in kb[1][0]["text"]
    assert "⏰ Alerta 24h antes: ✅ Sí" in kb[2][0]["text"]
    assert "⏰ Alerta 2h antes: ✅ Sí" in kb[3][0]["text"]

@pytest.mark.asyncio
async def test_reminders_flow_toggle_preference() -> None:
    user_svc = AsyncMock()
    sender = AsyncMock()
    on_idle = AsyncMock()
    
    prefs = ReminderPreferences(
        user_id=123,
        telegram_enabled=False,
        email_enabled=False,
        window_24h=True,
        window_2h=True
    )
    user_svc.update_reminder_preference.return_value = prefs
    user_svc.get_user.return_value = TelegramUser(id=123, first_name="Test")
    
    handlers = ReminderFlowHandlers(user_service=user_svc, sender=sender, on_idle=on_idle)
    state = ConversationState(chat_id=123, state=FSMState.CONFIGURING_REMINDERS)
    
    await handlers.reminder_handler(state, "telegram_enabled")
    
    user_svc.update_reminder_preference.assert_called_once_with(123, "telegram_enabled")
    sender.send_message.assert_called_once()
    args, kwargs = sender.send_message.call_args
    kb = kwargs["reply_markup"]["inline_keyboard"]
    assert "📱 Telegram: ❌ Desactivado" in kb[0][0]["text"]
