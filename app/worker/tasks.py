import time
from app.core.logging import logger

def make_process_message(container):
    async def process_message(ctx: dict, payload: dict) -> None:
        """
        Main worker job to process a Telegram message.
        Orchestrates preprocessor, classifier, and FSM router.
        """
        start_time = time.perf_counter()
    
        # 1. Extract basic info from payload
        callback_query = payload.get("callback_query")
        message = payload.get("message") or (callback_query["message"] if callback_query else None)
    
        if not message:
            logger.warning("No message in payload", payload=payload)
            return

        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        callback_data = callback_query.get("data") if callback_query else None

        # Upsert user to ensure they exist in DB
        from app.domain.entities import TelegramUser
        
        _, is_new = await container.user_service.upsert_user(TelegramUser(
            id=chat_id,
            username=message["chat"].get("username"),
            first_name=message["chat"].get("first_name", str(chat_id)),
            last_name=message["chat"].get("last_name")
        ))
    
        if is_new:
            
            welcome_msg = (
                f"👋 ¡Hola {message['chat'].get('first_name', '')}! Bienvenido/a a Titanium Booking.\n\n"
                "💡 Veo que es tu primera vez aquí. Te invito a pasar por la sección *👤 Mis Datos* "
                "del menú principal en cualquier momento para completar tu perfil, así podré enviarte "
                "recordatorios y comprobantes a tu correo. ¡Comencemos!"
            )
            await container.telegram_sender.send_message(chat_id, welcome_msg)
            await container.telegram_sender.flush_outbox(chat_id)    
        input_text = callback_data if callback_data else text
        if not input_text:
            logger.info("Empty message received", chat_id=chat_id)
            return

        logger.info("Processing message", chat_id=chat_id, input=input_text)

        try:
            # 1.1 If it's a callback, answer it to stop the loading icon
            
            if callback_query:
                await container.telegram_sender.answer_callback_query(callback_query["id"])
                if callback_data == "ignore":
                    logger.info("Ignored ghost click from disabled menu", chat_id=chat_id)
                    return

            # 2. Preprocess (Security, Modisms, Spelling)
            if callback_data:
                from app.domain.models import PreprocessorOutput, SecurityScanResult
                prep_result = PreprocessorOutput(
                    raw_text=callback_data,
                    cleaned_text=callback_data,
                    normalization_applied=False,
                    spell_corrections=[],
                    modism_matches=[],
                    confidence=1.0,
                    extracted_entities=None, # type: ignore
                    security_scan=SecurityScanResult(threat_detected=False, threat_type="none"),
                )
            else:
                preprocessor = container.preprocessor
                prep_result = preprocessor.preprocess(input_text)
            
                if prep_result.security_scan.threat_detected:
                    logger.warning("Security threat blocked", chat_id=chat_id, type=prep_result.security_scan.threat_type)
                    await container.telegram_sender.send_message(
                        chat_id, 
                        "⚠️ Tu mensaje contiene texto o patrones no permitidos y ha sido bloqueado por razones de seguridad."
                    )
                    await container.telegram_sender.flush_outbox(chat_id)
                    return

            # 3. Handle state and routing
            
            from app.domain.enums import FSMState
        
            # Acquire Redis Distributed Lock to ensure sequential processing for this user
            async with container.redis_client.get_chat_lock(chat_id):
                # 4. Get Current State (SSOT) - No DB transaction needed for a simple select
                state = await container.conversation_tx.get_state(chat_id)
            
                # 5. PRE-FLIGHT I/O: Perform heavy network calls outside the DB transaction
                preflight_data = {}
            
                if state.state == FSMState.IDLE:
                    from app.domain.enums import Intent
                    from app.telegram.callback import decode
                    import asyncio
                
                    cb_payload = decode(prep_result.cleaned_text)
                    text_to_classify = cb_payload.value if cb_payload is not None else prep_result.cleaned_text
                
                    classifier = container.classifier
                    try:
                        intent, confidence = await asyncio.wait_for(
                            classifier.classify(text_to_classify), timeout=2.5
                        )
                    except asyncio.TimeoutError:
                        logger.error("IntentClassifier timeout", chat_id=chat_id)
                        intent, confidence = Intent.UNKNOWN, 0.0
                    
                    preflight_data["intent"] = intent
                    preflight_data["confidence"] = confidence
                
                elif state.state == FSMState.WAITING_FAQ:
                    if prep_result.cleaned_text.lower() not in ["volver", "salir", "menu", "4"]:
                        
                        
                        from app.core.circuit_breaker import CircuitBreakerOpenException
                        import asyncio
                    
                        try:
                            kb_entries = await asyncio.wait_for(
                                container.rag_service.search(prep_result.cleaned_text), timeout=1.0
                            )
                        
                            preflight_data["rag_categories"] = [e.category for e in kb_entries]
                            preflight_data["has_provider_faq"] = any(e.provider_id is not None for e in kb_entries)
                        
                            context = container.rag_service.format_context(kb_entries)
                            answer = await asyncio.wait_for(
                                container.ai_service.get_response(prep_result.cleaned_text, context), timeout=2.5
                            )
                        except asyncio.TimeoutError:
                            logger.error("AI service timeout", chat_id=chat_id)
                            answer = "⚠️ Lo siento, el sistema está tardando demasiado en responder. Por favor, intenta de nuevo o usa el menú principal."
                        except CircuitBreakerOpenException:
                            answer = "⚠️ Nuestro sistema de asistencia de IA está temporalmente sobrecargado. Por favor, usa el menú principal con botones o contáctanos por teléfono."
                        except Exception:
                            answer = "Lo siento, tuve un problema al procesar tu pregunta. Por favor intenta más tarde."
                        
                        preflight_data["rag_answer"] = answer
            
                # Inject preflight data into the state context
                state.context["preflight"] = preflight_data
            
                # 6. Start true global database transaction for FSM DB writes
                async with container.db_client.transaction():
                    # 7. Route to FSM Handler
                    # The router will update the state object and queue messages in outbox atomically
                    await container.fsm_router.route(state, prep_result.cleaned_text)
                
                    # 8. Save Updated State
                    await container.conversation_tx.set_state(state)
                
                # Check for GCal sync trigger after transaction commits successfully
                pending_syncs = state.context.get("gcal_sync_pending")
                if pending_syncs:
                    try:
                        arq_pool = await container.redis_client.get_arq_pool()
                        for sync in pending_syncs:
                            action = sync["action"]
                            bid = sync["booking_id"]
                            if action == "create":
                                await arq_pool.enqueue_job("sync_booking_to_gcal", bid)
                            elif action == "delete":
                                await arq_pool.enqueue_job("delete_gcal_event", bid)
                        
                        # Remove pending syncs from state context so they aren't processed again, and save
                        state.context.pop("gcal_sync_pending", None)
                        await container.conversation_tx.set_state(state)
                    except Exception as sync_err:
                        logger.error("Failed to enqueue GCal sync jobs", error=str(sync_err))
                
                # 9. OUTBOX FLUSH: Outside the DB transaction, send accumulated messages
                await container.telegram_sender.flush_outbox(chat_id)

            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info("Message processed successfully", chat_id=chat_id, elapsed_ms=elapsed)

        except Exception as e:
            logger.error("Worker failed to process message", error=str(e), exc_info=True)
            try:
                
                await container.telegram_sender.send_message(chat_id, "⚠️ Disculpa, hubo un problema interno. Por favor intenta de nuevo.")
                await container.telegram_sender.flush_outbox(chat_id)
            except Exception:
                pass

    return process_message

