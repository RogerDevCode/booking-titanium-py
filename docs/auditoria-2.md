# Auditoría Pre-Producción (Edición Real) - Titanium Booking

**VEREDICTO DE PRODUCCIÓN: ❌ NO APTO PARA PRODUCCIÓN (Por características críticas pendientes)**

Esta auditoría contrasta el estado real del nuevo motor de reservas Titanium en FastAPI/ARQ frente a la base de código legacy en `f/`. Se desmienten afirmaciones falsas de reportes automáticos preliminares y se listan con precisión las brechas de seguridad, cumplimiento legal y resiliencia que impiden un paso a producción seguro.

---

## CONTEXTO REAL DE MIGRACIÓN: MITOS VS. REALIDAD

### 1. Sincronización Google Calendar (GCAL)
- **Estado en Auditorías Anteriores:** Se afirmaba falsamente como "no migrado".
- **Estado Real:** **✅ COMPLETAMENTE MIGRADO.** El motor de sincronización bidireccional y reconciliación está completamente implementado y verificado:
  - Clase `GCalService` en `app/services/gcal_service.py` maneja la sincronización, borrado de eventos y la lógica compleja de reconciliación (`reconcile_all()`) con auto-renovación de tokens OAuth2.
  - Tareas asíncronas en `app/worker/tasks.py` (`sync_booking_to_gcal`, `delete_gcal_event`) y cron job recurrente en `app/worker/settings.py` (`cron_reconcile_gcal` cada 5 minutos).
  - Tabla `gcal_events` activa en la base de datos.
  - Pruebas unitarias (`tests/unit/test_gcal_service.py`) e integración (`tests/integration/test_gcal_integration.py`) completamente funcionales.

### 2. Gestión de Listas de Espera (Waitlist)
- **Estado en Auditorías Anteriores:** Se afirmaba falsamente como "no migrado".
- **Estado Real:** **✅ COMPLETAMENTE MIGRADO y AMPLIADO.** La gestión inteligente y el backend administrativo de la lista de espera están operativos:
  - Tabla `waitlist` y `waitlist_notifications` en base de datos.
  - Tarea de fondo en el worker `notify_waitlist` que notifica automáticamente en batches y en diferido a los pacientes cuando una cita es liberada.
  - API REST de administración web completada en `app/api/v1/provider.py` con endpoints para:
    - Listar pacientes activos en lista de espera (`GET /provider/{id}/waitlist`).
    - Remover de lista manualmente (`DELETE /provider/{id}/waitlist/{entry_id}`).
    - Obtener métricas y tasas de conversión (`GET /provider/{id}/waitlist/stats`).
  - Pruebas de integración completas en `tests/integration/test_waitlist_endpoints.py`.

### 3. Mantenimiento Autónomo de Estado (Crons)
- **Estado en Auditorías Anteriores:** Se afirmaba falsamente como "no migrado".
- **Estado Real:** **✅ COMPLETAMENTE MIGRADO.**
  - Cron `cron_auto_cancel` en `app/worker/settings.py` ejecuta la cancelación automática de reservas pendientes expiradas cada 10 minutos.
  - Cron `cron_noshow_trigger` procesa los No-Shows automáticamente e incrementa penalizaciones según las reglas específicas de cada proveedor.

### 4. Dashboard Analítico
- **Estado en Auditorías Anteriores:** Se afirmaba falsamente como "no migrado".
- **Estado Real:** **✅ COMPLETAMENTE MIGRADO.**
  - API `/api/v1/dashboard/stats` implementada en `app/api/v1/dashboard.py` y verificada en las pruebas de endpoints administrativos.

---

## DETALLE DE COMPONENTES FALTANTES (REALES)

Las siguientes 4 ausencias son brechas reales y críticas que deben ser subsanadas antes del despliegue:

### 1. Notas Clínicas Encriptadas AES-256-GCM (`f/web_provider_notes`)
- **Impacto:** **CRÍTICO.** Falta portar la tabla `service_notes` y el módulo de cifrado AES-256-GCM en reposo. Almacenar notas médicas en texto plano o carecer del módulo expone información PHI sensible y constituye una violación de la ley de protección de datos de salud y privacidad.

### 2. Canal de Notificación Email (`f/gmail_send`)
- **Impacto:** **MEDIO.** Aunque el motor de recordatorios y preferencias multicanal está migrado (`reminder_preferences`), no existe el envío a través del canal email. El código de `NotificationService.send_reminders()` solo cuenta con el canal de Telegram. El módulo de envío de correo por Gmail/SMTP (`f/gmail_send`) no se ha portado.

### 3. Procesamiento de Tareas Fallidas / Dead Letter Queue (`f/dlq_processor`)
- **Impacto:** **ALTO.** El worker de ARQ no tiene configurado un procesador de Dead Letter Queue (DLQ) para reintentar y auditar de forma estructurada las tareas que fallan catastróficamente (por ejemplo, caídas temporales de red en el envío de mensajes de Telegram o sincronización de Google Calendar).

### 4. Trazabilidad Conversacional (`f/conversation_logger`)
- **Impacto:** **MEDIO.** No se ha migrado la tabla `conversations` ni la persistencia de los mensajes del chat bot. Actualmente no hay un registro histórico auditable de los mensajes crudos enviados y recibidos por el usuario de Telegram para análisis forense o RAG conversacional avanzado.

---

## RECOMENDACIÓN TÁCTICA RED TEAM (TESTS DE EXPLOTACIÓN)

Para asegurar que estas brechas reales detengan el pase a producción, se ratifica la propuesta de implementar los siguientes 5 tests de explotación que deben permanecer en rojo hasta su resolución:

1. `test_compliance_phi_plaintext_exposure`: Comprueba que las notas médicas de los pacientes no queden expuestas en texto plano en la base de datos.
2. `test_exploit_infinite_slot_lock_abuse`: Valida la resiliencia contra el secuestro de slots en estado `PENDING` por ataques DoS si se detiene el worker de autoliberación.
3. `test_red_team_cancelled_slot_abandonment`: Demuestra pérdida económica al comprobar que si el despachador de notificaciones de lista de espera falla, el cupo no se reasigna.
4. `test_red_team_gcal_phantom_booking_desync`: Simula fallos de red durante la sincronización a Google Calendar para exponer la falta de consistencia eventual sin el reconciliador.
5. `test_resilience_silent_message_drop_under_network_failure`: Expone la pérdida silenciosa de confirmaciones médicas ante fallos persistentes de red debido a la ausencia del procesador DLQ.

*Nota: Por directiva expresa de auditoría, los archivos de test vigentes no han sido modificados para evitar falsos positivos en la suite actual.*