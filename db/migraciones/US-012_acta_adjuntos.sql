-- US-012 · Adjuntos del acta (fotos y documentos de soporte)
-- Ejecutar en pgAdmin (Query Tool) sobre la base de datos de Actas.
-- Es seguro correrlo más de una vez.

CREATE TABLE IF NOT EXISTS acta_adjuntos (
    id              SERIAL PRIMARY KEY,
    acta_id         INTEGER      NOT NULL REFERENCES actas(id)    ON DELETE CASCADE,
    usuario_id      INTEGER      NOT NULL REFERENCES usuarios(id),
    nombre_original VARCHAR(255) NOT NULL,           -- como lo subió la persona (solo para mostrar)
    nombre_archivo  VARCHAR(80)  NOT NULL UNIQUE,    -- nombre aleatorio en disco
    tipo_mime       VARCHAR(100) NOT NULL,
    tamano_bytes    INTEGER      NOT NULL CHECK (tamano_bytes > 0),
    es_imagen       BOOLEAN      NOT NULL DEFAULT FALSE,  -- las imágenes pueden ir dentro del PDF
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_acta_adjuntos_acta ON acta_adjuntos (acta_id);
