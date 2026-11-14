-- US-005 · Catálogo de direcciones regionales y centros de formación del SENA
-- Ejecutar en pgAdmin (Query Tool) sobre la base de datos de Actas.
-- Es seguro correrlo más de una vez.
--
-- OPCIONAL: el alcance geográfico real del aplicativo sigue en Temas abiertos.
-- Córrelo solo si el equipo decide cargar el catálogo nacional. No borra ni
-- cambia nada; solo agrega lo que falta:
--   * una regional, si no hay otra con el mismo nombre (sin distinguir
--     mayúsculas e ignorando el prefijo "Regional ": "Antioquia" cuenta
--     como "Regional Antioquia"). Las nuevas siguen la forma de las que ya
--     hay: si la mayoría va sin el prefijo ("Antioquia"), se agregan sin él
--     ("Arauca"); si la tabla está vacía o la mayoría lo usa, con él
--     ("Regional Arauca");
--   * un centro, si su regional no tiene ya uno con el mismo nombre (sin
--     distinguir mayúsculas). Hay nombres repetidos entre regionales
--     ("Centro de Comercio y Servicios"), por eso se compara regional + centro.
-- Las tildes sí cuentan, y si la base usa otro nombre para una regional
-- (p. ej. "Valle" en vez de "Valle del Cauca") quedarán las dos y los centros
-- que ya tenga se repetirán en la nueva. Revisa antes con
--   SELECT nombre FROM regionales ORDER BY nombre;
-- y renombra la que no coincida con el nombre oficial, p. ej.
--   UPDATE regionales SET nombre = 'Valle del Cauca' WHERE nombre = 'Valle';
-- Si la base tiene un UNIQUE solo sobre el nombre del centro, fallará por los
-- nombres repetidos y no se guardará nada (todo va en una transacción).
--
-- Fuente: Directorio de regionales del SENA
--   https://www.sena.edu.co/la-entidad/directorio-regionales?vista=lista
--   consultado el 2026-11-13: 33 regionales y 118 centros, con los nombres como
--   se publican allí. Cruzado con los datos abiertos del SENA en datos.gov.co
--   (conjunto vv8g-8u9u). Única corrección: el centro 9110 de Boyacá va como
--   "Centro de Desarrollo Agropecuario y Agroindustrial", como en datos.gov.co.

BEGIN;

INSERT INTO regionales (nombre)
SELECT CASE WHEN p.con_prefijo THEN v.nombre
            ELSE regexp_replace(v.nombre, '^Regional\s+', '') END
FROM (VALUES
    ('Regional Amazonas'),
    ('Regional Antioquia'),
    ('Regional Arauca'),
    ('Regional Atlántico'),
    ('Regional Bolívar'),
    ('Regional Boyacá'),
    ('Regional Caldas'),
    ('Regional Caquetá'),
    ('Regional Casanare'),
    ('Regional Cauca'),
    ('Regional Cesar'),
    ('Regional Chocó'),
    ('Regional Córdoba'),
    ('Regional Cundinamarca'),
    ('Regional Distrito Capital'),
    ('Regional Guainía'),
    ('Regional Guaviare'),
    ('Regional Huila'),
    ('Regional La Guajira'),
    ('Regional Magdalena'),
    ('Regional Meta'),
    ('Regional Nariño'),
    ('Regional Norte de Santander'),
    ('Regional Putumayo'),
    ('Regional Quindío'),
    ('Regional Risaralda'),
    ('Regional San Andrés'),
    ('Regional Santander'),
    ('Regional Sucre'),
    ('Regional Tolima'),
    ('Regional Valle del Cauca'),
    ('Regional Vaupés'),
    ('Regional Vichada')
) AS v (nombre)
-- Con "Regional " solo si la tabla está vacía o la mayoría de nombres ya lo trae
CROSS JOIN (
    SELECT count(*) FILTER (WHERE btrim(nombre) ~* '^regional\s') * 2 >= count(*) AS con_prefijo
    FROM regionales
) p
WHERE NOT EXISTS (
    SELECT 1 FROM regionales r
    WHERE lower(regexp_replace(btrim(r.nombre), '^regional\s+', '', 'i'))
        = lower(regexp_replace(btrim(v.nombre), '^regional\s+', '', 'i'))
)
ORDER BY v.nombre;

