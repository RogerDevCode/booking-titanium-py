-- ============================================================================
-- TITANIUM BOOKING ENGINE — ROW LEVEL SECURITY
-- Archivo: db/migrations/002_rls_policies.sql
-- Propósito: Aislamiento lógico por proveedor. Cada proveedor solo ve sus
--            datos como si tuviera su propia base de datos.
-- Uso: SET LOCAL app.current_provider_id = '<provider_id>';
-- ============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Rol de aplicación (el que usa la app para queries normales)
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user NOLOGIN;
    END IF;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- ─────────────────────────────────────────────────────────────────────────────
-- Helper: Obtener el provider_id del contexto de sesión
-- Retorna 0 si no hay contexto (modo admin/bypass)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION current_provider_id() RETURNS BIGINT AS $$
BEGIN
    RETURN COALESCE(
        NULLIF(current_setting('app.current_provider_id', true), '')::BIGINT,
        0
    );
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION is_admin_context() RETURNS BOOLEAN AS $$
BEGIN
    RETURN COALESCE(
        current_setting('app.admin_override', true),
        'false'
    )::BOOLEAN;
END;
$$ LANGUAGE plpgsql STABLE;

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS en SLOTS: Un proveedor solo ve/modifica sus propios slots
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE slots ENABLE ROW LEVEL SECURITY;

CREATE POLICY slots_isolation ON slots
    USING (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    )
    WITH CHECK (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    );

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS en BOOKINGS: Un proveedor solo ve reservas de sus slots
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;

CREATE POLICY bookings_isolation ON bookings
    USING (
        is_admin_context()
        OR current_provider_id() = 0
        OR slot_id IN (SELECT id FROM slots WHERE provider_id = current_provider_id())
    )
    WITH CHECK (
        is_admin_context()
        OR current_provider_id() = 0
        OR slot_id IN (SELECT id FROM slots WHERE provider_id = current_provider_id())
    );

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS en WAITLIST: Un proveedor solo ve su propia lista de espera
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;

CREATE POLICY waitlist_isolation ON waitlist
    USING (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    )
    WITH CHECK (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    );

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS en PROVIDER_SCHEDULES
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE provider_schedules ENABLE ROW LEVEL SECURITY;

CREATE POLICY schedules_isolation ON provider_schedules
    USING (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    )
    WITH CHECK (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    );

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS en PROVIDER_EXCEPTIONS
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE provider_exceptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY exceptions_isolation ON provider_exceptions
    USING (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    )
    WITH CHECK (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id = current_provider_id()
    );

-- ─────────────────────────────────────────────────────────────────────────────
-- RLS en KNOWLEDGE_BASE (FAQ por proveedor)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;

CREATE POLICY kb_isolation ON knowledge_base
    USING (
        is_admin_context()
        OR current_provider_id() = 0
        OR provider_id IS NULL  -- Global entries visible to all
        OR provider_id = current_provider_id()
    );

-- ─────────────────────────────────────────────────────────────────────────────
-- Nota: Las tablas users, specialties, conversation_states, outbox_messages,
-- reminder_preferences, audit_log, gcal_events NO tienen RLS porque:
--   - users: Los pacientes son compartidos entre proveedores
--   - specialties: Son catálogo global
--   - conversation_states: Pertenecen al paciente (chat_id)
--   - outbox_messages: Pertenecen al paciente
--   - audit_log: Solo accesible por admin
-- ─────────────────────────────────────────────────────────────────────────────

COMMIT;
