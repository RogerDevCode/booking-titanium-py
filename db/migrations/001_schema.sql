-- ============================================================================
-- TITANIUM BOOKING ENGINE — DDL MAESTRO
-- Archivo: db/migrations/001_schema.sql
-- Propósito: Esquema completo desde cero. Ejecutar en BD vacía.
-- Convenciones:
--   • Todas las PKs son BIGINT GENERATED ALWAYS AS IDENTITY (excepto users.id
--     que es el chat_id de Telegram, por lo que se inserta manualmente).
--   • Timestamps con zona horaria (TIMESTAMPTZ) en UTC.
--   • Soft-delete donde aplique (is_active / status).
--   • CHECK constraints para validaciones de dominio.
--   • Índices parciales para queries frecuentes.
-- ============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- EXTENSIONES
-- ─────────────────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Wrapper inmutable para usar unaccent en índices
CREATE OR REPLACE FUNCTION immutable_unaccent(text) RETURNS text AS $$
    SELECT public.unaccent($1);
$$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE STRICT;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. USERS (Pacientes / Usuarios de Telegram)
-- PK = chat_id de Telegram (BIGINT, no autogenerado)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE users (
    id          BIGINT      PRIMARY KEY,  -- Telegram chat_id
    username    VARCHAR(100),
    first_name  VARCHAR(100) NOT NULL,
    last_name   VARCHAR(100),
    phone       VARCHAR(20),
    email       VARCHAR(255),
    address     VARCHAR(255),
    rut         VARCHAR(20),
    is_active   BOOLEAN     NOT NULL DEFAULT true,
    is_blocked  BOOLEAN     NOT NULL DEFAULT false,
    blocked_until TIMESTAMPTZ,
    noshow_count INT        NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_users_noshow_count CHECK (noshow_count >= 0)
);

CREATE INDEX idx_users_rut   ON users (rut)   WHERE rut IS NOT NULL;
CREATE INDEX idx_users_phone ON users (phone) WHERE phone IS NOT NULL;
CREATE INDEX idx_users_email ON users (email) WHERE email IS NOT NULL;
CREATE INDEX idx_users_name  ON users USING gin (
    (immutable_unaccent(first_name) || ' ' || COALESCE(immutable_unaccent(last_name), '')) gin_trgm_ops
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. SPECIALTIES
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE specialties (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. PROVIDERS (Profesionales médicos)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE providers (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    specialty_id            BIGINT       NOT NULL REFERENCES specialties(id),
    bio                     TEXT,
    is_active               BOOLEAN      NOT NULL DEFAULT true,
    slot_duration_minutes   INT          NOT NULL DEFAULT 30,
    buffer_time_minutes     INT          NOT NULL DEFAULT 0,
    notice_period_hours     INT          NOT NULL DEFAULT 4,
    waitlist_batch_size     INT          NOT NULL DEFAULT 3,
    waitlist_delay_minutes  INT          NOT NULL DEFAULT 15,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_providers_slot_duration CHECK (slot_duration_minutes BETWEEN 5 AND 480),
    CONSTRAINT chk_providers_buffer        CHECK (buffer_time_minutes BETWEEN 0 AND 120),
    CONSTRAINT chk_providers_notice        CHECK (notice_period_hours BETWEEN 0 AND 168),
    CONSTRAINT chk_providers_batch         CHECK (waitlist_batch_size BETWEEN 1 AND 50),
    CONSTRAINT chk_providers_delay         CHECK (waitlist_delay_minutes BETWEEN 1 AND 1440)
);

CREATE INDEX idx_providers_specialty ON providers (specialty_id) WHERE is_active = true;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. PROVIDER_SCHEDULES (Horarios semanales)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE provider_schedules (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id  BIGINT  NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    day_of_week  INT     NOT NULL,
    start_time   TIME    NOT NULL,
    end_time     TIME    NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_schedule_day  CHECK (day_of_week BETWEEN 0 AND 6),
    CONSTRAINT chk_schedule_time CHECK (start_time < end_time)
);

CREATE INDEX idx_schedules_provider ON provider_schedules (provider_id, day_of_week)
    WHERE is_active = true;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. PROVIDER_EXCEPTIONS (Bloqueos / Ausencias)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE provider_exceptions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id     BIGINT       NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    start_datetime  TIMESTAMPTZ  NOT NULL,
    end_datetime    TIMESTAMPTZ  NOT NULL,
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_exception_dates CHECK (start_datetime < end_datetime)
);

CREATE INDEX idx_exceptions_provider_range ON provider_exceptions (provider_id, start_datetime, end_datetime);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. SLOTS (Horas de atención generadas por el SlotEngine)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE slots (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id  BIGINT       NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    start_time   TIMESTAMPTZ  NOT NULL,
    end_time     TIMESTAMPTZ  NOT NULL,
    is_available BOOLEAN      NOT NULL DEFAULT true,

    CONSTRAINT chk_slot_times     CHECK (start_time < end_time),
    CONSTRAINT uq_slot_provider_start UNIQUE (provider_id, start_time)
);

CREATE INDEX idx_slots_available ON slots (provider_id, start_time)
    WHERE is_available = true;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. BOOKINGS (Reservas)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TYPE booking_status AS ENUM ('PENDING', 'CONFIRMED', 'CANCELLED', 'COMPLETED', 'NO_SHOW');

CREATE TABLE bookings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT         NOT NULL REFERENCES users(id),
    slot_id         BIGINT         NOT NULL REFERENCES slots(id),
    status          booking_status NOT NULL DEFAULT 'CONFIRMED',
    reminders_sent  INT            NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_booking_reminders CHECK (reminders_sent BETWEEN 0 AND 10)
);

