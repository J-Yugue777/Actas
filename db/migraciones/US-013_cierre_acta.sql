-- US-013 · Cierre del acta: firma de cada participante, fecha exacta de cierre y PDF
-- Ejecutar en pgAdmin (Query Tool) sobre la base de datos de Actas.
-- Es seguro correrlo más de una vez.
--
-- Requiere US-012 (acta_adjuntos) y US-020 (aporte de cada participante).
--
-- 1. acta_participantes.firmado_en: cuándo firmó (aprobó) cada participante su aporte.
-- 2. actas.cerrado_en, cerrado_por, pdf_archivo y pdf_sha256: cierre y PDF guardado.
-- 3. Bloqueo en la base de datos (además del que hace la app): con el acta cerrada,
--    todo INSERT, UPDATE o DELETE en actas, acta_items, acta_participantes,
--    acta_adjuntos y acta_compromisos falla con el error 55000.
--    Única excepción: en acta_compromisos se puede marcar `completado` (seguimiento
--    del compromiso) sin tocar la actividad, la fecha ni el responsable.
--
-- Reabrir un acta cerrada está fuera del alcance: requeriría desactivar a mano el
-- trigger trg_actas_bloqueo_cierre (ALTER TABLE actas DISABLE TRIGGER ...) con
-- permisos de dueño de la tabla, y volver a generar el PDF.

BEGIN;

ALTER TABLE acta_participantes ADD COLUMN IF NOT EXISTS firmado_en TIMESTAMPTZ;

ALTER TABLE actas ADD COLUMN IF NOT EXISTS cerrado_en  TIMESTAMPTZ;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS cerrado_por INTEGER;
ALTER TABLE actas ADD COLUMN IF NOT EXISTS pdf_archivo VARCHAR(80);  -- nombre aleatorio en disco
ALTER TABLE actas ADD COLUMN IF NOT EXISTS pdf_sha256  CHAR(64);

-- Restricciones con nombre fijo: se pueden volver a crear sin duplicarlas
ALTER TABLE actas DROP CONSTRAINT IF EXISTS fk_actas_cerrado_por;
ALTER TABLE actas ADD CONSTRAINT fk_actas_cerrado_por
    FOREIGN KEY (cerrado_por) REFERENCES usuarios(id);

ALTER TABLE actas DROP CONSTRAINT IF EXISTS uq_actas_pdf_archivo;
ALTER TABLE actas ADD CONSTRAINT uq_actas_pdf_archivo UNIQUE (pdf_archivo);

-- Toda acta que se cierre desde ahora guarda la fecha exacta. NOT VALID: no revisa
-- actas viejas que ya estuvieran cerradas sin fecha.
ALTER TABLE actas DROP CONSTRAINT IF EXISTS ck_actas_cerrada_con_fecha;
ALTER TABLE actas ADD CONSTRAINT ck_actas_cerrada_con_fecha
    CHECK (estado <> 'cerrada' OR cerrado_en IS NOT NULL) NOT VALID;

-- Tablas hijas del acta. El FOR SHARE hace que una escritura que llega mientras el
-- acta se está cerrando (el cierre la tiene con FOR UPDATE) espere a que el cierre
-- termine y vea el estado nuevo: nada se cuela entre la revisión de firmas y el COMMIT.
CREATE OR REPLACE FUNCTION fn_bloquear_hijos_acta_cerrada() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_actas  INTEGER[];
    v_acta   INTEGER;
    v_estado TEXT;
BEGIN
    IF TG_TABLE_NAME = 'acta_compromisos' AND TG_OP = 'UPDATE'
       AND to_jsonb(NEW) - 'completado' = to_jsonb(OLD) - 'completado' THEN
        RETURN NEW;  -- solo cambió `completado`: el contenido del acta sigue igual
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_actas := ARRAY[NEW.acta_id];
    ELSIF TG_OP = 'DELETE' THEN
        v_actas := ARRAY[OLD.acta_id];
    ELSIF OLD.acta_id = NEW.acta_id THEN
        v_actas := ARRAY[NEW.acta_id];
    ELSE
        v_actas := ARRAY[OLD.acta_id, NEW.acta_id];  -- la fila se pasa a otra acta
    END IF;

    FOREACH v_acta IN ARRAY v_actas LOOP
        SELECT estado INTO v_estado FROM actas WHERE id = v_acta FOR SHARE;
        IF v_estado = 'cerrada' THEN
            RAISE EXCEPTION 'El acta % está cerrada: ya no se puede modificar (%).', v_acta, TG_TABLE_NAME
                USING ERRCODE = '55000', HINT = 'Un acta cerrada es de solo lectura.';
        END IF;
    END LOOP;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- El acta misma: cerrada no se cambia ni se borra (el cierre sí pasa, porque OLD sigue abierta)
CREATE OR REPLACE FUNCTION fn_bloquear_acta_cerrada() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.estado = 'cerrada' THEN
        RAISE EXCEPTION 'El acta % está cerrada: ya no se puede modificar ni borrar.', OLD.id
            USING ERRCODE = '55000', HINT = 'Un acta cerrada es de solo lectura.';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_actas_bloqueo_cierre ON actas;
CREATE TRIGGER trg_actas_bloqueo_cierre
    BEFORE UPDATE OR DELETE ON actas
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_acta_cerrada();

DROP TRIGGER IF EXISTS trg_acta_items_bloqueo_cierre ON acta_items;
CREATE TRIGGER trg_acta_items_bloqueo_cierre
    BEFORE INSERT OR UPDATE OR DELETE ON acta_items
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_hijos_acta_cerrada();

DROP TRIGGER IF EXISTS trg_acta_participantes_bloqueo_cierre ON acta_participantes;
CREATE TRIGGER trg_acta_participantes_bloqueo_cierre
    BEFORE INSERT OR UPDATE OR DELETE ON acta_participantes
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_hijos_acta_cerrada();

DROP TRIGGER IF EXISTS trg_acta_adjuntos_bloqueo_cierre ON acta_adjuntos;
CREATE TRIGGER trg_acta_adjuntos_bloqueo_cierre
    BEFORE INSERT OR UPDATE OR DELETE ON acta_adjuntos
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_hijos_acta_cerrada();

-- acta_compromisos puede no existir todavía en algunas bases
DO $$
BEGIN
    IF to_regclass('acta_compromisos') IS NOT NULL THEN
        DROP TRIGGER IF EXISTS trg_acta_compromisos_bloqueo_cierre ON acta_compromisos;
        CREATE TRIGGER trg_acta_compromisos_bloqueo_cierre
            BEFORE INSERT OR UPDATE OR DELETE ON acta_compromisos
            FOR EACH ROW EXECUTE FUNCTION fn_bloquear_hijos_acta_cerrada();
    END IF;
END;
$$;

COMMENT ON COLUMN acta_participantes.firmado_en IS
    'US-013: cuándo el participante firmó (aprobó) su aporte. Se anula si cambia el aporte.';
COMMENT ON COLUMN actas.cerrado_en IS 'US-013: fecha y hora exactas del cierre.';
COMMENT ON COLUMN actas.cerrado_por IS 'US-013: quién cerró el acta (su líder).';
COMMENT ON COLUMN actas.pdf_archivo IS
    'US-013: nombre aleatorio del PDF en la carpeta de subidas (UPLOAD_DIR).';
COMMENT ON COLUMN actas.pdf_sha256 IS 'US-013: huella SHA-256 del PDF generado al cerrar.';

COMMIT;
