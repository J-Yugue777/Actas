-- =====================================================================
-- BASE DE DATOS COMPLETA · Aplicativo de Actas SENA (PostgreSQL)
-- Versión final: usuarios con dirección y teléfono, roles con permiso
-- para crear actas, estructura académica, actas y aportes.
--
-- Úsalo para crear la base DESDE CERO (por ejemplo, en una base nueva).
-- Si ya tienes datos, NO lo ejecutes sobre ella: usa los archivos de
-- db/migraciones/.
--
-- Docker lo corre solo la primera vez (docker compose up). En pgAdmin:
-- ábrelo en el Query Tool de la base "actas" y ejecútalo; después corre
-- 02_datos_demo.sql (usuarios para entrar) y los archivos de db/migraciones/.
-- =====================================================================

-- ---------------------------------------------------------------------
-- (Opcional) Borrar todo para empezar de cero.
-- ¡CUIDADO! Elimina todos los datos. Quita los "--" solo si lo necesitas.
-- ---------------------------------------------------------------------
-- DROP TABLE IF EXISTS acta_adjuntos, acta_anexos, acta_compromisos, acta_participantes,
--     acta_items, actas, centros_formacion, regionales, equipo_integrantes,
--     equipo_ficha, equipos_ejecutores, fichas, programas, usuarios, roles CASCADE;

BEGIN;

