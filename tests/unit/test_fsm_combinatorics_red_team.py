import asyncio
from unittest.mock import AsyncMock, patch
from hypothesis import settings, HealthCheck, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, initialize, invariant

from app.domain.enums import FSMState, Intent
from app.domain.models import ConversationState
from app.fsm.main import fsm_router

# Dummy data
MOCK_SPECIALTIES = [{"id": 1, "name": "Cardiología"}, {"id": 2, "name": "Odontología"}]
MOCK_DOCTORS = [{"id": "doc1", "name": "Dr. Perez"}, {"id": "doc2", "name": "Dr. Gomez"}]
MOCK_SLOTS = [{"id": "s1", "start_time": "2030-01-01T10:00:00Z"}]
MOCK_BOOKINGS = [{"id": "b1", "specialty": "Cardio", "appointment_time": "2030-01-01T10:00"}]

class FSMMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        # Isolated state per run
        self.state = ConversationState(chat_id=123)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def teardown(self):  # noqa: F811
        self.loop.close()

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)

    @initialize()
    def setup_mocks(self):
        self.state = ConversationState(chat_id=123)
        # We patch all services to avoid DB calls during the fuzzing
        self.patcher_sender = patch("app.telegram.sender.telegram_sender.send_message", new=AsyncMock())
        self.patcher_sender.start()
        
        # Mock db_client
        self.patcher_db = patch("app.db.connection.db_client", create=True)
        self.mock_db = self.patcher_db.start()
        self.mock_db.execute = AsyncMock()
        self.mock_db.fetch = AsyncMock(return_value=[])
        self.mock_db.fetchrow = AsyncMock(return_value=None)
        
        # We patch the service where it is imported in the handlers
        self.patcher_booking = patch("app.fsm.booking_flow.booking_service")
        self.mock_booking = self.patcher_booking.start()
        self.mock_booking.get_all_specialties = AsyncMock(return_value=[type("S", (), {"id": "1", "name": s["name"]})() for s in MOCK_SPECIALTIES])
        self.mock_booking.get_providers_by_specialty = AsyncMock(return_value=[type("D", (), {"id": d["id"], "name": d["name"]})() for d in MOCK_DOCTORS])
        from datetime import datetime
        self.mock_booking.get_available_slots = AsyncMock(return_value=[type("SL", (), {"id": s["id"], "start_time": datetime.fromisoformat(s["start_time"])})() for s in MOCK_SLOTS])
        self.mock_booking.create_booking = AsyncMock(return_value=True)
        self.mock_booking.get_user_bookings = AsyncMock(return_value=[type("B", (), {"id": b["id"], "specialty_name": b["specialty"], "appointment_time": b["appointment_time"], "start_time": datetime.fromisoformat(b["appointment_time"]), "doctor_name": "Dr.", "provider_name": "Dr."})() for b in MOCK_BOOKINGS])
        self.mock_booking.cancel_booking = AsyncMock(return_value=True)
        self.mock_booking.reschedule_booking = AsyncMock(return_value=True)

        self.patcher_repo = patch("app.fsm.booking_flow.booking_repo", create=True)
        self.mock_repo = self.patcher_repo.start()
        self.mock_repo.get_specialties = AsyncMock(return_value=[])
        self.mock_repo.get_provider_id_by_booking = AsyncMock(return_value="doc1")

        self.patcher_booking2 = patch("app.fsm.main.booking_service", self.mock_booking, create=True)
        self.patcher_booking2.start()

        # User Service
        self.patcher_user = patch("app.fsm.profile_flow.user_service", create=True)
        self.mock_user = self.patcher_user.start()
        self.mock_user.get_user = AsyncMock(return_value=type("U", (), {"id": 1, "first_name": "Test", "phone": None, "email": None, "address": None})())
        self.mock_user.update_field = AsyncMock(return_value=True)

        self.patcher_user2 = patch("app.fsm.main.user_service", self.mock_user, create=True)
        self.patcher_user2.start()

    def teardown(self):  # noqa: F811
        self.patcher_sender.stop()
        self.patcher_db.stop()
        self.patcher_booking.stop()
        self.patcher_repo.stop()
        self.patcher_booking2.stop()
        self.patcher_user.stop()
        self.patcher_user2.stop()
        super().teardown()

    @rule(text=st.sampled_from(["1", "2", "3", "4", "home", "back", "cancel", "page_next", "page_prev", "/start", "invalid_random_text"]))
    def dispatch_event(self, text):
        """Simulates sending a valid or invalid text/callback to the FSM router."""
        self.run_async(fsm_router.route(self.state, text))

    @rule(intent=st.sampled_from([Intent.BOOK_APPOINTMENT, Intent.MY_BOOKINGS, Intent.CANCEL_APPOINTMENT, Intent.RESCHEDULE_APPOINTMENT, Intent.MANAGE_PROFILE]))
    def dispatch_intent_idle(self, intent):
        """Simulates the NLU intent classification hitting the router when in IDLE."""
        if self.state.state == FSMState.IDLE:
            self.state.context["preflight"] = {"intent": intent}
            self.run_async(fsm_router.route(self.state, ""))

    @invariant()
    def check_state_validity(self):
        """State must never be corrupted to None or invalid type."""
        assert isinstance(self.state.state, FSMState)

    @invariant()
    def check_context_type(self):
        """Context and drafts must always be dictionaries."""
        assert isinstance(self.state.context, dict)
        assert isinstance(self.state.booking_draft, dict)


TestFSM = FSMMachine.TestCase
TestFSM.settings = settings(
    max_examples=200, 
    deadline=None, 
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture]
)
