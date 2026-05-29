from typing import get_type_hints
from app.telegram.sender import TelegramSender

def test_sender_strict_typing_red_team():
    """
    Red Team test to enforce zero implicit typing (Zero Any Policy) on infrastructure wrappers.
    Checks that core methods explicitly return None instead of implicitly doing so.
    """
    methods_to_check = [
        "send_message",
        "edit_message_reply_markup",
        "flush_outbox"
    ]
    
    sender_class = TelegramSender
    
    for method_name in methods_to_check:
        method = getattr(sender_class, method_name)
        hints = get_type_hints(method)
        
        # Verify that 'return' is explicitly annotated in the function signature
        assert 'return' in hints, f"Method '{method_name}' lacks explicit return type annotation."
        
        # Verify that it strictly returns None type
        assert hints['return'] is type(None), f"Method '{method_name}' should return None, got {hints['return']}"
