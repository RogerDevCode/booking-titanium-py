import copy
import random
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from typing import List

from app.domain.enums import FSMState, Intent, BookingStatus
from app.domain.models import ConversationState
from app.domain.entities import Specialty, Provider, AppointmentSlot, BookingView
from app.fsm.main import fsm_router
from app.telegram.callback import encode

# ─────────────────────────────────────────────────────────────────────────────
# Mocks & Domain Factories
# ─────────────────────────────────────────────────────────────────────────────

def make_specialty(idx: int = 1) -> Specialty:
    return Specialty(id=f"sp-{idx}", name=f"Especialidad {idx}", description=f"Desc {idx}")

def make_provider(idx: int = 1, specialty_id: str = "sp-1") -> Provider:
    return Provider(id=f"doc-{idx}", name=f"Dr. Medico {idx}", specialty_id=specialty_id)

def make_slot(idx: int = 1, doctor_id: str = "doc-1") -> AppointmentSlot:
    base = datetime(2026, 6, 1, 9, 0) + timedelta(hours=idx)
    return AppointmentSlot(
        id=f"slot-{idx}", doctor_id=doctor_id,
        start_time=base, end_time=base + timedelta(hours=1),
        is_available=True
    )

def make_booking_view(idx: int = 1) -> BookingView:
    return BookingView(
        id=idx, status=BookingStatus.CONFIRMED,
        start_time=datetime(2026, 6, 1, 10, 0) + timedelta(hours=idx),
        provider_name=f"Dr. Medico {idx}",
        specialty_name=f"Especialidad {idx}"
    )

class MockUser:
    def __init__(self):
        self.first_name = "Fuzz User"
        self.phone = "+56912345678"
        self.email = "fuzz@example.com"

# ─────────────────────────────────────────────────────────────────────────────
# State Helper
# ─────────────────────────────────────────────────────────────────────────────

def copy_state(state: ConversationState) -> ConversationState:
    return ConversationState(
        chat_id=state.chat_id,
        state=state.state,
        active_flow=state.active_flow,
        context=copy.deepcopy(state.context),
        booking_draft=copy.deepcopy(state.booking_draft),
        message_id=state.message_id,
        version=state.version,
        updated_at=state.updated_at
    )

# ─────────────────────────────────────────────────────────────────────────────
# Test Fixture for Mocks
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_fsm_mocks():
    # Capture/suppress outbound Telegram messages
    mock_send = AsyncMock()
    
    # Mock database connection
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchrow = AsyncMock(return_value=None)
    
    # Mock services
    mock_booking_svc = AsyncMock()
    mock_booking_svc.get_all_specialties = AsyncMock(
        return_value=[make_specialty(1), make_specialty(2)]
    )
    mock_booking_svc.get_providers_by_specialty = AsyncMock(
        return_value=[make_provider(1, "sp-1"), make_provider(2, "sp-1")]
    )
    mock_booking_svc.get_available_slots = AsyncMock(
        return_value=[make_slot(1, "doc-1"), make_slot(2, "doc-1")]
    )
    mock_booking_svc.create_booking = AsyncMock(
        return_value=type("B", (), {"id": 999})()
    )
    mock_booking_svc.get_user_bookings = AsyncMock(
        return_value=[make_booking_view(1), make_booking_view(2)]
    )
    mock_booking_svc.cancel_booking = AsyncMock(return_value=True)
    mock_booking_svc.reschedule_booking = AsyncMock(
        return_value=type("B", (), {"id": 888})()
    )
    
    mock_booking_repo = AsyncMock()
    mock_booking_repo.get_provider_id_by_booking = AsyncMock(return_value="doc-1")
    
    mock_user_svc = AsyncMock()
    mock_user_svc.get_user = AsyncMock(return_value=MockUser())
    mock_user_svc.update_field = AsyncMock(return_value=True)

    with (
        patch("app.telegram.sender.telegram_sender.send_message", mock_send),
        patch("app.db.connection.db_client", mock_db),
        # Patch booking flow imports
        patch("app.fsm.booking_flow.booking_service", mock_booking_svc),
        patch("app.fsm.booking_flow.booking_repo", mock_booking_repo),
        # Patch main imports
        patch("app.fsm.main.booking_service", mock_booking_svc, create=True),
        # Patch profile flow imports
        patch("app.fsm.profile_flow.user_service", mock_user_svc),
        patch("app.fsm.main.user_service", mock_user_svc, create=True),
    ):
        yield

