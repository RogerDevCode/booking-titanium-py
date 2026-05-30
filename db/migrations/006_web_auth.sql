-- ============================================================================
-- TITANIUM BOOKING ENGINE — WEB AUTHENTICATION SCHEMA
-- Archivo: db/migrations/006_web_auth.sql
-- Propósito: Tabla de credenciales administrativas y de proveedores para el panel.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS web_users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(50) NOT NULL CHECK (role IN ('admin', 'provider')),
    provider_id   BIGINT REFERENCES providers(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed defaults (only if they do not exist)
INSERT INTO web_users (email, password_hash, role, provider_id)
VALUES (
    'admin@titanium.com',
    '0777f136a76d33b59aa69e3854944738:3871476b33bf2e8df29787e8fa0518902d19d99d18bfb7efb713b6cbf37cdb6ec15780e472c7609ec7070178c6013f82703299f844ee07036440a190f2d85826',
    'admin',
    NULL
) ON CONFLICT (email) DO NOTHING;

INSERT INTO web_users (email, password_hash, role, provider_id)
VALUES (
    'doctor@titanium.com',
    'b9d8626c46e3f26e3ed6e430aeeecd5f:a3421c26b0f15e9b67aec09c473bfbe6d3c2fb0abc7b1d9258b79f769114a456c845b196453d56f8bea97f2dd420d917af4fc424c1d726051a6efa262426da35',
    'provider',
    (SELECT id FROM providers WHERE name = 'Dra. María González' LIMIT 1)
) ON CONFLICT (email) DO NOTHING;

COMMIT;