def make_cron_auto_cancel(container):
    async def cron_auto_cancel(ctx: dict) -> None:
        """Cron job to clean up expired pending bookings."""
        
        await container.notification_service.auto_cancel_expired_bookings()

    return cron_auto_cancel

def make_cron_noshow_trigger(container):
    async def cron_noshow_trigger(ctx: dict) -> None:
        """Cron job to process no-show triggers."""
        await container.notification_service.process_noshow_triggers()
    return cron_noshow_trigger

def make_cron_reminders(container):
    async def cron_reminders(ctx: dict) -> None:
        """Cron job to send appointment reminders."""
        
        await container.notification_service.send_reminders()

    return cron_reminders

def make_cron_flush_outbox(container):
    async def cron_flush_outbox(ctx: dict) -> None:
        """Fallback cron job to flush any PENDING outbox messages."""
        
    
        # Get unique chat_ids with PENDING messages
        query = "SELECT DISTINCT chat_id FROM outbox_messages WHERE status = 'PENDING'"
        rows = await container.db_client.fetch(query)
    
        for row in rows:
            await container.telegram_sender.flush_outbox(row["chat_id"])

    return cron_flush_outbox

def make_notify_waitlist(container):
    async def notify_waitlist(ctx: dict, slot_id: str, provider_id: str) -> None:
        """
        Background job to notify users on the waitlist when a slot is freed.
        It checks if the slot is still available, gets batch of users, notifies them,
        and schedules itself again after the provider's configured delay if there are more users.
        """
        

        # Check if slot is still available
        slot = await container.db_client.fetchrow(
            "SELECT start_time, is_available FROM slots WHERE id = $1", 
            slot_id
        )
        if not slot or not slot["is_available"]:
            logger.info("Waitlist abort: slot taken or not found", slot_id=slot_id)
            return

        # Get provider settings and info
        provider = await container.db_client.fetchrow(
            "SELECT name, waitlist_batch_size, waitlist_delay_minutes FROM providers WHERE id = $1",
            provider_id
        )
        if not provider:
            return

        batch_size = provider["waitlist_batch_size"] or 3
        delay_minutes = provider["waitlist_delay_minutes"] or 15

        # Get users to notify
        # Active waitlist users who haven't been notified for this slot yet
        query = """
            SELECT w.id as waitlist_id, w.user_id 
            FROM waitlist w
            LEFT JOIN waitlist_notifications wn ON w.id = wn.waitlist_id AND wn.slot_id = $1
            WHERE w.provider_id = $2 AND w.status = 'ACTIVE' AND wn.id IS NULL
            ORDER BY w.created_at ASC
            LIMIT $3
        """
        users_to_notify = await container.db_client.fetch(query, slot_id, provider_id, batch_size)

        if not users_to_notify:
            logger.info("Waitlist abort: no more users to notify", provider_id=provider_id)
            return

        from app.fsm.booking_flow import format_chile_time
        slot_time_str = format_chile_time(slot["start_time"])
    
        msg = (
            f"🚨 *¡Cupo Liberado en Lista de Espera!*\n\n"
            f"Se acaba de liberar una hora con el Dr. *{provider['name']}* para:\n"
            f"📅 {slot_time_str}\n\n"
            "Si te interesa, ingresa al menú principal y selecciona *Agendar hora* lo más pronto posible. "
            "¡Los cupos se toman rápido!"
        )

        notified_count = 0
        for u in users_to_notify:
            try:
                # Send message
                await container.telegram_sender.send_message(u["user_id"], msg)
            
                # Record notification
                await container.db_client.execute(
                    "INSERT INTO waitlist_notifications (waitlist_id, slot_id) VALUES ($1, $2)",
                    u["waitlist_id"], slot_id
                )
                notified_count += 1
            except Exception as e:
                logger.error("Failed to notify waitlist user", error=str(e), user_id=u["user_id"])

        logger.info("Notified waitlist batch", slot_id=slot_id, count=notified_count)

        # If we notified a full batch, there might be more users. 
        # Schedule next run after delay.
        if notified_count == batch_size:
            arq_pool = ctx.get("redis")
            if arq_pool:
                from datetime import timedelta
                await arq_pool.enqueue_job(
                    "notify_waitlist", 
                    slot_id, 
                    provider_id, 
                    _defer_by=timedelta(minutes=delay_minutes)
                )



    return notify_waitlist

