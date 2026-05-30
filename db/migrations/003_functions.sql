-- ============================================================================
-- TITANIUM BOOKING ENGINE — STORED PROCEDURES & BUSINESS RULES
-- Archivo: db/migrations/003_functions.sql
-- Propósito: Validaciones de reglas de negocio dentro de la base de datos.
--            Garantizan integridad transaccional sin depender de la app.
-- ============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- fn_create_booking: Crea una reserva atómicamente
-- Verifica: slot disponible, usuario no bloqueado, no double-booking
-- Usa: pg_advisory_xact_lock para serializar por slot_id
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_create_booking(
    p_user_id  BIGINT,
    p_slot_id  BIGINT
) RETURNS TABLE (
    booking_id  BIGINT,
    slot_start  TIMESTAMPTZ,
    slot_end    TIMESTAMPTZ,
    provider_id BIGINT
) AS $$
DECLARE
    v_slot       RECORD;
    v_user       RECORD;
    v_booking_id BIGINT;
BEGIN
    -- 1. Advisory lock on slot to prevent concurrent booking
    PERFORM pg_advisory_xact_lock(p_slot_id);

    -- 2. Verify user is not blocked
    SELECT u.is_blocked, u.blocked_until
      INTO v_user
      FROM users u
     WHERE u.id = p_user_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'USER_NOT_FOUND: User % does not exist', p_user_id;
    END IF;

    IF v_user.is_blocked AND (v_user.blocked_until IS NULL OR v_user.blocked_until > NOW()) THEN
        RAISE EXCEPTION 'USER_BLOCKED: User % is blocked from booking', p_user_id;
    END IF;

    -- 3. Lock and verify slot
    SELECT s.id, s.start_time, s.end_time, s.provider_id, s.is_available
      INTO v_slot
      FROM slots s
     WHERE s.id = p_slot_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'SLOT_NOT_FOUND: Slot % does not exist', p_slot_id;
    END IF;

    IF NOT v_slot.is_available THEN
        RAISE EXCEPTION 'SLOT_UNAVAILABLE: Slot % is no longer available', p_slot_id;
    END IF;

    IF v_slot.start_time <= NOW() THEN
        RAISE EXCEPTION 'SLOT_IN_PAST: Slot % has already started', p_slot_id;
    END IF;

    -- 4. Mark slot as taken
    UPDATE slots SET is_available = false WHERE id = p_slot_id;

    -- 5. Create booking
    INSERT INTO bookings (user_id, slot_id, status)
    VALUES (p_user_id, p_slot_id, 'CONFIRMED')
    RETURNING id INTO v_booking_id;

    -- 6. Audit
    INSERT INTO audit_log (table_name, record_id, action, new_data, actor_id)
    VALUES ('bookings', v_booking_id, 'INSERT',
            jsonb_build_object('user_id', p_user_id, 'slot_id', p_slot_id, 'status', 'CONFIRMED'),
            p_user_id);

    RETURN QUERY SELECT v_booking_id, v_slot.start_time, v_slot.end_time, v_slot.provider_id;
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────────────────
-- fn_cancel_booking: Cancela una reserva y libera el slot
-- Verifica: ownership, estado cancelable
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_cancel_booking(
    p_user_id    BIGINT,
    p_booking_id BIGINT
) RETURNS TABLE (
    freed_slot_id  BIGINT,
    provider_id    BIGINT
) AS $$
DECLARE
    v_booking RECORD;
