-- US-013 · Aporte del participante, compromisos y firma
-- Ejecutar en pgAdmin (Query Tool) sobre la base de datos de Actas.
-- Es seguro correrlo más de una vez.

-- Aporte de cada participante (si ya existen estas columnas no hace nada)
ALTER TABLE acta_participantes ADD COLUMN IF NOT EXISTS desarrollo    TEXT;
ALTER TABLE acta_participantes ADD COLUMN IF NOT EXISTS conclusiones  TEXT;

-- Firma de cada persona: nombre aleatorio del archivo en disco
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS firma_archivo VARCHAR(80);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS firma_mime    VARCHAR(100);

-- Compromisos: quién los registró (su firma acompaña el compromiso)
ALTER TABLE acta_compromisos ADD COLUMN IF NOT EXISTS creado_por INTEGER REFERENCES usuarios(id);