INSERT INTO centros_formacion (regional_id, nombre)
SELECT r.id, v.centro
FROM (VALUES
    ('Regional Amazonas', 'Centro para la Biodiversidad y el Turismo del Amazonas'),
    ('Regional Antioquia', 'Centro de los Recursos Naturales Renovables - La Salada'),
    ('Regional Antioquia', 'Centro del Diseño y Manufactura del Cuero'),
    ('Regional Antioquia', 'Centro de Formación en Diseño, Confección y Moda'),
    ('Regional Antioquia', 'Centro para el Desarrollo del Hábitat y la Construcción'),
    ('Regional Antioquia', 'Centro de Tecnología de la Manufactura Avanzada'),
    ('Regional Antioquia', 'Centro Tecnológico del Mobiliario'),
    ('Regional Antioquia', 'Centro Textil y de Gestión Industrial'),
    ('Regional Antioquia', 'Centro de Comercio'),
    ('Regional Antioquia', 'Centro de Servicios de Salud'),
    ('Regional Antioquia', 'Centro de Servicios y Gestión Empresarial'),
    ('Regional Antioquia', 'Complejo Tecnológico para la Gestión Agroempresarial'),
    ('Regional Antioquia', 'Complejo Tecnológico Minero Agroempresarial'),
    ('Regional Antioquia', 'Centro de la Innovación, la Agroindustria y la Aviación'),
    ('Regional Antioquia', 'Complejo Tecnológico Agroindustrial, Pecuario y Turístico'),
    ('Regional Antioquia', 'Complejo Tecnológico, Turístico y Agroindustrial del Occidente Antioqueño'),
    ('Regional Antioquia', 'Centro de Formación Minero Ambiental'),
    ('Regional Arauca', 'Centro de Gestión y Desarrollo Agroindustrial de Arauca'),
    ('Regional Atlántico', 'Centro para el Desarrollo Agroecológico y Agroindustrial'),
    ('Regional Atlántico', 'Centro Nacional Colombo Alemán'),
    ('Regional Atlántico', 'Centro Industrial y de Aviación'),
    ('Regional Atlántico', 'Centro de Comercio y Servicios'),
    ('Regional Bolívar', 'Centro Agroempresarial y Minero'),
    ('Regional Bolívar', 'Centro Internacional Náutico, Fluvial y Portuario'),
    ('Regional Bolívar', 'Centro para la Industria Petroquímica'),
    ('Regional Bolívar', 'Centro de Comercio y Servicios'),
    ('Regional Boyacá', 'Centro de Desarrollo Agropecuario y Agroindustrial'),
    ('Regional Boyacá', 'Centro Minero'),
    ('Regional Boyacá', 'Centro de Gestión Administrativa y Fortalecimiento Empresarial'),
    ('Regional Boyacá', 'Centro Industrial de Mantenimiento y Manufactura'),
    ('Regional Boyacá', 'Centro de la innovación Agroindustrial y de servicios'),
    ('Regional Caldas', 'Centro para la Formación Cafetera'),
    ('Regional Caldas', 'Centro de Automatización Industrial'),
    ('Regional Caldas', 'Centro de Procesos Industriales y Construcción'),
    ('Regional Caldas', 'Centro de Comercio y Servicios'),
    ('Regional Caldas', 'Centro Pecuario y Agroempresarial'),
    ('Regional Caquetá', 'Centro Tecnológico de la Amazonia'),
    ('Regional Casanare', 'Centro Agroindustrial y Fortalecimiento Empresarial de Casanare'),
    ('Regional Cauca', 'Centro Agropecuario'),
    ('Regional Cauca', 'Centro de Teleinformática y Producción Industrial'),
    ('Regional Cauca', 'Centro de Comercio y Servicios'),
    ('Regional Cesar', 'Centro Biotecnológico del Caribe'),
    ('Regional Cesar', 'Centro Agroempresarial'),
    ('Regional Cesar', 'Centro de Operación y Mantenimiento Minero'),
    ('Regional Chocó', 'Centro de Recursos Naturales, Industria y Biodiversidad'),
    ('Regional Córdoba', 'Centro Agropecuario y de Biotecnología el Porvenir'),
    ('Regional Córdoba', 'Centro de Comercio, Industria y Turismo de Córdoba'),
    ('Regional Cundinamarca', 'Centro Industrial y de Desarrollo Empresarial de Soacha'),
    ('Regional Cundinamarca', 'Centro de Desarrollo Agroindustrial y Empresarial'),
    ('Regional Cundinamarca', 'Centro Agroecológico y Empresarial'),
    ('Regional Cundinamarca', 'Centro de la Tecnología de Diseño y la Productividad Empresarial'),
    ('Regional Cundinamarca', 'Centro de Biotecnología Agropecuaria'),
    ('Regional Cundinamarca', 'Centro de Desarrollo Agroempresarial'),
    ('Regional Distrito Capital', 'Centro de Tecnologías para la Construcción y la Madera'),
    ('Regional Distrito Capital', 'Centro de Electricidad, Electrónica y Telecomunicaciones'),
    ('Regional Distrito Capital', 'Centro de Gestión Industrial'),
    ('Regional Distrito Capital', 'Centro de Manufactura en Textil y Cuero'),
    ('Regional Distrito Capital', 'Centro de Tecnologías del Transporte'),
    ('Regional Distrito Capital', 'Centro Metalmecánico'),
    ('Regional Distrito Capital', 'Centro de Materiales y Ensayos'),
    ('Regional Distrito Capital', 'Centro de Diseño y Metrología'),
    ('Regional Distrito Capital', 'Centro para la Industria de la Comunicación Gráfica'),
    ('Regional Distrito Capital', 'Centro de Gestión de Mercados, Logística y Tecnologías de la Información'),
    ('Regional Distrito Capital', 'Centro de Formación de Talento Humano en Salud'),
    ('Regional Distrito Capital', 'Centro de Gestión Administrativa'),
    ('Regional Distrito Capital', 'Centro de Servicios Financieros'),
    ('Regional Distrito Capital', 'Centro Nacional de Hotelería, Turismo y Alimentos'),
    ('Regional Distrito Capital', 'Centro de Formación en Actividad Física y Cultura'),
    ('Regional Guainía', 'Centro Ambiental y Ecoturístico del Nororiente Amazónico'),
    ('Regional Guaviare', 'Centro de Desarrollo Agroindustrial, Turístico y Tecnológico del Guaviare'),
    ('Regional Huila', 'Centro de Formación Agroindustrial'),
    ('Regional Huila', 'Centro Agroempresarial y Desarrollo Pecuario del Huila'),
    ('Regional Huila', 'Centro de Desarrollo Agroempresarial y Turístico del Huila'),
    ('Regional Huila', 'Centro de la Industria, la Empresa y los Servicios'),
    ('Regional Huila', 'Centro de Gestión y Desarrollo Sostenible Surcolombiano'),
    ('Regional La Guajira', 'Centro Industrial y de Energías Alternativas'),
    ('Regional La Guajira', 'Centro Agroempresarial y Acuícola'),
    ('Regional Magdalena', 'Centro Acuícola y Agroindustrial de Gaira'),
    ('Regional Magdalena', 'Centro de Logística y Promoción Ecoturística del Magdalena'),
    ('Regional Meta', 'Centro Agroindustrial del Meta'),
    ('Regional Meta', 'Centro de Industria y Servicios del Meta'),
    ('Regional Nariño', 'Centro Sur Colombiano de Logística Internacional'),
    ('Regional Nariño', 'Centro Agroindustrial y Pesquero de la Costa Pacífica'),
    ('Regional Nariño', 'Centro Internacional de Producción Limpia - Lope'),
    ('Regional Norte de Santander', 'Centro de Formación para el Desarrollo Rural y Minero'),
    ('Regional Norte de Santander', 'Centro de la Industria, la Empresa y los Servicios'),
    ('Regional Putumayo', 'Centro Agroforestal y Acuícola Arapaima'),
    ('Regional Quindío', 'Centro Agroindustrial'),
    ('Regional Quindío', 'Centro para el Desarrollo Tecnológico de la Construcción y la Industria'),
    ('Regional Quindío', 'Centro de Comercio y Turismo'),
    ('Regional Risaralda', 'Centro Atención Sector Agropecuario'),
    ('Regional Risaralda', 'Centro de Diseño e Innovación Tecnológica Industrial'),
    ('Regional Risaralda', 'Centro de Comercio y Servicios'),
    ('Regional San Andrés', 'Centro de Formación Turística, Gente de Mar y de Servicios'),
    ('Regional Santander', 'Centro de Atención al Sector Agropecuario'),
    ('Regional Santander', 'Centro Industrial de Mantenimiento Integral'),
    ('Regional Santander', 'Centro Industrial del Diseño y la Manufactura'),
    ('Regional Santander', 'Centro de Servicios Empresariales y Turísticos'),
    ('Regional Santander', 'Centro Industrial y del Desarrollo Tecnológico'),
    ('Regional Santander', 'Centro Agroturístico'),
    ('Regional Santander', 'Centro Agroempresarial y Turístico de los Andes'),
    ('Regional Santander', 'Centro de Gestión Agroempresarial del Oriente'),
    ('Regional Sucre', 'Centro de la Innovación, la Tecnología y los Servicios'),
    ('Regional Tolima', 'Centro Agropecuario La Granja'),
    ('Regional Tolima', 'Centro de Industria y Construcción'),
    ('Regional Tolima', 'Centro de Comercio y Servicios'),
    ('Regional Valle del Cauca', 'Centro Agropecuario de Buga'),
    ('Regional Valle del Cauca', 'Centro Latinoamericano de Especies Menores'),
    ('Regional Valle del Cauca', 'Centro Náutico Pesquero de Buenaventura'),
    ('Regional Valle del Cauca', 'Centro de Electricidad y Automatización Industrial'),
    ('Regional Valle del Cauca', 'Centro de la Construcción'),
    ('Regional Valle del Cauca', 'Centro de Diseño Tecnológico Industrial'),
    ('Regional Valle del Cauca', 'Centro Nacional de Asistencia Técnica a la Industria'),
    ('Regional Valle del Cauca', 'Centro de Gestión Tecnológica de Servicios'),
    ('Regional Valle del Cauca', 'Centro de Tecnologías Agroindustriales'),
    ('Regional Valle del Cauca', 'Centro de Biotecnología Industrial'),
    ('Regional Vaupés', 'Centro Agropecuario y de Servicios Ambientales Jirijirimo'),
    ('Regional Vichada', 'Centro de Producción y Transformación Agroindustrial de la Orinoquía')
) AS v (regional, centro)
JOIN (
    SELECT min(id) AS id, lower(regexp_replace(btrim(nombre), '^regional\s+', '', 'i')) AS clave
    FROM regionales
    GROUP BY lower(regexp_replace(btrim(nombre), '^regional\s+', '', 'i'))
) r ON r.clave = lower(regexp_replace(btrim(v.regional), '^regional\s+', '', 'i'))
WHERE NOT EXISTS (
    SELECT 1
    FROM centros_formacion c
    JOIN regionales rc ON rc.id = c.regional_id
    WHERE lower(regexp_replace(btrim(rc.nombre), '^regional\s+', '', 'i')) = r.clave
      AND lower(btrim(c.nombre)) = lower(v.centro)
)
ORDER BY r.id, v.centro;

COMMIT;

-- Búsquedas de centros por regional (y la llave foránea regional_id)
CREATE INDEX IF NOT EXISTS idx_centros_formacion_regional ON centros_formacion (regional_id, nombre);
