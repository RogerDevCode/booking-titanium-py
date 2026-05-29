import pytest
from app.domain.models import ConversationState
from app.domain.enums import FSMState
from app.fsm.booking_flow import selecting_doctor_handler
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_pagination_red_team_boundaries():
    """
    Red Team Test for Pagination:
    Simulates a scenario with 25 doctors to verify that pagination works
    correctly and doesn't corrupt state.
    """
    chat_id = 11223344
    state = ConversationState(chat_id=chat_id, state=FSMState.SELECTING_DOCTOR)
    state.booking_draft["specialty_name"] = "Cardiología"
    
    # 25 mock doctors
    mock_doctors = [{"id": f"doc_{i}", "name": f"Doctor {i}"} for i in range(25)]
    state.context["items"] = mock_doctors
    state.context["page"] = 0
    
    with patch("app.telegram.sender.TelegramSender.send_message", new_callable=AsyncMock) as mock_send:
        # Simulate pressing "page_next" from page 0
        await selecting_doctor_handler(state, "page_next")
        
        # State should be updated
        assert state.context["page"] == 1
        
        # Verify it built page 1 correctly (indices 5 to 9)
        mock_send.assert_called()
        reply_markup = mock_send.call_args[1].get("reply_markup")
        assert reply_markup is not None
        
        # Check inline keyboard
        keyboard = reply_markup["inline_keyboard"]
        # Page 1 should have 5 items + 1 nav (prev/next) + 1 nav (home/back/cancel) = 7 rows
        assert len(keyboard) == 7
        
        # Verify it built page 1 correctly (indices 5 to 9) -> button 1 should be 6️⃣ Doctor 5
        assert "6️⃣ Doctor 5" in keyboard[0][0]["text"]
        
        # Check nav row (which is now second to last, last is the universal nav row)
        nav_row = keyboard[-2]
        assert len(nav_row) == 2 # both Prev and Next buttons should be there
        assert nav_row[0]["callback_data"] == "v0:nav:page_prev"
        assert nav_row[1]["callback_data"] == "v0:nav:page_next"
        
        # Simulate selecting relative index "7" (which is Doctor 6)
        mock_send.reset_mock()
        with patch("app.services.booking_service.BookingService.get_available_slots", new_callable=AsyncMock) as mock_slots:
            from datetime import datetime
            class MockSlot:
                id = "slot_1"
                start_time = datetime(2026, 5, 28, 10, 0, 0)
            mock_slots.return_value = [MockSlot()]
            await selecting_doctor_handler(state, "7")
            
            assert state.booking_draft["doctor_id"] == "doc_6"
            assert state.booking_draft["doctor_name"] == "Doctor 6"
            assert state.state == FSMState.SELECTING_TIME
