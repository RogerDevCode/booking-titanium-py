import pytest
from app.domain.enums import FSMState
from app.domain.models import FSM_TRANSITIONS, ConversationState, FSMTransitionError

def test_all_fsm_states_can_reach_idle():
    """
    Verifica que absolutamente todos los estados definidos en FSMState
    puedan transicionar a FSMState.IDLE (ya sea directamente o manejando su
    propio estado). Esto garantiza que el comando global /start nunca cause un
    FSMTransitionError, previniendo soft-locks.
    """
    for state in FSMState:
        if state == FSMState.IDLE:
            continue
            
        allowed_transitions = FSM_TRANSITIONS.get(state, set())
        assert FSMState.IDLE in allowed_transitions, (
            f"El estado {state.value} no permite transicionar a IDLE. "
            f"Esto romperá el comando /start si el usuario queda atrapado."
        )

def test_fsm_router_global_start_escape_hatch():
    """
    Verifica dinámicamente que un ConversationState en cualquier estado
    pueda ejecutar transition_to(FSMState.IDLE) sin lanzar error.
    """
    for state_enum in FSMState:
        state = ConversationState(chat_id=1, state=state_enum)
        try:
            state.transition_to(FSMState.IDLE)
        except FSMTransitionError as e:
            pytest.fail(f"FSMTransitionError al escapar de {state_enum.value} a IDLE: {e}")
        
        assert state.state == FSMState.IDLE
