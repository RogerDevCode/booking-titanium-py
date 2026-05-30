-- ============================================================================
-- TITANIUM BOOKING ENGINE — DATOS SEMILLA
-- Archivo: db/migrations/004_seed.sql
-- Propósito: Datos iniciales mínimos para arrancar el sistema.
-- ============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Especialidades médicas base
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO specialties (name, description) VALUES
    ('Medicina General', 'Consultas médicas generales y chequeos preventivos'),
    ('Odontología', 'Atención dental, limpieza, ortodoncia y cirugía oral'),
    ('Dermatología', 'Diagnóstico y tratamiento de enfermedades de la piel'),
    ('Cardiología', 'Evaluación y tratamiento de enfermedades cardiovasculares'),
    ('Pediatría', 'Atención médica integral para niños y adolescentes'),
    ('Ginecología', 'Salud femenina, control prenatal y ginecología general'),
    ('Traumatología', 'Lesiones musculoesqueléticas, fracturas y rehabilitación'),
    ('Oftalmología', 'Diagnóstico y tratamiento de enfermedades oculares'),
    ('Nutrición', 'Planificación alimentaria y tratamiento de trastornos nutricionales'),
    ('Psicología', 'Evaluación y terapia psicológica');

-- ─────────────────────────────────────────────────────────────────────────────
-- Proveedor demo (para desarrollo)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO providers (name, specialty_id, bio, slot_duration_minutes, buffer_time_minutes, notice_period_hours)
VALUES (
    'Dra. María González',
    (SELECT id FROM specialties WHERE name = 'Medicina General'),
    'Médico general con 15 años de experiencia. Especialista en medicina preventiva.',
    30, 5, 4
);

INSERT INTO providers (name, specialty_id, bio, slot_duration_minutes, buffer_time_minutes, notice_period_hours)
VALUES (
    'Dr. Carlos Pérez',
    (SELECT id FROM specialties WHERE name = 'Odontología'),
    'Odontólogo certificado. Especialidad en endodoncia y ortodoncia.',
    45, 10, 4
);

INSERT INTO providers (name, specialty_id, bio, slot_duration_minutes, buffer_time_minutes, notice_period_hours)
VALUES (
    'Dra. Ana Muñoz',
    (SELECT id FROM specialties WHERE name = 'Dermatología'),
    'Dermatóloga con subespecialidad en dermatología estética.',
    30, 5, 4
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Horarios de la Dra. González (Lunes a Viernes 09:00-13:00, 14:30-18:00)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO provider_schedules (provider_id, day_of_week, start_time, end_time)
SELECT p.id, d.dow, t.st, t.et
  FROM providers p
 CROSS JOIN (VALUES (0),(1),(2),(3),(4)) AS d(dow)
 CROSS JOIN (VALUES ('09:00'::TIME, '13:00'::TIME), ('14:30'::TIME, '18:00'::TIME)) AS t(st, et)
 WHERE p.name = 'Dra. María González';

-- ─────────────────────────────────────────────────────────────────────────────
-- Horarios del Dr. Pérez (Lunes, Miércoles, Viernes 08:00-14:00)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO provider_schedules (provider_id, day_of_week, start_time, end_time)
SELECT p.id, d.dow, '08:00'::TIME, '14:00'::TIME
  FROM providers p
 CROSS JOIN (VALUES (0),(2),(4)) AS d(dow)
 WHERE p.name = 'Dr. Carlos Pérez';

-- ─────────────────────────────────────────────────────────────────────────────
-- Horarios de la Dra. Muñoz (Martes y Jueves 10:00-17:00)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO provider_schedules (provider_id, day_of_week, start_time, end_time)
SELECT p.id, d.dow, '10:00'::TIME, '17:00'::TIME
  FROM providers p
 CROSS JOIN (VALUES (1),(3)) AS d(dow)
 WHERE p.name = 'Dra. Ana Muñoz';

-- ─────────────────────────────────────────────────────────────────────────────
-- Base de conocimiento demo (FAQ)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO knowledge_base (title, category, content) VALUES
    ('Horarios de atención', 'General',
     'La clínica atiende de lunes a viernes de 08:00 a 18:00 horas. Los sábados de 09:00 a 13:00.'),
    ('Política de cancelación', 'General',
     'Puedes cancelar tu hora hasta 4 horas antes sin penalización. Después de ese plazo, la cancelación cuenta como inasistencia.'),
    ('Documentos necesarios', 'General',
     'Para tu primera consulta necesitas tu cédula de identidad o pasaporte vigente y tu previsión de salud (Fonasa o Isapre).'),
    ('Medios de pago', 'General',
     'Aceptamos efectivo, tarjetas de crédito y débito (Visa, Mastercard, Redcompra), y transferencias bancarias.'),
    ('Preparación para exámenes', 'Salud',
     'Para exámenes de sangre debes acudir en ayuno de al menos 8 horas. Solo puedes tomar agua. Consulta con tu médico sobre suspender medicamentos.');

COMMIT;