# ─────────────────────────────────────────────────────────────────────────────
# Recursive Permutation Tree Fuzzer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recursive_fuzz_depth_4():
    """
    Generates all possible permutation trees of core actions recursively up to depth 4,
    asserting that the state machine always transitions cleanly without crashing.
    """
    
    # Pruned set of core actions for full permutation coverage to keep run-time fast
    core_actions = [
        ("text", "1"),
        ("text", "si"),
        ("text", "no"),
        ("text", "back"),
        ("text", "cancel"),
        ("callback", "valid_select_1"),
        ("intent", Intent.BOOK_APPOINTMENT),
        ("intent", Intent.GET_INFO),
    ]

    failures = []

    async def recurse(state: ConversationState, depth: int, path: List[str]):
        if depth == 0:
            return

        for action_type, val in core_actions:
            # Skip intent action if not in IDLE since intent classification only runs in IDLE
            if action_type == "intent" and state.state != FSMState.IDLE:
                continue

            state_copy = copy_state(state)
            new_path = path + [f"{action_type}:{val}"]

            try:
                if action_type == "text":
                    await fsm_router.route(state_copy, val)
                elif action_type == "callback":
                    if val == "valid_select_1":
                        cb = encode(state_copy.version, "select", "1")
                    await fsm_router.route(state_copy, cb)
                elif action_type == "intent":
                    state_copy.context["preflight"] = {"intent": val}
                    await fsm_router.route(state_copy, "")

                # Invariants
                assert isinstance(state_copy.state, FSMState), f"Invalid state type: {type(state_copy.state)}"
                assert isinstance(state_copy.context, dict), f"Context is not dict: {type(state_copy.context)}"
                assert isinstance(state_copy.booking_draft, dict), f"Draft is not dict: {type(state_copy.booking_draft)}"

                # Recurse
                await recurse(state_copy, depth - 1, new_path)

            except Exception as e:
                failures.append({
                    "path": new_path,
                    "initial_state": state.state,
                    "final_state": state_copy.state,
                    "error": f"{type(e).__name__}: {str(e)}"
                })

    initial_state = ConversationState(chat_id=123)
    await recurse(initial_state, 4, [])

    if failures:
        msg = "\n".join([
            f"Path {f['path']} failed (state {f['initial_state']} -> {f['final_state']}): {f['error']}"
            for f in failures[:10]
        ])
        raise AssertionError(f"FSM Crashed/Invalid transitions found ({len(failures)} total):\n{msg}")

# ─────────────────────────────────────────────────────────────────────────────
# Randomized Walk Fuzzer (Broader Input Coverage)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_random_walk_fuzz():
    """
    Runs 500 randomized walks of depth 4 with a comprehensive set of inputs,
    verifying FSM integrity across all kinds of raw strings, stale callbacks, etc.
    """
    all_actions = [
        # Numbers
        ("text", "1"), ("text", "2"), ("text", "3"), ("text", "4"), ("text", "5"),
        # Navigations
        ("text", "volver"), ("text", "salir"), ("text", "menu"), ("text", "home"),
        ("text", "back"), ("text", "cancel"), ("text", "/start"),
        # Confirmations
        ("text", "si"), ("text", "sí"), ("text", "no"), ("text", "ok"),
        # Random inputs
        ("text", "random invalid text"), ("text", "doctor"), ("text", "cardio"),
        # Callbacks
        ("callback", "valid_select_1"),
        ("callback", "valid_select_2"),
        ("callback", "valid_back"),
        ("callback", "valid_cancel"),
        ("callback", "valid_page_next"),
        ("callback", "valid_page_prev"),
        ("callback", "stale_version"),
        ("callback", "malformed_callback"),
        # Intents (only when IDLE)
        ("intent", Intent.BOOK_APPOINTMENT),
        ("intent", Intent.MY_BOOKINGS),
        ("intent", Intent.CANCEL_APPOINTMENT),
        ("intent", Intent.RESCHEDULE_APPOINTMENT),
        ("intent", Intent.GET_INFO),
        ("intent", Intent.MANAGE_PROFILE),
        ("intent", Intent.GET_REPORT),
        ("intent", Intent.MANAGE_REMINDERS),
        ("intent", Intent.UNKNOWN),
    ]

    failures = []

    for run_idx in range(500):
        state = ConversationState(chat_id=123)
        path = []
        
        for step in range(4):
            # Select action
            action_type, val = random.choice(all_actions)
            
            # If we choose intent but state is not IDLE, try selecting again or default to text "1"
            attempts = 0
            while action_type == "intent" and state.state != FSMState.IDLE and attempts < 5:
                action_type, val = random.choice(all_actions)
                attempts += 1
            if action_type == "intent" and state.state != FSMState.IDLE:
                action_type, val = ("text", "1")

            path.append(f"{action_type}:{val}")

            try:
                if action_type == "text":
                    await fsm_router.route(state, val)
                elif action_type == "callback":
                    if val.startswith("valid_select_"):
                        opt = val.split("_")[-1]
                        cb = encode(state.version, "select", opt)
                    elif val == "valid_back":
                        cb = encode(state.version, "nav", "back")
                    elif val == "valid_cancel":
                        cb = encode(state.version, "nav", "cancel")
                    elif val == "valid_page_next":
                        cb = encode(state.version, "nav", "page_next")
                    elif val == "valid_page_prev":
                        cb = encode(state.version, "nav", "page_prev")
                    elif val == "stale_version":
                        cb = encode(max(0, state.version - 1), "select", "1")
                    elif val == "malformed_callback":
                        cb = "v_invalid_format"
                    else:
                        cb = val
                    await fsm_router.route(state, cb)
                elif action_type == "intent":
                    state.context["preflight"] = {"intent": val}
                    await fsm_router.route(state, "")

                # Invariants
                assert isinstance(state.state, FSMState)
                assert isinstance(state.context, dict)
                assert isinstance(state.booking_draft, dict)

            except Exception as e:
                failures.append({
                    "run": run_idx,
                    "step": step,
                    "path": list(path),
                    "error": f"{type(e).__name__}: {str(e)}"
                })
                break

    if failures:
        msg = "\n".join([
            f"Run {f['run']} failed at step {f['step']} with path {f['path']}: {f['error']}"
            for f in failures[:10]
        ])
        raise AssertionError(f"FSM Fuzz Random Walk failed ({len(failures)} total failures):\n{msg}")


