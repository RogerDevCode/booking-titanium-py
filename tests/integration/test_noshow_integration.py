import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from app.domain.entities import TelegramUser
from app.services.notification_service import NotificationService

@pytest.mark.asyncio
async def test_noshow_trigger_basic(integration_container, clean_db_and_redis) -> None:
    db = integration_container.db_client
    u_svc = integration_container.user_service
    
    mock_sender = AsyncMock()
    n_svc = NotificationService(db=db, sender=mock_sender)
    
    # 1. Setup specialty, provider with custom no-show configuration, user, slot
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'General Medicine')")
    await db.execute(
        """
        INSERT INTO providers (id, name, specialty_id, is_active, max_noshows_warning, max_noshows_block, noshow_block_days)
        OVERRIDING SYSTEM VALUE VALUES (10, 'Dr. House', 1, true, 2, 4, 15)
        """
    )
    
    chat_id = 12345
    user = TelegramUser(id=chat_id, first_name="John", last_name="Doe")
    await u_svc.upsert_user(user)
    
    # Create an expired slot (end time in the past)
    now = datetime.now(timezone.utc)
    slot_start = now - timedelta(hours=2)
    slot_end = now - timedelta(hours=1.5)
    
    await db.execute(
        """
        INSERT INTO slots (id, provider_id, start_time, end_time, is_available) 
        OVERRIDING SYSTEM VALUE VALUES (100, 10, $1, $2, false)
        """, 
        slot_start, slot_end
    )
    
    # Book the slot with status 'CONFIRMED'
    await db.execute("INSERT INTO bookings (id, user_id, slot_id, status) OVERRIDING SYSTEM VALUE VALUES (1000, $1, 100, 'CONFIRMED')", chat_id)
    
    # 2. Run the no-show trigger process
    await n_svc.process_noshow_triggers()
    
    # 3. Assertions
    # Booking status should now be 'NO_SHOW'
    booking_row = await db.fetchrow("SELECT status FROM bookings WHERE id = 1000")
    assert booking_row["status"] == "NO_SHOW"
    
    # User's noshow_count should be 1
    user_row = await db.fetchrow("SELECT noshow_count, is_blocked, blocked_until FROM users WHERE id = $1", chat_id)
    assert user_row["noshow_count"] == 1
    assert user_row["is_blocked"] is False
    assert user_row["blocked_until"] is None
    
    # Check that a notification message was sent to the user
    mock_sender.send_message.assert_called_once()
    args, _ = mock_sender.send_message.call_args
    assert args[0] == chat_id
    assert "Inasistencia Registrada" in args[1]
    assert "Dr. House" in args[1]
    assert "Inasistencias acumuladas: *1*" in args[1]


@pytest.mark.asyncio
async def test_noshow_trigger_warning(integration_container, clean_db_and_redis) -> None:
    db = integration_container.db_client
    u_svc = integration_container.user_service
    
    mock_sender = AsyncMock()
    n_svc = NotificationService(db=db, sender=mock_sender)
    
    # Setup provider with warning limit at 2
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'General Medicine')")
    await db.execute(
        """
        INSERT INTO providers (id, name, specialty_id, is_active, max_noshows_warning, max_noshows_block, noshow_block_days)
        OVERRIDING SYSTEM VALUE VALUES (10, 'Dr. House', 1, true, 2, 3, 15)
        """
    )
    
    chat_id = 12345
    user = TelegramUser(id=chat_id, first_name="John")
    await u_svc.upsert_user(user)
    
    # Set user's initial noshow_count to 1 (close to warning limit 2)
    await db.execute("UPDATE users SET noshow_count = 1 WHERE id = $1", chat_id)
    
    # Create expired slot
    now = datetime.now(timezone.utc)
    slot_start = now - timedelta(hours=2)
    slot_end = now - timedelta(hours=1.5)
    await db.execute("INSERT INTO slots (id, provider_id, start_time, end_time, is_available) OVERRIDING SYSTEM VALUE VALUES (100, 10, $1, $2, false)", slot_start, slot_end)
    await db.execute("INSERT INTO bookings (id, user_id, slot_id, status) OVERRIDING SYSTEM VALUE VALUES (1000, $1, 100, 'CONFIRMED')", chat_id)
    
    # Process
    await n_svc.process_noshow_triggers()
    
    # Assertions
    user_row = await db.fetchrow("SELECT noshow_count, is_blocked FROM users WHERE id = $1", chat_id)
    assert user_row["noshow_count"] == 2
    assert user_row["is_blocked"] is False
    
    # Check that a WARNING penalty was inserted into user_penalties
    penalty_row = await db.fetchrow("SELECT penalty_type, reason FROM user_penalties WHERE user_id = $1", chat_id)
    assert penalty_row is not None
    assert penalty_row["penalty_type"] == "WARNING"
    assert "Auto-warning" in penalty_row["reason"]
    
    # Warning message assertion
    args, _ = mock_sender.send_message.call_args
    assert "Advertencia de Bloqueo" in args[1]
    assert "Dr. House" in args[1]


