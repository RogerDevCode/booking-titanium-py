from app.domain.enums import FSMState
from app.fsm.main import FSMRouter

def test_static_graph_no_orphan_states():
    """
    Verifica que todos los estados definidos en FSMState tengan 
    un handler asignado en el FSMRouter (sin estados huérfanos).
    """
    router = FSMRouter()
    mapped_states = set(router._handlers.keys())
    
    # Algunos estados podrían no estar implementados aún,
    # pero el diseño ideal es que todos estén mapeados o explícitamente ignorados.
    missing_handlers = set(FSMState) - mapped_states
    
    # Validamos que no falten handlers para los estados core
    assert not missing_handlers, f"Estados sin handler asignado: {missing_handlers}"

def test_static_graph_no_invalid_states():
    """
    Verifica que el router no tenga estados fantasma (handlers asignados a None o strings).
    """
    router = FSMRouter()
    mapped_states = set(router._handlers.keys())
    
    invalid_states = [s for s in mapped_states if not isinstance(s, FSMState)]
    
    assert not invalid_states, f"Estados inválidos en el router: {invalid_states}"
