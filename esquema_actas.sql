-- Esquema reconstruido a partir de las consultas del código (app.py, actas.py,
-- aportes.py, adjuntos.py, secciones.py, pdf_acta.py, db.py).
-- Es seguro correrlo más de una vez: solo crea lo que no existe.
-- No toca los datos de las tablas `usuarios` y `roles` que ya tienes.

-- ---------------------------------------------------------------- roles / usuarios
ALTER TABLE roles    ADD COLUMN IF NOT EXISTS puede_crear_acta BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefono  VARCHAR(30);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS direccion VARCHAR(200);

-- ---------------------------------------------------------------- catálogos
CREATE TABLE IF NOT EXISTS regionales (
    id     SERIAL PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS centros_formacion (
    id          SERIAL PRIMARY KEY,
    regional_id INTEGER      NOT NULL REFERENCES regionales(id),
    nombre      VARCHAR(160) NOT NULL,
    UNIQUE (regional_id, nombre)
);

CREATE TABLE IF NOT EXISTS programas (
    id     SERIAL PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS fichas (
    id          SERIAL PRIMARY KEY,
    numero      VARCHAR(20) NOT NULL UNIQUE,
    programa_id INTEGER     NOT NULL REFERENCES programas(id),
    activa      BOOLEAN     NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------- equipos ejecutores
CREATE TABLE IF NOT EXISTS equipos_ejecutores (
    id     SERIAL PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL
);

CREATE TABLE IF NOT EXISTS equipo_ficha (
    equipo_ejecutor_id INTEGER NOT NULL REFERENCES equipos_ejecutores(id) ON DELETE CASCADE,
    ficha_id           INTEGER NOT NULL REFERENCES fichas(id)             ON DELETE CASCADE,
    PRIMARY KEY (equipo_ejecutor_id, ficha_id)
);

CREATE TABLE IF NOT EXISTS equipo_integrantes (
    equipo_ejecutor_id INTEGER NOT NULL REFERENCES equipos_ejecutores(id) ON DELETE CASCADE,
    usuario_id         INTEGER NOT NULL REFERENCES usuarios(id),
    rol_id             INTEGER NOT NULL REFERENCES roles(id),
    PRIMARY KEY (equipo_ejecutor_id, usuario_id)
);

-- ---------------------------------------------------------------- actas
CREATE TABLE IF NOT EXISTS actas (
    id             SERIAL PRIMARY KEY,
    tipo_acta      VARCHAR(20)  NOT NULL CHECK (tipo_acta IN ('equipo_ejecutor', 'otros_asuntos')),
    consecutivo    INTEGER      NOT NULL,
    anio           INTEGER      NOT NULL,
    numero_acta    VARCHAR(40)  NOT NULL,
    nombre_reunion VARCHAR(200) NOT NULL,
    ciudad         VARCHAR(100),
    fecha_reunion  DATE         NOT NULL,
    hora_inicio    TIME,
    hora_fin       TIME,
    lugar_enlace   VARCHAR(300),
    regional_id    INTEGER      NOT NULL REFERENCES regionales(id),
    centro_id      INTEGER      NOT NULL REFERENCES centros_formacion(id),
    ficha_id       INTEGER      REFERENCES fichas(id),
    mes            INTEGER      CHECK (mes BETWEEN 1 AND 12),
    codigo_formato VARCHAR(40),
    lider_id       INTEGER      NOT NULL REFERENCES usuarios(id),
    estado         VARCHAR(10)  NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'cerrada')),
    creado_en      TIMESTAMP    NOT NULL DEFAULT now()
);

-- Si la tabla `actas` ya existía en versión mínima (solo id y lider_id), completa lo que falte
ALTER TABLE actas ADD COLUMN IF NOT EXISTS tipo_acta      VARCHAR(20);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS consecutivo    INTEGER;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS anio           INTEGER;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS numero_acta    VARCHAR(40);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS nombre_reunion VARCHAR(200);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS ciudad         VARCHAR(100);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS fecha_reunion  DATE;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS hora_inicio    TIME;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS hora_fin       TIME;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS lugar_enlace   VARCHAR(300);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS regional_id    INTEGER REFERENCES regionales(id);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS centro_id      INTEGER REFERENCES centros_formacion(id);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS ficha_id       INTEGER REFERENCES fichas(id);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS mes            INTEGER;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS codigo_formato VARCHAR(40);
ALTER TABLE actas ADD COLUMN IF NOT EXISTS estado         VARCHAR(10) NOT NULL DEFAULT 'abierta';
ALTER TABLE actas ADD COLUMN IF NOT EXISTS creado_en      TIMESTAMP   NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_actas_lider ON actas (lider_id);
CREATE INDEX IF NOT EXISTS idx_actas_ficha ON actas (ficha_id, anio, mes);

-- ---------------------------------------------------------------- partes del acta
CREATE TABLE IF NOT EXISTS acta_items (
    id          SERIAL PRIMARY KEY,
    acta_id     INTEGER      NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
    tipo        VARCHAR(10)  NOT NULL CHECK (tipo IN ('agenda', 'objetivo')),
    descripcion VARCHAR(500) NOT NULL CHECK (length(btrim(descripcion)) > 0),
    orden       INTEGER      NOT NULL,
    creado_en   TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (acta_id, tipo, orden) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS idx_acta_items_acta ON acta_items (acta_id, tipo, orden);

CREATE TABLE IF NOT EXISTS acta_participantes (
    acta_id       INTEGER NOT NULL REFERENCES actas(id)    ON DELETE CASCADE,
    usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
    desarrollo    TEXT,
    conclusiones  TEXT,
    PRIMARY KEY (acta_id, usuario_id)
);

CREATE TABLE IF NOT EXISTS acta_compromisos (
    id                SERIAL PRIMARY KEY,
    acta_id           INTEGER      NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
    actividad         VARCHAR(500) NOT NULL,
    fecha_entrega     DATE         NOT NULL,
    responsable_id    INTEGER      REFERENCES usuarios(id),
    responsable_texto VARCHAR(200),
    completado        BOOLEAN      NOT NULL DEFAULT FALSE,
    creado_por        INTEGER      REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS idx_acta_compromisos_acta ON acta_compromisos (acta_id);