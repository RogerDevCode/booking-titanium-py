-- ============================================================================
-- TITANIUM BOOKING ENGINE — MIGRACIÓN GCAL PROVIDERS
-- Archivo: db/migrations/005_provider_gcal.sql
-- Propósito: Añadir campos de sincronización con Google Calendar a proveedores.
-- ============================================================================

ALTER TABLE providers
    ADD COLUMN gcal_calendar_id      TEXT,
    ADD COLUMN gcal_access_token     TEXT,
    ADD COLUMN gcal_refresh_token    TEXT,
    ADD COLUMN gcal_client_id        TEXT,
    ADD COLUMN gcal_client_secret    TEXT;
