import json
import pytest
from unittest.mock import AsyncMock

from app.worker.tasks import make_process_message

@pytest.mark.asyncio
async def test_end_to_end_booking_menu_navigation(integration_container, clean_db_and_redis):
    """
    Este test resuelve el problema de la "ceguera" en las pruebas anteriores.
    En lugar de generar artificialmente los payloads de estado, este test:
    1. Ejecuta el worker pipeline real (preprocesador -> clasificador -> router).
    2. Lee la base de datos real (outbox_messages) para ver qué teclado se envió al usuario.
    3. Extrae dinámicamente el `callback_data` REAL del botón generado por `build_inline_keyboard`.
    4. Lo inyecta como el siguiente mensaje del usuario.
    
    Esto asegura que tanto la codificación de callbacks, las transiciones de estado, 
    y el renderizado de menús funcionen en armonía.
    """
    # 1. Setup Data in DB for the test
    spec_id = "11111111-1111-1111-1111-111111111111"
    doc_id = "22222222-2222-2222-2222-222222222222"
    
    # Mock Telegram API calls so we don't spam the real API
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
    chat_id = 88888

    # Helper function to process a message and get the latest keyboard sent to outbox
    async def interact(text: str, is_callback: bool = False):
        # Clear outbox before action to only get the response for this interaction
        await integration_container.db_client.execute("DELETE FROM outbox_messages WHERE chat_id = $1", chat_id)
        
        from typing import Any
        payload: dict[str, Any] = {"message": {"chat": {"id": chat_id, "first_name": "TestUser"}}}
        if is_callback:
            payload["callback_query"] = {
                "id": "test_query_id",
                "message": {"chat": {"id": chat_id}},
                "data": text
            }
        else:
            payload["message"]["text"] = text

        await process_message({}, payload)
        
        # Fetch the latest message from outbox
        row = await integration_container.db_client.fetchrow(
            "SELECT text, reply_markup FROM outbox_messages WHERE chat_id = $1 ORDER BY created_at DESC LIMIT 1", 
            chat_id
        )
        assert row is not None, "No response was sent to the user!"
        
        markup_str = row["reply_markup"]
        keyboard = json.loads(markup_str)["inline_keyboard"] if markup_str else []
        return row["text"], keyboard

    # --- FLUJO DE INTERACCIÓN REAL ---

    # 1. El usuario envía /start
    text, keyboard = await interact("/start", is_callback=False)
    assert "Bienvenido al Sistema de Reservas" in text
    
    # Buscar el botón de "Agendar hora"
    agendar_btn = None
    for row in keyboard:
        for btn in row:
            if "Agendar hora" in btn.get("text", ""):
                agendar_btn = btn
                break
    assert agendar_btn is not None, "Botón de Agendar hora no encontrado"
    
    # 2. El usuario hace click en "Agendar hora" (usamos su callback_data exacto generado por el sistema)
    text, keyboard = await interact(agendar_btn["callback_data"], is_callback=True)
    assert "especialidad buscas" in text
    
    # Buscar el botón de "Especialidad_Test"
    cardio_btn = None
    for row in keyboard:
        for btn in row:
            if "Especialidad_Test" in btn.get("text", ""):
                cardio_btn = btn
                break
    assert cardio_btn is not None, "Botón de Especialidad_Test no encontrado"

    # 3. El usuario selecciona "Especialidad_Test"
    text, keyboard = await interact(cardio_btn["callback_data"], is_callback=True)
    assert "Seleccionar Médico" in text
    
    # Buscar el botón de "Dr. Test"
    doc_btn = None
    for row in keyboard:
        for btn in row:
            if "Dr. Test" in btn.get("text", ""):
                doc_btn = btn
                break
    assert doc_btn is not None, "Botón del doctor no encontrado"

    # 4. El usuario selecciona al Dr. Test
    text, keyboard = await interact(doc_btn["callback_data"], is_callback=True)
    assert "Seleccionar Horario" in text
    
    # 5. El usuario selecciona la hora (la primera disponible)
    time_btn = keyboard[0][0]
    text, keyboard = await interact(time_btn["callback_data"], is_callback=True)
    assert "Confirma tu reserva" in text
    
    # 6. El usuario confirma
    confirm_btn = None
    for row in keyboard:
        for btn in row:
            if "SÍ, confirmar" in btn.get("text", ""):
                confirm_btn = btn
                break
    assert confirm_btn is not None, "Botón de SÍ, confirmar no encontrado"
    
    text, keyboard = await interact(confirm_btn["callback_data"], is_callback=True)
    assert "reserva confirmada" in text.lower() or "¡listo!" in text.lower()

    # Verificamos que se haya guardado en la DB
    booking = await integration_container.db_client.fetchrow("SELECT * FROM bookings WHERE user_id = $1", chat_id)
    assert booking is not None
    assert booking["status"] == "CONFIRMED"
