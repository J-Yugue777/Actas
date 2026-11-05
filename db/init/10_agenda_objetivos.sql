-- US-006 · Agenda y objetivos del acta (RF-006, RN-006, RN-012)
-- El líder del acta puede agregar tantos puntos de agenda y objetivos como necesite.

-- TEMPORAL: tabla mínima para poder probar US-006 mientras no exista US-004
-- (Creación del acta). Cuando la tabla real `actas` esté en el repo, borra este
-- bloque; solo se necesita que tenga `id` y la columna del líder (`lider_id`).
CREATE TABLE IF NOT EXISTS actas (
    id       SERIAL PRIMARY KEY,
    lider_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS acta_items (
    id          SERIAL PRIMARY KEY,
    acta_id     INTEGER NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
    tipo        VARCHAR(10) NOT NULL CHECK (tipo IN ('agenda', 'objetivo')),
    descripcion VARCHAR(500) NOT NULL CHECK (length(btrim(descripcion)) > 0),
    orden       INTEGER NOT NULL,
    creado_en   TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (acta_id, tipo, orden) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_acta_items_acta ON acta_items (acta_id, tipo, orden);
