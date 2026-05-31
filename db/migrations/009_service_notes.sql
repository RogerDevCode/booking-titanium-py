-- Archivo: db/migrations/009_service_notes.sql

CREATE TABLE IF NOT EXISTS tags (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    color VARCHAR(7) NOT NULL DEFAULT '#757575',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_notes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    booking_id BIGINT REFERENCES bookings(id) ON DELETE SET NULL,
    client_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    provider_id BIGINT REFERENCES providers(id) ON DELETE CASCADE,
    content_encrypted TEXT NOT NULL,
    encryption_version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id BIGINT REFERENCES service_notes(id) ON DELETE CASCADE,
    tag_id BIGINT REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
);

-- Row Level Security (RLS) Isolation
ALTER TABLE service_notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY service_notes_isolation ON service_notes
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
