
with open('tests/unit/test_menus_completo.py', 'r') as f:
    content = f.read()

# Make sure patch is NOT imported from unittest.mock
content = content.replace('from unittest.mock import AsyncMock, patch, MagicMock', 'from unittest.mock import AsyncMock, MagicMock')

custom_patch = '''
import contextlib

@contextlib.contextmanager
def patch(target, new=None, **kwargs):
    if new is None:
        new = AsyncMock()
        
    old_val = None
    target_obj = None
    attr_name = ""
    
    if "telegram_sender.send_message" in target:
        target_obj = telegram_sender
        attr_name = "send_message"
    elif "get_all_specialties" in target:
        target_obj = booking_service
        attr_name = "get_all_specialties"
    elif "get_providers_by_specialty" in target:
        target_obj = booking_service
        attr_name = "get_providers_by_specialty"
    elif "get_available_slots" in target:
        target_obj = booking_service
        attr_name = "get_available_slots"
    elif "create_booking" in target:
        target_obj = booking_service
        attr_name = "create_booking"
    elif "get_user_bookings" in target:
        target_obj = booking_service
        attr_name = "get_user_bookings"
    elif "cancel_booking" in target:
        target_obj = booking_service
        attr_name = "cancel_booking"
    elif "reschedule_booking" in target:
        target_obj = booking_service
        attr_name = "reschedule_booking"
    elif "get_user" in target:
        target_obj = user_service
        attr_name = "get_user"
    elif "get_provider_id_by_booking" in target:
        target_obj = booking_repo
        attr_name = "get_provider_id_by_booking"
    elif "fake_db.execute" in target:
        target_obj = fake_db
        attr_name = "execute"
    
    if target_obj:
        old_val = getattr(target_obj, attr_name)
        setattr(target_obj, attr_name, new)
        
    try:
        yield new
    finally:
        if target_obj:
            setattr(target_obj, attr_name, old_val)

'''

# Insert the custom patch after fake_db = AsyncMock()
content = content.replace('fake_db = AsyncMock()', 'fake_db = AsyncMock()\\n' + custom_patch)

with open('tests/unit/test_menus_completo.py', 'w') as f:
    f.write(content)
