-- US-020 · Textos largos en el aporte de cada participante (desarrollo y conclusiones)
-- Ejecutar en pgAdmin (Query Tool) sobre la base de datos de Actas.
-- Es seguro correrlo más de una vez.
--
-- Límite real: 50.000 caracteres por campo (unas 15 páginas). Es el mismo número
-- que MAX_LARGO_APORTE en aportes.py: si cambias uno, cambia el otro.
-- Sirve si las columnas no existen, si existen como VARCHAR(n) o si ya son TEXT.

BEGIN;

ALTER TABLE acta_participantes ADD COLUMN IF NOT EXISTS desarrollo            TEXT;
ALTER TABLE acta_participantes ADD COLUMN IF NOT EXISTS conclusiones          TEXT;
ALTER TABLE acta_participantes ADD COLUMN IF NOT EXISTS aporte_actualizado_en TIMESTAMPTZ;

-- VARCHAR(n) -> TEXT no pierde datos ni reescribe la tabla
ALTER TABLE acta_participantes ALTER COLUMN desarrollo   TYPE TEXT;
ALTER TABLE acta_participantes ALTER COLUMN conclusiones TYPE TEXT;

-- char_length cuenta caracteres (una tilde o un emoji valen 1), igual que len() en Python
ALTER TABLE acta_participantes DROP CONSTRAINT IF EXISTS ck_acta_participantes_desarrollo_largo;
ALTER TABLE acta_participantes ADD CONSTRAINT ck_acta_participantes_desarrollo_largo
    CHECK (desarrollo IS NULL OR char_length(desarrollo) <= 50000);

ALTER TABLE acta_participantes DROP CONSTRAINT IF EXISTS ck_acta_participantes_conclusiones_largo;
ALTER TABLE acta_participantes ADD CONSTRAINT ck_acta_participantes_conclusiones_largo
    CHECK (conclusiones IS NULL OR char_length(conclusiones) <= 50000);

COMMENT ON COLUMN acta_participantes.desarrollo IS
    'US-020: relato de la reunión del participante. Máximo 50.000 caracteres (aportes.MAX_LARGO_APORTE).';
COMMENT ON COLUMN acta_participantes.conclusiones IS
    'US-020: conclusiones del participante. Máximo 50.000 caracteres (aportes.MAX_LARGO_APORTE).';
COMMENT ON COLUMN acta_participantes.aporte_actualizado_en IS
    'US-020: última vez que el participante guardó su aporte.';

COMMIT;