-- =====================================================================
-- 1. ROLES Y USUARIOS
-- =====================================================================
CREATE TABLE roles (
    id               SERIAL PRIMARY KEY,
    nombre           VARCHAR(80) UNIQUE NOT NULL,
    puede_crear_acta BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE usuarios (
    id               SERIAL PRIMARY KEY,
    nombre           VARCHAR(150) NOT NULL,
    apellido         VARCHAR(150) NOT NULL,
    tipo_documento   VARCHAR(20)  NOT NULL,              -- CC, CE, TI, etc.
    fecha_nacimiento DATE         NOT NULL,
    correo           VARCHAR(150) UNIQUE NOT NULL,       -- UNIQUE evita duplicados
    password_hash    VARCHAR(255),
    tipo_vinculacion VARCHAR(30),                        -- carrera administrativa, provisional, contratista (RN-001)
    direccion        VARCHAR(200),
    telefono         VARCHAR(20),
    rol_id           INT NOT NULL REFERENCES roles(id),  -- NOT NULL cumple RN-003
    activo           BOOLEAN DEFAULT TRUE
);

INSERT INTO roles (nombre, puede_crear_acta) VALUES
    ('Administrador',                                       TRUE),
    ('Instructor líder de ficha',                           TRUE),
    ('Coordinador académico',                               TRUE),
    ('Instructor',                                          FALSE),
    ('Coordinador de Formación',                            TRUE),
    ('Agente de Gestión de Administración Educativa (GAE)', TRUE),
    ('Bienestar de Centro',                                 TRUE),
    ('Coordinador Misional',                                TRUE),
    ('Asesor Emprendedor',                                  TRUE),
    ('Líder de Producción de Centros',                      TRUE);

-- =====================================================================
-- 2. ESTRUCTURA ACADÉMICA (modelo entidad-relación)
--    Programas 1..N Fichas | Fichas 1..N Equipo/ficha
--    Equipos ejecutores 1..N Equipo/ficha | Equipos ejecutores 1..N Usuarios
-- =====================================================================
CREATE TABLE programas (
    id     SERIAL PRIMARY KEY,
    codigo VARCHAR(20),
    nombre VARCHAR(200) NOT NULL
);

CREATE TABLE fichas (
    id          SERIAL PRIMARY KEY,
    numero      VARCHAR(20) UNIQUE NOT NULL,             -- ejemplo: 3210115
    programa_id INT NOT NULL REFERENCES programas(id),
    activa      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE equipos_ejecutores (
    id     SERIAL PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE equipo_ficha (
    id                 SERIAL PRIMARY KEY,
    equipo_ejecutor_id INT NOT NULL REFERENCES equipos_ejecutores(id),
    ficha_id           INT NOT NULL REFERENCES fichas(id),
    UNIQUE (equipo_ejecutor_id, ficha_id)
);

-- Usuarios de un equipo ejecutor, con su rol EN ESE EQUIPO.
-- Aquí se define quién es "Instructor líder de ficha" y quién solo "Instructor".
CREATE TABLE equipo_integrantes (
    id                 SERIAL PRIMARY KEY,
    equipo_ejecutor_id INT NOT NULL REFERENCES equipos_ejecutores(id),
    usuario_id         INT NOT NULL REFERENCES usuarios(id),
    rol_id             INT NOT NULL REFERENCES roles(id),
    UNIQUE (equipo_ejecutor_id, usuario_id)
);

-- =====================================================================
-- 3. REGIONALES Y CENTROS (listas desplegables dependientes)
-- =====================================================================
CREATE TABLE regionales (
    id     SERIAL PRIMARY KEY,
    nombre VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE centros_formacion (
    id          SERIAL PRIMARY KEY,
    regional_id INT NOT NULL REFERENCES regionales(id),
    nombre      VARCHAR(200) NOT NULL,
    UNIQUE (regional_id, nombre)
);

INSERT INTO regionales (nombre) VALUES
    ('Amazonas'), ('Antioquia'), ('Arauca'), ('Atlántico'), ('Bolívar'), ('Boyacá'),
    ('Caldas'), ('Caquetá'), ('Casanare'), ('Cauca'), ('Cesar'), ('Chocó'), ('Córdoba'),
    ('Cundinamarca'), ('Distrito Capital'), ('Guainía'), ('Guaviare'), ('Huila'),
    ('La Guajira'), ('Magdalena'), ('Meta'), ('Nariño'), ('Norte de Santander'),
    ('Putumayo'), ('Quindío'), ('Risaralda'), ('San Andrés y Providencia'), ('Santander'),
    ('Sucre'), ('Tolima'), ('Valle del Cauca'), ('Vaupés'), ('Vichada');

-- Un centro de ejemplo; carga aquí el resto de centros reales.
INSERT INTO centros_formacion (regional_id, nombre)
SELECT id, 'Centro de Biotecnología Industrial'
FROM regionales WHERE nombre = 'Valle del Cauca';

-- =====================================================================
-- 4. ACTAS
-- =====================================================================
CREATE TABLE actas (
    id             SERIAL PRIMARY KEY,
    tipo_acta      VARCHAR(20) NOT NULL CHECK (tipo_acta IN ('equipo_ejecutor', 'otros_asuntos')),
    consecutivo    INT NOT NULL,
    anio           SMALLINT NOT NULL,
    numero_acta    VARCHAR(40) NOT NULL,                  -- ejemplo: Acta 1
    nombre_reunion VARCHAR(200) NOT NULL,
    ciudad         VARCHAR(100) NOT NULL,
    fecha_reunion  DATE NOT NULL,
    hora_inicio    TIME NOT NULL,
    hora_fin       TIME NOT NULL,
    lugar_enlace   VARCHAR(300) NOT NULL,
    regional_id    INT NOT NULL REFERENCES regionales(id),
    centro_id      INT NOT NULL REFERENCES centros_formacion(id),
    ficha_id       INT REFERENCES fichas(id),             -- solo actas de equipo ejecutor
    mes            SMALLINT CHECK (mes BETWEEN 1 AND 12), -- solo actas de equipo ejecutor
    codigo_formato VARCHAR(30),                           -- ejemplo: GOR-F-084 v2
    estado         VARCHAR(10) NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'cerrada')),
    lider_id       INT NOT NULL REFERENCES usuarios(id),  -- quien crea el acta es su líder
    creada_en      TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (hora_fin > hora_inicio),                       -- VAL-008
    CHECK (tipo_acta <> 'equipo_ejecutor' OR (ficha_id IS NOT NULL AND mes IS NOT NULL))
);

-- Una sola acta de equipo ejecutor por ficha y mes
CREATE UNIQUE INDEX uq_acta_ficha_mes
    ON actas (ficha_id, anio, mes) WHERE tipo_acta = 'equipo_ejecutor';

-- El consecutivo no se repite dentro de centro + ficha + año
CREATE UNIQUE INDEX uq_acta_consecutivo
    ON actas (centro_id, COALESCE(ficha_id, 0), anio, consecutivo);

-- Agenda y objetivos (listas de textos 1..n) · US-006
CREATE TABLE acta_items (
    id          SERIAL PRIMARY KEY,
    acta_id     INT NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
    tipo        VARCHAR(10) NOT NULL CHECK (tipo IN ('agenda', 'objetivo')),
    descripcion VARCHAR(500) NOT NULL,
    orden       INT NOT NULL
);

-- =====================================================================
-- 5. APORTES DE LOS PARTICIPANTES (incluye a quien creó el acta)
-- =====================================================================
CREATE TABLE acta_participantes (
    id            SERIAL PRIMARY KEY,
    acta_id       INT NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
    usuario_id    INT NOT NULL REFERENCES usuarios(id),
    desarrollo    TEXT,
    conclusiones  TEXT,
    dependencia   VARCHAR(150),
    aprueba       BOOLEAN,
    observaciones TEXT,
    firma         TEXT,                                   -- ruta de la imagen de la firma
    UNIQUE (acta_id, usuario_id)
);

CREATE TABLE acta_compromisos (
    id                SERIAL PRIMARY KEY,
    acta_id           INT NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
    registrado_por    INT NOT NULL REFERENCES usuarios(id),
    actividad         TEXT NOT NULL,
    fecha_entrega     DATE NOT NULL,
    responsable_id    INT REFERENCES usuarios(id),
    responsable_texto VARCHAR(150),
    firma             TEXT,
    CHECK (responsable_id IS NOT NULL OR responsable_texto IS NOT NULL)
);

CREATE TABLE acta_anexos (
    id             SERIAL PRIMARY KEY,
    acta_id        INT NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
    subido_por     INT NOT NULL REFERENCES usuarios(id),
    nombre_archivo VARCHAR(255) NOT NULL,
    ruta           TEXT NOT NULL,
    subido_en      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =====================================================================
-- 6. CAMBIOS POSTERIORES. También están en db/migraciones/; van aquí para que
--    una base nueva funcione aunque no se corran las migraciones.
--    En una base que ya existía, corre los archivos de db/migraciones/.
-- =====================================================================

-- US-012 · Adjuntos del acta (fotos y documentos de soporte)
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

-- US-013 · Firma de cada persona y quién registró cada compromiso
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS firma_archivo VARCHAR(80);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS firma_mime    VARCHAR(100);
ALTER TABLE acta_compromisos ADD COLUMN IF NOT EXISTS creado_por INTEGER REFERENCES usuarios(id);

-- Compromisos: marca de completado (sección Compromisos). El aplicativo guarda
-- quién registró el compromiso en creado_por, así que registrado_por es opcional.
ALTER TABLE acta_compromisos ADD COLUMN IF NOT EXISTS completado BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE acta_compromisos ALTER COLUMN registrado_por DROP NOT NULL;

COMMIT;