@pytest.mark.asyncio
async def test_noshow_trigger_block(integration_container, clean_db_and_redis) -> None:
    db = integration_container.db_client
    u_svc = integration_container.user_service
    booking_repo = integration_container.booking_repo
    
    mock_sender = AsyncMock()
    n_svc = NotificationService(db=db, sender=mock_sender)
    
    # Setup provider with block limit at 3 and block_days at 15
    await db.execute("INSERT INTO specialties (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'General Medicine')")
    await db.execute(
        """
        INSERT INTO providers (id, name, specialty_id, is_active, max_noshows_warning, max_noshows_block, noshow_block_days)
        OVERRIDING SYSTEM VALUE VALUES (10, 'Dr. House', 1, true, 2, 3, 15)
        """
    )
    
    chat_id = 12345
    user = TelegramUser(id=chat_id, first_name="John")
    await u_svc.upsert_user(user)
    
    # Set user's initial noshow_count to 2 (reaching 3 will block them)
    await db.execute("UPDATE users SET noshow_count = 2 WHERE id = $1", chat_id)
    
    # Create expired slot
    now = datetime.now(timezone.utc)
    slot_start = now - timedelta(hours=2)
    slot_end = now - timedelta(hours=1.5)
    await db.execute("INSERT INTO slots (id, provider_id, start_time, end_time, is_available) OVERRIDING SYSTEM VALUE VALUES (100, 10, $1, $2, false)", slot_start, slot_end)
    await db.execute("INSERT INTO bookings (id, user_id, slot_id, status) OVERRIDING SYSTEM VALUE VALUES (1000, $1, 100, 'CONFIRMED')", chat_id)
    
    # Process
    await n_svc.process_noshow_triggers()
    
    # Assertions
    user_row = await db.fetchrow("SELECT noshow_count, is_blocked, blocked_until FROM users WHERE id = $1", chat_id)
    assert user_row["noshow_count"] == 3
    assert user_row["is_blocked"] is True
    assert user_row["blocked_until"] is not None
    # Verify blocked_until is about 15 days in the future
    diff = user_row["blocked_until"] - datetime.now(timezone.utc)
    assert 13 < diff.days <= 15
    
    # Check that a TEMP_BAN penalty was inserted into user_penalties
    penalty_row = await db.fetchrow("SELECT penalty_type, reason, active_until FROM user_penalties WHERE user_id = $1 ORDER BY id DESC LIMIT 1", chat_id)
    assert penalty_row is not None
    assert penalty_row["penalty_type"] == "TEMP_BAN"
    assert "Auto-ban" in penalty_row["reason"]
    assert penalty_row["active_until"] is not None
    
    # Block notification message assertion
    args, _ = mock_sender.send_message.call_args
    assert "Cuenta Bloqueada" in args[1]
    
    # 4. Attempt to create a new booking or reschedule (should raise ValueError)
    # Create a new available slot
    new_start = now + timedelta(days=2)
    new_end = new_start + timedelta(minutes=30)
    await db.execute("INSERT INTO slots (id, provider_id, start_time, end_time, is_available) OVERRIDING SYSTEM VALUE VALUES (101, 10, $1, $2, true)", new_start, new_end)
    
    with pytest.raises(ValueError, match="User is blocked"):
        await booking_repo.create_booking_tx(chat_id, "101")
        
    with pytest.raises(ValueError, match="User is blocked"):
        await booking_repo.reschedule_booking_tx(chat_id, 1000, "101")