BEGIN
    -- 1. Lock booking row
    SELECT b.id, b.user_id, b.slot_id, b.status
      INTO v_booking
      FROM bookings b
     WHERE b.id = p_booking_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'BOOKING_NOT_FOUND: Booking % does not exist', p_booking_id;
    END IF;

    -- 2. Verify ownership
    IF v_booking.user_id != p_user_id THEN
        RAISE EXCEPTION 'UNAUTHORIZED: User % does not own booking %', p_user_id, p_booking_id;
    END IF;

    -- 3. Verify cancellable status
    IF v_booking.status NOT IN ('PENDING', 'CONFIRMED') THEN
        RAISE EXCEPTION 'INVALID_STATUS: Cannot cancel booking with status %', v_booking.status;
    END IF;

    -- 4. Cancel booking
    UPDATE bookings 
       SET status = 'CANCELLED', updated_at = NOW()
     WHERE id = p_booking_id;

    -- 5. Free the slot
    UPDATE slots SET is_available = true WHERE id = v_booking.slot_id;

    -- 6. Audit
    INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, actor_id)
    VALUES ('bookings', p_booking_id, 'UPDATE',
            jsonb_build_object('status', v_booking.status::text),
            jsonb_build_object('status', 'CANCELLED'),
            p_user_id);

    RETURN QUERY SELECT v_booking.slot_id,
        (SELECT s.provider_id FROM slots s WHERE s.id = v_booking.slot_id);
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────────────────
-- fn_reschedule_booking: Cancela una reserva y crea una nueva atómicamente
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_reschedule_booking(
    p_user_id        BIGINT,
    p_old_booking_id BIGINT,
    p_new_slot_id    BIGINT
) RETURNS TABLE (
    new_booking_id BIGINT,
    old_slot_id    BIGINT,
    new_slot_start TIMESTAMPTZ,
    new_slot_end   TIMESTAMPTZ
) AS $$
DECLARE
    v_old      RECORD;
    v_new_slot RECORD;
    v_new_id   BIGINT;
