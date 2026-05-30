import asyncio
import datetime
import uuid
from app.container import build_container
from app.core.logging import logger

async def main():
    logger.info("Iniciando prueba de recordatorios...")
    
    container = build_container()
    await container.db_client.connect()
    
    # Asegurarnos de que existe la columna (por si no se ha aplicado el DDL en el contenedor)
    try:
        await container.db_client.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminders_sent INT DEFAULT 0;")
        logger.info("Migración de columna 'reminders_sent' aplicada.")
    except Exception as e:
        logger.info(f"Columna ya existe o error menor: {e}")

    user_id = 999999
    
    # 1. Crear usuario
    from app.domain.entities import TelegramUser
    await container.user_service.upsert_user(TelegramUser(
        id=user_id,
        first_name="TestReminderUser"
    ))
    
    # 2. Obtener o crear especialidad
    row_spec = await container.db_client.fetchrow(
        "INSERT INTO specialties (name) VALUES ('Especialidad Test') ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )
    spec_id = row_spec['id']
    
    # 3. Crear doctor
    provider_id = uuid.uuid4()
    await container.db_client.execute(
        "INSERT INTO providers (id, name, specialty_id, is_active) VALUES ($1, 'Dr. Reminder', $2, true)",
        provider_id, spec_id
    )
    
    # 4. Crear slot para dentro de 23 horas (debería lanzar recordatorio de 24h)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    start_time_24h = now_utc + datetime.timedelta(hours=23, minutes=30)
    end_time_24h = start_time_24h + datetime.timedelta(minutes=30)
    
    # Crear slot para dentro de 1.5 horas (debería lanzar recordatorio de 2h)
    start_time_2h = now_utc + datetime.timedelta(hours=1, minutes=30)
    end_time_2h = start_time_2h + datetime.timedelta(minutes=30)

    # Insert slots
    row_24h = await container.db_client.fetchrow(
        "INSERT INTO slots (provider_id, start_time, end_time, is_available) VALUES ($1, $2, $3, false) RETURNING id",
        provider_id, start_time_24h, end_time_24h
    )
    slot_id_24h = row_24h['id']
    row_2h = await container.db_client.fetchrow(
        "INSERT INTO slots (provider_id, start_time, end_time, is_available) VALUES ($1, $2, $3, false) RETURNING id",
        provider_id, start_time_2h, end_time_2h
    )
    slot_id_2h = row_2h['id']
    
    # Insert bookings
    brow_24h = await container.db_client.fetchrow(
        "INSERT INTO bookings (user_id, slot_id, status, reminders_sent) VALUES ($1, $2, 'CONFIRMED', 0) RETURNING id",
        user_id, slot_id_24h
    )
    booking_id_24h = brow_24h['id']
    brow_2h = await container.db_client.fetchrow(
        "INSERT INTO bookings (user_id, slot_id, status, reminders_sent) VALUES ($1, $2, 'CONFIRMED', 0) RETURNING id",
        user_id, slot_id_2h
    )
    booking_id_2h = brow_2h['id']
    
    logger.info(f"Sembrados bookings: {booking_id_24h} (24h) y {booking_id_2h} (2h)")

    # Limpiar outbox previa
    await container.db_client.execute("DELETE FROM outbox_messages WHERE chat_id = $1", user_id)

    # Ejecutar el servicio de recordatorios
    await container.notification_service.send_reminders()
    
    # Revisar la base de datos (outbox)
    outbox = await container.db_client.fetch("SELECT text FROM outbox_messages WHERE chat_id = $1", user_id)
    
    for msg in outbox:
        logger.info(f"Mensaje generado para enviar: {msg['text']}")

    if len(outbox) == 2:
        logger.info("✅ ÉXITO: Se generaron ambos recordatorios correctamente.")
    else:
        logger.error(f"❌ FALLO: Se esperaban 2 mensajes, se generaron {len(outbox)}")
        
    await container.close()

if __name__ == "__main__":
    asyncio.run(main())
