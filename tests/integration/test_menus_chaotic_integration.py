import json
from typing import Any
import pytest
from unittest.mock import AsyncMock

from app.worker.tasks import make_process_message

@pytest.fixture
async def setup_chaotic_test(integration_container, clean_db_and_redis):
    spec_id = "11111111-1111-1111-1111-111111111111"
    doc_id = "22222222-2222-2222-2222-222222222222"
    
    # Mock Telegram API calls
    mock_post = AsyncMock()
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 999}}
    mock_post.return_value.raise_for_status = AsyncMock()
    integration_container.telegram_sender._client = type("MockClient", (), {"post": mock_post})()
    
    await integration_container.db_client.execute(f"INSERT INTO specialties (id, name) VALUES ('{spec_id}', 'Especialidad_Test') ON CONFLICT DO NOTHING")
    await integration_container.db_client.execute(
        f"INSERT INTO providers (id, name, specialty_id, is_active) VALUES ('{doc_id}', 'Dr. Test', '{spec_id}', true) ON CONFLICT DO NOTHING"
    )
    await integration_container.db_client.execute(
        f"INSERT INTO slots (provider_id, start_time, end_time, is_available) VALUES ('{doc_id}', '2030-01-01 10:00:00+00', '2030-01-01 10:30:00+00', true)"
    )

    process_message = make_process_message(integration_container)
    chat_id = 77777

    async def interact(text: str, is_callback: bool = False):
        await integration_container.db_client.execute("DELETE FROM outbox_messages WHERE chat_id = $1", chat_id)
        
        payload: dict[str, Any] = {"message": {"chat": {"id": chat_id, "first_name": "TestUserCaotico"}}}
        if is_callback:
            payload["callback_query"] = {
                "id": "test_query_id",
                "message": {"chat": {"id": chat_id}},
                "data": text
            }
        else:
            payload["message"]["text"] = text # type: ignore

        await process_message({}, payload)
        
        row = await integration_container.db_client.fetchrow(
            "SELECT text, reply_markup FROM outbox_messages WHERE chat_id = $1 ORDER BY created_at DESC LIMIT 1", 
            chat_id
        )
        assert row is not None, f"No response was sent to the user for input: {text}"
        
        markup_str = row["reply_markup"]
        keyboard = json.loads(markup_str)["inline_keyboard"] if markup_str else []
        return row["text"], keyboard

    def find_btn(keyboard, text_match):
        for row in keyboard:
            for btn in row:
                if text_match.lower() in btn.get("text", "").lower() or text_match.lower() in btn.get("callback_data", "").lower():
                    return btn
        return None

    return interact, find_btn


@pytest.mark.asyncio
async def test_backward_navigation_clears_state(setup_chaotic_test):
    interact, find_btn = setup_chaotic_test

    # 1. Start
    text, kb = await interact("/start")
    
    # 2. Agendar
    btn_agendar = find_btn(kb, "Agendar hora")
    text, kb = await interact(btn_agendar["callback_data"], is_callback=True)
    assert "especialidad" in text.lower()
    
    # 3. Select Specialty -> Goes to Doctor Selection
    btn_spec = find_btn(kb, "Especialidad_Test")
    text, kb = await interact(btn_spec["callback_data"], is_callback=True)
    assert "médico" in text.lower()
    
    # 4. ATRÁS (Back to Specialty)
    btn_back = find_btn(kb, "nav:back")
    assert btn_back is not None, "Botón Atrás no encontrado en selección de médico"
    text, kb = await interact(btn_back["callback_data"], is_callback=True)
    assert "especialidad" in text.lower(), "Al volver atrás no se regresó a especialidad"
    
    # 5. Select Specialty again
    btn_spec2 = find_btn(kb, "Especialidad_Test")
    text, kb = await interact(btn_spec2["callback_data"], is_callback=True)
    assert "médico" in text.lower()
    
    # 6. Select Doctor -> Goes to Time Selection
    btn_doc = find_btn(kb, "Dr. Test")
    text, kb = await interact(btn_doc["callback_data"], is_callback=True)
    assert "horario" in text.lower()
    
    # 7. ATRÁS (Back to Doctor Selection)
    btn_back2 = find_btn(kb, "nav:back")
    assert btn_back2 is not None, "Botón Atrás no encontrado en selección de hora"
    text, kb = await interact(btn_back2["callback_data"], is_callback=True)
    assert "médico" in text.lower(), "Al volver atrás no se regresó a la selección de médico"


@pytest.mark.asyncio
async def test_stale_callback_version_mismatch(setup_chaotic_test):
    interact, find_btn = setup_chaotic_test

    # 1. Start
    text, kb_start = await interact("/start")
    btn_agendar_1 = find_btn(kb_start, "Agendar hora")
    
    # 2. User goes forward
    text, kb_spec = await interact(btn_agendar_1["callback_data"], is_callback=True)
    assert "especialidad" in text.lower()
    
    # 3. The user maliciously or accidentally clicks the old 'Agendar hora' button from step 1
    # This should be rejected because state version has progressed.
    text, kb = await interact(btn_agendar_1["callback_data"], is_callback=True)
    # The expected behavior should be a soft error message or a reprompt, but it shouldn't crash.
    # It might also just ignore it. If the router strictly checks version, it should emit an error text.
    # Usually it says "Menú expirado" or similar.
    assert "expirado" in text.lower() or "inválido" in text.lower() or "desactualizado" in text.lower()


@pytest.mark.asyncio
async def test_abrupt_interruption_resets_flow(setup_chaotic_test):
    interact, find_btn = setup_chaotic_test

    # 1. Start
    text, kb = await interact("/start")
    btn_agendar = find_btn(kb, "Agendar hora")
    
    # 2. Iniciar flujo
    text, kb = await interact(btn_agendar["callback_data"], is_callback=True)
    assert "especialidad" in text.lower()
    
    # 3. Interrupción abrupta (El usuario escribe texto en lugar de tocar el menú)
    text, kb = await interact("quiero cancelar")
    
    # Dependiendo de la implementación, puede mandarlo a cancelar, o reprompt.
    # Pero no debe fallar con 500. Asumamos que el NLU lo entiende o el router dice "comando no reconocido"
    assert "cancelada" in text.lower() or "cancelar" in text.lower() or "no entiendo" in text.lower() or "menú" in text.lower()

    # 4. Otro reinicio abrupto
    text, kb = await interact("/start")
    assert "bienvenido" in text.lower()


@pytest.mark.asyncio
async def test_slash_command_in_menu(setup_chaotic_test):
    interact, find_btn = setup_chaotic_test

    # 1. Start
    text, kb = await interact("/start")
    btn_agendar = find_btn(kb, "Agendar hora")
    
    # 2. Iniciar flujo
    text, kb = await interact(btn_agendar["callback_data"], is_callback=True)
    assert "especialidad" in text.lower()
    
    # 3. Manda comando desconocido
    text, kb = await interact("/comando_random")
    
    # Ideally tell the user that command is invalid, or just re-prompt politely.
    # We implemented a global rule that sends a warning message.
    assert "proceso" in text.lower() or "termina" in text.lower() or "especialidad" in text.lower()
    
    # 4. Manda comando /cancel
    text, kb = await interact("/cancel")
    assert "cancelada" in text.lower() or "cancelar" in text.lower()