BEGIN
    -- 1. Lock old booking
    SELECT b.id, b.user_id, b.slot_id, b.status
      INTO v_old
      FROM bookings b
     WHERE b.id = p_old_booking_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'BOOKING_NOT_FOUND: Old booking % not found', p_old_booking_id;
    END IF;

    IF v_old.user_id != p_user_id THEN
        RAISE EXCEPTION 'UNAUTHORIZED: User % does not own booking %', p_user_id, p_old_booking_id;
    END IF;

    IF v_old.status NOT IN ('PENDING', 'CONFIRMED') THEN
        RAISE EXCEPTION 'INVALID_STATUS: Cannot reschedule booking with status %', v_old.status;
    END IF;

    -- 2. Advisory lock on new slot
    PERFORM pg_advisory_xact_lock(p_new_slot_id);

    -- 3. Lock and verify new slot
    SELECT s.id, s.start_time, s.end_time, s.is_available
      INTO v_new_slot
      FROM slots s
     WHERE s.id = p_new_slot_id
       FOR UPDATE;

    IF NOT FOUND OR NOT v_new_slot.is_available THEN
        RAISE EXCEPTION 'SLOT_UNAVAILABLE: New slot % not available', p_new_slot_id;
    END IF;

    IF v_new_slot.start_time <= NOW() THEN
        RAISE EXCEPTION 'SLOT_IN_PAST: New slot % has already started', p_new_slot_id;
    END IF;

    -- 4. Cancel old booking + free old slot
    UPDATE bookings SET status = 'CANCELLED', updated_at = NOW() WHERE id = p_old_booking_id;
    UPDATE slots SET is_available = true WHERE id = v_old.slot_id;

    -- 5. Book new slot
    UPDATE slots SET is_available = false WHERE id = p_new_slot_id;
    INSERT INTO bookings (user_id, slot_id, status)
    VALUES (p_user_id, p_new_slot_id, 'CONFIRMED')
    RETURNING id INTO v_new_id;

    -- 6. Audit
    INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, actor_id)
    VALUES ('bookings', v_new_id, 'INSERT',
            jsonb_build_object('rescheduled_from', p_old_booking_id),
            jsonb_build_object('user_id', p_user_id, 'slot_id', p_new_slot_id, 'status', 'CONFIRMED'),
            p_user_id);

    RETURN QUERY SELECT v_new_id, v_old.slot_id, v_new_slot.start_time, v_new_slot.end_time;
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────────────────
-- fn_auto_cancel_expired: Cancela bookings PENDING expirados (>30min)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_auto_cancel_expired()
RETURNS TABLE (
    cancelled_booking_id BIGINT,
    freed_slot_id        BIGINT,
    affected_user_id     BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH expired AS (
        SELECT b.id, b.user_id, b.slot_id
          FROM bookings b
         WHERE b.status = 'PENDING'
           AND b.created_at < NOW() - INTERVAL '30 minutes'
           FOR UPDATE OF b
    ),
    cancel_bookings AS (
        UPDATE bookings SET status = 'CANCELLED', updated_at = NOW()
         WHERE id IN (SELECT id FROM expired)
        RETURNING id, slot_id, user_id
    ),
    free_slots AS (
        UPDATE slots SET is_available = true
         WHERE id IN (SELECT slot_id FROM expired)
    )
    SELECT cb.id, cb.slot_id, cb.user_id FROM cancel_bookings cb;
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────────────────
-- fn_mark_noshow: Marca un booking como NO_SHOW e incrementa el contador
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_mark_noshow(
    p_booking_id BIGINT
) RETURNS VOID AS $$
DECLARE
    v_user_id    BIGINT;
    v_noshow_cnt INT;
BEGIN
    -- 1. Update booking status
    UPDATE bookings SET status = 'NO_SHOW', updated_at = NOW()
     WHERE id = p_booking_id AND status = 'CONFIRMED'
    RETURNING user_id INTO v_user_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'INVALID_BOOKING: Booking % not eligible for no-show', p_booking_id;
    END IF;

    -- 2. Increment noshow counter
    UPDATE users SET noshow_count = noshow_count + 1, updated_at = NOW()
     WHERE id = v_user_id
    RETURNING noshow_count INTO v_noshow_cnt;

    -- 3. Auto-penalize based on thresholds
    IF v_noshow_cnt >= 5 THEN
        -- Block for 30 days
        UPDATE users SET is_blocked = true, blocked_until = NOW() + INTERVAL '30 days'
         WHERE id = v_user_id;
        INSERT INTO user_penalties (user_id, penalty_type, reason, active_until)
        VALUES (v_user_id, 'TEMP_BAN', 'Auto-ban: 5+ no-shows', NOW() + INTERVAL '30 days');
    ELSIF v_noshow_cnt >= 3 THEN
        -- Warning
        INSERT INTO user_penalties (user_id, penalty_type, reason)
        VALUES (v_user_id, 'WARNING', 'Auto-warning: 3+ no-shows')
        ON CONFLICT DO NOTHING;
    END IF;

    -- 4. Audit
    INSERT INTO audit_log (table_name, record_id, action, new_data, actor_id)
    VALUES ('bookings', p_booking_id, 'UPDATE',
            jsonb_build_object('status', 'NO_SHOW', 'noshow_count', v_noshow_cnt),
            v_user_id);
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────────────────
-- fn_get_conversation_state: Lee estado con advisory lock
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_get_conversation_state(
    p_chat_id BIGINT
) RETURNS TABLE (
    chat_id       BIGINT,
    state         VARCHAR,
    active_flow   VARCHAR,
    context       JSONB,
    booking_draft JSONB,
    message_id    INT,
    version       INT,
    updated_at    TIMESTAMPTZ
) AS $$
BEGIN
    -- Advisory lock scoped to transaction
    PERFORM pg_advisory_xact_lock(p_chat_id);

    RETURN QUERY
    SELECT cs.chat_id, cs.state, cs.active_flow, cs.context,
           cs.booking_draft, cs.message_id, cs.version, cs.updated_at
      FROM conversation_states cs
     WHERE cs.chat_id = p_chat_id;
END;
$$ LANGUAGE plpgsql;

COMMIT;
