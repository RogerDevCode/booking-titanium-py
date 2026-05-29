import pytest
from app.domain.models import ConversationState
from app.db.connection import db_client
from app.services.booking_service import booking_service
from app.fsm.booking_flow import _render_time_menu, CHILE_TZ

@pytest.fixture
async def db():
    from app.core.config import settings
    settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"
    await db_client.connect()
    yield
    await db_client.disconnect()

@pytest.mark.asyncio
async def test_availability_engine(db):
    doctor_id = "956d0274-09c8-468a-a948-98d2b88fbd7f" # Dr. Juan Perez
    slots = await booking_service.get_available_slots(doctor_id, limit=50)
    
    assert len(slots) > 0, "Debe haber slots disponibles para Juan Perez"
    
    # Check that the dates are correctly parsed and are inside 08:00 - 16:00 in Chile Time
    for slot in slots:
        local_time = slot.start_time.astimezone(CHILE_TZ)
        assert 8 <= local_time.hour < 16, f"Hora {local_time.hour} fuera de rango laboral"
        assert local_time.weekday() < 5, f"Día {local_time.weekday()} no es día hábil"

@pytest.mark.asyncio
async def test_timezone_formatting_in_menu(db, monkeypatch):
    doctor_id = "956d0274-09c8-468a-a948-98d2b88fbd7f"
    slots = await booking_service.get_available_slots(doctor_id, limit=5)
    
    state = ConversationState(chat_id=999)
    state.booking_draft["doctor_name"] = "Dr. Juan Perez"
    state.context["items"] = [{"id": s.id, "time": s.start_time.isoformat()} for s in slots]
    
    # We will mock telegram_sender.build_paginated_keyboard to capture the generated options
    captured_options = []
    
    from app.telegram.sender import telegram_sender
    
    def mock_build_paginated_keyboard(options, version, start_idx=0, page=0, total_pages=1, include_nav=False):
        captured_options.extend(options)
        return {"type": "inline_keyboard"}
        
    monkeypatch.setattr(telegram_sender, "build_paginated_keyboard", mock_build_paginated_keyboard)
    
    # Call _render_time_menu directly to bypass the handler and check the keyboard output
    await _render_time_menu(state)
    
    assert len(captured_options) == min(5, len(slots))
    
    for i, option_text in enumerate(captured_options):
        # We expect option text to match local time, so if DB is UTC, the text should be UTC-4
        local_time = slots[i].start_time.astimezone(CHILE_TZ)
        from app.fsm.booking_flow import format_chile_time
        expected_time_str = format_chile_time(local_time)
        assert option_text == expected_time_str, f"La opción del menú no respeta el TZ local. Esperado: {expected_time_str}, Obtenido: {option_text}"
