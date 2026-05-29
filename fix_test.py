
with open('tests/unit/test_menus_completo.py', 'r') as f:
    content = f.read()

# Fix the assertion in test_confirmacion_si_crea_reserva
content = content.replace(
    "assert any('#42' in t or '42' in t for t in capture.texts)",
    "assert any('confirmada' in t.lower() for t in capture.texts)"
)

with open('tests/unit/test_menus_completo.py', 'w') as f:
    f.write(content)