def make_cron_generate_slots(container):
    async def cron_generate_slots(ctx: dict) -> None:
        """Cron job to project slots for all providers."""
        
        await container.slot_engine.generate_slots_for_all_providers(days=60)

    return cron_generate_slots

def make_generate_user_report_pdf(container):
    async def generate_user_report_pdf(chat_id: int):
        """Generates a PDF report for a user and sends it via Telegram."""
        from fpdf import FPDF
        
        
        
    
        try:
            user = await container.user_service.get_user(chat_id)
            if not user:
                return
            
            bookings = await container.booking_repo.get_history_all(chat_id)
        
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=16, style="B")
            pdf.cell(0, 10, text="Historial Medico Consolidado", new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_font("Helvetica", size=12)
            pdf.cell(0, 10, text=f"Paciente: {user.first_name} {user.last_name or ''}", new_x="LMARGIN", new_y="NEXT", align="C")
            if user.rut:
                pdf.cell(0, 10, text=f"RUT: {user.rut}", new_x="LMARGIN", new_y="NEXT", align="C")
        
            pdf.ln(10)
        
            pdf.set_font("Helvetica", size=10, style="B")
            pdf.cell(35, 10, "Fecha", border=1)
            pdf.cell(55, 10, "Especialidad", border=1)
            pdf.cell(55, 10, "Profesional", border=1)
            pdf.cell(25, 10, "Estado", border=1, new_x="LMARGIN", new_y="NEXT")
        
            pdf.set_font("Helvetica", size=10)
            status_es = {"CONFIRMED": "Confirmado", "CANCELLED": "Cancelado", "PENDING": "Pendiente", "COMPLETED": "Completado"}
        
            for b in bookings:
                dt_str = b.start_time.strftime("%d/%m/%y %H:%M")
                pdf.cell(35, 10, dt_str, border=1)
                pdf.cell(55, 10, b.specialty_name[:25], border=1)
                pdf.cell(55, 10, b.provider_name[:25], border=1)
                pdf.cell(25, 10, status_es.get(b.status.value, "Desconocido"), border=1, new_x="LMARGIN", new_y="NEXT")
            
            pdf_bytes = pdf.output()
        
            await container.telegram_sender.send_document(
                chat_id, 
                document=bytes(pdf_bytes), 
                filename=f"Reporte_Medico_{user.first_name}.pdf",
                caption="Aquí tienes tu historial consolidado de los últimos 24 meses."
            )
        except Exception as e:
            logger.error("Error generating PDF", error=str(e), chat_id=chat_id)
            
            await container.telegram_sender.send_message(chat_id, "❌ Hubo un error al generar tu PDF. Por favor, intenta más tarde.")

    return generate_user_report_pdf


def make_sync_booking_to_gcal(container):
    async def sync_booking_to_gcal(ctx: dict, booking_id: int) -> None:
        """Background job to sync booking to Google Calendar."""
        logger.info("Worker sync_booking_to_gcal running", booking_id=booking_id)
        await container.gcal_service.sync_booking_to_gcal(booking_id)
    return sync_booking_to_gcal


def make_delete_gcal_event(container):
    async def delete_gcal_event(ctx: dict, booking_id: int) -> None:
        """Background job to delete event from Google Calendar."""
        logger.info("Worker delete_gcal_event running", booking_id=booking_id)
        await container.gcal_service.delete_gcal_event(booking_id)
    return delete_gcal_event


def make_cron_reconcile_gcal(container):
    async def cron_reconcile_gcal(ctx: dict) -> None:
        """Cron job to reconcile Google Calendar and DB discrepancies."""
        logger.info("Worker cron_reconcile_gcal running")
        await container.gcal_service.reconcile_all()
    return cron_reconcile_gcal