CREATE INDEX idx_bookings_user    ON bookings (user_id, status);
CREATE INDEX idx_bookings_slot    ON bookings (slot_id);
CREATE INDEX idx_bookings_pending ON bookings (created_at)
    WHERE status = 'PENDING';

-- Prevent double-booking: only one active booking per slot
CREATE UNIQUE INDEX uq_bookings_active_slot
    ON bookings (slot_id)
    WHERE status IN ('PENDING', 'CONFIRMED');

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. WAITLIST
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE waitlist (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id),
    provider_id BIGINT      NOT NULL REFERENCES providers(id),
    status      VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_waitlist_status CHECK (status IN ('ACTIVE', 'NOTIFIED', 'FULFILLED', 'EXPIRED')),
    CONSTRAINT uq_waitlist_active  UNIQUE (user_id, provider_id, status)
);

CREATE INDEX idx_waitlist_provider ON waitlist (provider_id, status, created_at)
    WHERE status = 'ACTIVE';

-- ─────────────────────────────────────────────────────────────────────────────
-- 9. WAITLIST_NOTIFICATIONS
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE waitlist_notifications (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    waitlist_id BIGINT      NOT NULL REFERENCES waitlist(id) ON DELETE CASCADE,
    slot_id     BIGINT      NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
    notified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_waitlist_notif UNIQUE (waitlist_id, slot_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 10. CONVERSATION_STATES (FSM State — SSOT)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE conversation_states (
    chat_id       BIGINT      PRIMARY KEY,  -- = users.id (Telegram chat_id)
    state         VARCHAR(50) NOT NULL DEFAULT 'IDLE',
    active_flow   VARCHAR(50),
    context       JSONB       NOT NULL DEFAULT '{}',
    booking_draft JSONB       NOT NULL DEFAULT '{}',
    message_id    INT,
    version       INT         NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_conv_version CHECK (version >= 0)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 11. OUTBOX_MESSAGES (Transactional Outbox Pattern)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE outbox_messages (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id      BIGINT      NOT NULL,
    text         TEXT        NOT NULL,
    reply_markup JSONB,
    status       VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_outbox_status CHECK (status IN ('PENDING', 'SENT', 'FAILED', 'CANCELLED'))
);

CREATE INDEX idx_outbox_pending ON outbox_messages (chat_id, created_at)
    WHERE status = 'PENDING';

-- ─────────────────────────────────────────────────────────────────────────────
-- 12. KNOWLEDGE_BASE (RAG)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE knowledge_base (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id   BIGINT REFERENCES providers(id) ON DELETE SET NULL,
    title         VARCHAR(255),
    category      VARCHAR(50) NOT NULL,
    content       TEXT        NOT NULL,
    is_active     BOOLEAN     NOT NULL DEFAULT true,
    search_vector TSVECTOR,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kb_search ON knowledge_base USING gin (search_vector);
CREATE INDEX idx_kb_provider ON knowledge_base (provider_id) WHERE provider_id IS NOT NULL;

-- Auto-generate search_vector on insert/update
CREATE OR REPLACE FUNCTION kb_search_vector_trigger() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('spanish',
        COALESCE(immutable_unaccent(NEW.title), '') || ' ' ||
        immutable_unaccent(NEW.content)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_kb_search_vector
    BEFORE INSERT OR UPDATE OF title, content ON knowledge_base
    FOR EACH ROW EXECUTE FUNCTION kb_search_vector_trigger();

-- ─────────────────────────────────────────────────────────────────────────────
-- 13. REMINDER_PREFERENCES
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE reminder_preferences (
    user_id          BIGINT  PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    telegram_enabled BOOLEAN NOT NULL DEFAULT true,
    email_enabled    BOOLEAN NOT NULL DEFAULT false,
    window_24h       BOOLEAN NOT NULL DEFAULT true,
    window_2h        BOOLEAN NOT NULL DEFAULT true,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 14. USER_PENALTIES (No-Show tracking)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE user_penalties (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    penalty_type  VARCHAR(30) NOT NULL,
    reason        TEXT,
    active_until  TIMESTAMPTZ,
    is_active     BOOLEAN     NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_penalty_type CHECK (penalty_type IN ('WARNING', 'TEMP_BAN', 'PERM_BAN'))
);

CREATE INDEX idx_penalties_user ON user_penalties (user_id) WHERE is_active = true;

-- ─────────────────────────────────────────────────────────────────────────────
-- 15. GCAL_EVENTS (Google Calendar sync — futuro)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE gcal_events (
    booking_id       BIGINT PRIMARY KEY REFERENCES bookings(id) ON DELETE CASCADE,
    gcal_event_id    TEXT        NOT NULL,
    gcal_calendar_id TEXT        NOT NULL,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 16. AUDIT_LOG (Trazabilidad)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE audit_log (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name VARCHAR(50)  NOT NULL,
    record_id  BIGINT       NOT NULL,
    action     VARCHAR(10)  NOT NULL,  -- INSERT, UPDATE, DELETE
    old_data   JSONB,
    new_data   JSONB,
    actor_id   BIGINT,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_audit_action CHECK (action IN ('INSERT', 'UPDATE', 'DELETE'))
);

CREATE INDEX idx_audit_table_record ON audit_log (table_name, record_id);
CREATE INDEX idx_audit_created      ON audit_log (created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- TRIGGERS: auto-update updated_at
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION trigger_set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY[
        'users', 'specialties', 'providers', 'provider_schedules',
        'provider_exceptions', 'bookings', 'waitlist',
        'knowledge_base', 'reminder_preferences'
    ]) LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()',
            tbl, tbl
        );
    END LOOP;
END;
$$;

COMMIT;
