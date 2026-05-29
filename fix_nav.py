import re

paths = [
    'app/fsm/booking_flow.py',
    'app/fsm/profile_flow.py',
    'app/fsm/faq_flow.py'
]

for p in paths:
    with open(p, 'r') as f:
        content = f.read()
    
    # Update paginated
    content = re.sub(
        r'total_pages=total_pages\s*\)',
        'total_pages=total_pages, include_nav=True)',
        content
    )
    
    # Update inline (for booking_flow options, etc)
    content = re.sub(
        r'build_inline_keyboard\(options\)',
        'build_inline_keyboard(options, include_nav=True)',
        content
    )
    
    # For hardcoded options
    content = content.replace(
        'kb = telegram_sender.build_inline_keyboard(["SÍ, confirmar", "NO, cancelar"])',
        'kb = telegram_sender.build_inline_keyboard(["SÍ, confirmar", "NO, cancelar"], include_nav=True)'
    )
    
    content = content.replace(
        'kb = telegram_sender.build_inline_keyboard(["Cancelar Cita", "Reagendar Cita", "Volver al Menú"])',
        'kb = telegram_sender.build_inline_keyboard(["Cancelar Cita", "Reagendar Cita"], include_nav=True)'
    )

    content = content.replace(
        '["Nombre", "Teléfono", "Email", "Volver"]',
        '["Nombre", "Teléfono", "Email"]'
    )
    
    content = content.replace(
        'build_inline_keyboard(\n                ["Nombre", "Teléfono", "Email"]\n            )',
        'build_inline_keyboard(["Nombre", "Teléfono", "Email"], include_nav=True)'
    )
    
    # In faq_flow, we want nav too.
    content = content.replace(
        'build_inline_keyboard(\n        ["Ver más FAQs", "Volver al Menú"]\n    )',
        'build_inline_keyboard(["Ver más FAQs"], include_nav=True)'
    )

    with open(p, 'w') as f:
        f.write(content)

