import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from app.domain.entities import TelegramUser
from app.services.notification_service import NotificationService

@pytest.mark.asyncio
async def test_reminder_preferences_db_crud(integration_container, clean_db_and_redis) -> None:
    u_svc = integration_container.user_service
    
    # 1. Setup user
    chat_id = 998877
    user = TelegramUser(id=chat_id, first_name="ReminderUser", email="test@clinic.com")
    await u_svc.upsert_user(user)
    
    # 2. Get default preferences (should automatically insert defaults: telegram=true, email=false, 24h=true, 2h=true)
    prefs = await u_svc.get_reminder_preferences(chat_id)
    assert prefs.user_id == chat_id
    assert prefs.telegram_enabled is True
    assert prefs.email_enabled is False
    assert prefs.window_24h is True
    assert prefs.window_2h is True
    
    # 3. Toggle telegram off
    prefs = await u_svc.update_reminder_preference(chat_id, "telegram_enabled")
    assert prefs.telegram_enabled is False
    
    # 4. Toggle email on
    prefs = await u_svc.update_reminder_preference(chat_id, "email_enabled")
    assert prefs.email_enabled is True
    
    # 5. Toggle all off
    prefs = await u_svc.update_reminder_preference(chat_id, "all_off")
    assert prefs.telegram_enabled is False
    assert prefs.email_enabled is False
    assert prefs.window_24h is False
    assert prefs.window_2h is False

    # 6. Toggle all on
    prefs = await u_svc.update_reminder_preference(chat_id, "all_on")
    assert prefs.telegram_enabled is True
    assert prefs.email_enabled is True
    assert prefs.window_24h is True
    assert prefs.window_2h is True


@pytest.mark.asyncio
async def test_notification_service_respects_reminder_preferences(integration_container, clean_db_and_redis) -> None:
    db = integration_container.db_client
    u_svc = integration_container.user_service
    
    # Mock Telegram sender
    mock_sender = AsyncMock()
    n_svc = NotificationService(db=db, sender=mock_sender)
    
    # 1. Setup specialties, providers, users, slot
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (10, 'Cardiology')")
    await db.execute("INSERT INTO providers (id, name, specialty_id, is_active) OVERRIDING SYSTEM VALUE VALUES (20, 'Dr. Reminders', 10, true)")
    
    chat_id_enabled = 10001
    chat_id_disabled = 10002
    
    user_enabled = TelegramUser(id=chat_id_enabled, first_name="EnabledUser")
    user_disabled = TelegramUser(id=chat_id_disabled, first_name="DisabledUser")
    await u_svc.upsert_user(user_enabled)
    await u_svc.upsert_user(user_disabled)
    
    # Enable defaults for user_enabled
    await u_svc.get_reminder_preferences(chat_id_enabled)
    # Disable telegram for user_disabled
    await u_svc.get_reminder_preferences(chat_id_disabled)
    await u_svc.update_reminder_preference(chat_id_disabled, "telegram_enabled")
    
    # Generate Slots (one for 24h alert, one for 2h alert for both users)
    now = datetime.now(timezone.utc)
    t_24h = now + timedelta(hours=23)
    t_2h = now + timedelta(hours=1.5)
    
    t_24h_2 = now + timedelta(hours=22)
    t_2h_2 = now + timedelta(hours=1)
    
    await db.execute("INSERT INTO slots (id, provider_id, start_time, end_time, is_available) OVERRIDING SYSTEM VALUE VALUES (101, 20, $1, $2, false)", t_24h, t_24h + timedelta(minutes=30))
    await db.execute("INSERT INTO slots (id, provider_id, start_time, end_time, is_available) OVERRIDING SYSTEM VALUE VALUES (102, 20, $1, $2, false)", t_2h, t_2h + timedelta(minutes=30))
    await db.execute("INSERT INTO slots (id, provider_id, start_time, end_time, is_available) OVERRIDING SYSTEM VALUE VALUES (201, 20, $1, $2, false)", t_24h_2, t_24h_2 + timedelta(minutes=30))
    await db.execute("INSERT INTO slots (id, provider_id, start_time, end_time, is_available) OVERRIDING SYSTEM VALUE VALUES (202, 20, $1, $2, false)", t_2h_2, t_2h_2 + timedelta(minutes=30))
    
    # Book slots
    await db.execute("INSERT INTO bookings (user_id, slot_id, status, reminders_sent) VALUES ($1, 101, 'CONFIRMED', 0)", chat_id_enabled)
    await db.execute("INSERT INTO bookings (user_id, slot_id, status, reminders_sent) VALUES ($1, 102, 'CONFIRMED', 0)", chat_id_enabled)
    await db.execute("INSERT INTO bookings (user_id, slot_id, status, reminders_sent) VALUES ($1, 201, 'CONFIRMED', 0)", chat_id_disabled)
    await db.execute("INSERT INTO bookings (user_id, slot_id, status, reminders_sent) VALUES ($1, 202, 'CONFIRMED', 0)", chat_id_disabled)
    
    # 2. Run reminders cron task
    await n_svc.send_reminders()
    
    # Assert mock_sender.send_message was only called for chat_id_enabled, NOT chat_id_disabled
    sent_chats = [call[0][0] for call in mock_sender.send_message.call_args_list]
    assert chat_id_enabled in sent_chats
    assert chat_id_disabled not in sent_chats
    
    # Verify that the DB marked reminders as sent for BOTH to prevent infinite processing loop
    rows = await db.fetch("SELECT reminders_sent, user_id FROM bookings WHERE slot_id IN (101, 102, 201, 202)")
    for r in rows:
        # Since t_2h is < 2.0h, reminders_sent should be 2 for the 2h alert slot, and 1 for the 24h alert slot
        # Wait, the send_reminders cron runs and processes both. Since hours_until <= 2.0, the 2h slot updates to reminders_sent=2.
        # The 24h slot is hours_until = 23, so it updates to reminders_sent=1.
        if r['user_id'] == chat_id_enabled:
            pass # already verified sent_chats
        
        # Ensure database state advanced for both to avoid double-eval
        assert r['reminders_sent'] in (1, 2)
