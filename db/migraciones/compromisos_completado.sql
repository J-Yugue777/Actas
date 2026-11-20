-- Compromisos · marca de completado y registrado_por opcional
-- Ejecutar en pgAdmin (Query Tool) sobre la base de datos de Actas.
-- Es seguro correrlo más de una vez.

-- La sección Compromisos filtra por pendiente / completado
ALTER TABLE acta_compromisos ADD COLUMN IF NOT EXISTS completado BOOLEAN NOT NULL DEFAULT FALSE;

-- El aplicativo guarda quién registró el compromiso en creado_por (US-013).
-- Si la base tiene registrado_por obligatorio, agregar un compromiso falla.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'acta_compromisos' AND column_name = 'registrado_por') THEN
        ALTER TABLE acta_compromisos ALTER COLUMN registrado_por DROP NOT NULL;
    END IF;
END $$;
