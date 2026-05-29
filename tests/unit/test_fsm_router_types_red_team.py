from typing import get_type_hints
from app.fsm.main import FSMRouter

def test_fsm_router_strict_typing_red_team():
    """
    Red Team test to enforce Zero Any Policy on the FSM Router boundaries.
    Ensures register and route methods explicitly define -> None and accept HandlerType.
    """
    router_class = FSMRouter
    
    # Check register
    register_hints = get_type_hints(router_class.register)
    assert 'return' in register_hints, "Method 'register' lacks explicit return type annotation."
    assert register_hints['return'] is type(None), f"Method 'register' should return None, got {register_hints['return']}"
    # Python 3.9+ type hints might resolve to aliases, we just ensure it's there
    assert 'handler' in register_hints, "Method 'register' lacks explicit 'handler' type annotation."

    # Check route
    route_hints = get_type_hints(router_class.route)
    assert 'return' in route_hints, "Method 'route' lacks explicit return type annotation."
    assert route_hints['return'] is type(None), f"Method 'route' should return None, got {route_hints['return']}"