@pytest.mark.asyncio
async def test_faq_volver_button_bug():
    """
    Verifies that selecting 'Volver al menú' (value '2') in the FAQ flow
    immediately transitions to IDLE without processing/sending a RAG answer.
    """
    # 1. Start in WAITING_FAQ state
    state = ConversationState(chat_id=123, state=FSMState.WAITING_FAQ)
    state.context["preflight"] = {"rag_answer": "This is a FAQ answer"}
    
    # We patch telegram_sender.send_message to count/inspect messages
    calls = []
    async def record_call(chat_id, text, reply_markup=None):
        calls.append(text)
        
    with patch("app.telegram.sender.telegram_sender.send_message", side_effect=record_call):
        await fsm_router.route(state, "2")
        
    # If the bug exists:
    # 1. It didn't intercept "2" early, so it generated the RAG response ("This is a FAQ answer")
    # 2. Then it processed "2" and sent "Volviendo al menú principal."
    # So both messages are sent!
    assert not any("This is a FAQ answer" in c for c in calls), f"RAG answer was sent even though user wanted to go back! Sent: {calls}"


@pytest.mark.asyncio
async def test_reschedule_select_new_slot_stuck_bug():
    """
    Verifies that if the user provides an invalid slot selection (non-digit)
    during the rescheduling step 'select_new_slot', the FSM re-renders the slots menu
    rather than failing silently and leaving the user stuck with no reply.
    """
    state = ConversationState(chat_id=123, state=FSMState.RESCHEDULING_BOOKING)
    state.booking_draft["old_booking_id"] = 1
    state.booking_draft["doctor_id"] = "doc-1"
    state.context["step"] = "select_new_slot"
    state.context["items"] = [{"id": "slot-1", "time": "2026-06-01T10:00:00"}]
    state.context["page"] = 0

    calls = []
    async def record_call(chat_id, text, reply_markup=None):
        calls.append(text)

    # Test with non-digit input
    with patch("app.telegram.sender.telegram_sender.send_message", side_effect=record_call):
        await fsm_router.route(state, "invalid_input")

    # We expect that the slots menu is re-rendered, so a message is sent
    assert len(calls) > 0, "No reply sent on invalid slot input, user is stuck!"


@pytest.mark.asyncio
async def test_reschedule_select_new_slot_out_of_range_bug():
    """
    Verifies that if the user provides a slot number that is out of range
    during 'select_new_slot', the FSM re-renders the slots menu.
    """
    state = ConversationState(chat_id=123, state=FSMState.RESCHEDULING_BOOKING)
    state.booking_draft["old_booking_id"] = 1
    state.booking_draft["doctor_id"] = "doc-1"
    state.context["step"] = "select_new_slot"
    state.context["items"] = [{"id": "slot-1", "time": "2026-06-01T10:00:00"}]
    state.context["page"] = 0

    calls = []
    async def record_call(chat_id, text, reply_markup=None):
        calls.append(text)

    # Test with out-of-range digit input (e.g. "99")
    with patch("app.telegram.sender.telegram_sender.send_message", side_effect=record_call):
        await fsm_router.route(state, "99")

    assert len(calls) > 0, "No reply sent on out of range slot selection, user is stuck!"


