-- ============================================================================
-- TITANIUM BOOKING ENGINE — PROVIDER NO-SHOW CONFIGURATION
-- Archivo: db/migrations/007_provider_noshow_config.sql
-- Propósito: Añadir columnas a la tabla de proveedores para configurar límites de no-shows.
-- ============================================================================

BEGIN;

ALTER TABLE providers
ADD COLUMN IF NOT EXISTS max_noshows_warning INT NOT NULL DEFAULT 3,
ADD COLUMN IF NOT EXISTS max_noshows_block INT NOT NULL DEFAULT 5,
ADD COLUMN IF NOT EXISTS noshow_block_days INT NOT NULL DEFAULT 30;

COMMIT;
