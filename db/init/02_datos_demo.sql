-- =====================================================================
-- DATOS DE PRUEBA · para poder entrar al aplicativo y crear actas.
-- Corre DESPUÉS de 01_esquema.sql. Se puede correr más de una vez:
-- lo que ya existe no se duplica.
--
-- Usuarios (todos con la contraseña Demo12345):
--   admin@actas.local       Administrador: ve todo y crea actas en cualquier ficha
--   lider@actas.local       Instructor líder de la ficha 3210115
--   instructor@actas.local  Instructor de la ficha 3210115 (no crea actas)
--
-- Para crear un usuario propio: py crear_usuario.py (en Windows) o python crear_usuario.py
-- =====================================================================

BEGIN;

-- Programa, ficha y equipo ejecutor de ejemplo
INSERT INTO programas (codigo, nombre)
SELECT '228118', 'Análisis y Desarrollo de Software'
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE codigo = '228118');

INSERT INTO fichas (numero, programa_id)
SELECT '3210115', id FROM programas WHERE codigo = '228118'
ON CONFLICT (numero) DO NOTHING;

INSERT INTO equipos_ejecutores (nombre)
SELECT 'Equipo ejecutor ficha 3210115'
WHERE NOT EXISTS (SELECT 1 FROM equipos_ejecutores WHERE nombre = 'Equipo ejecutor ficha 3210115');

INSERT INTO equipo_ficha (equipo_ejecutor_id, ficha_id)
SELECT e.id, f.id
FROM equipos_ejecutores e, fichas f
WHERE e.nombre = 'Equipo ejecutor ficha 3210115' AND f.numero = '3210115'
ON CONFLICT (equipo_ejecutor_id, ficha_id) DO NOTHING;

-- Usuarios (contraseña Demo12345, ya cifrada como la guarda el aplicativo)
INSERT INTO usuarios (nombre, apellido, tipo_documento, fecha_nacimiento, correo,
                      password_hash, tipo_vinculacion, direccion, telefono, rol_id)
SELECT v.nombre, v.apellido, 'CC', v.nacimiento::date, v.correo, v.hash,
       v.vinculacion, 'Cali', '3000000000', r.id
FROM (VALUES
    ('Admin', 'Demo', '1990-01-01', 'admin@actas.local', 'Carrera administrativa',
     'Administrador',
     'pbkdf2:sha256:1000000$c4srzTzLnAx6lBBK$25c5f8b7763d9f59d5c9f82db4905aed0c6e548c41ee1ccccd9ece0b28c09011'),
    ('Lina', 'Líder', '1992-05-10', 'lider@actas.local', 'Contratista',
     'Instructor líder de ficha',
     'pbkdf2:sha256:1000000$2xdEfFS0A5G2OgTP$0991c0c3c1107e220ee6c0fe912f40535c37b34afaaa444a2849ec063c570edf'),
    ('Iván', 'Instructor', '1995-08-20', 'instructor@actas.local', 'Contratista',
     'Instructor',
     'pbkdf2:sha256:1000000$cWiLEgpKT7gjJU9z$cbc7872ac032bb12420c0338626dae8745d28cebcfc4237957211446b2e85798')
) AS v(nombre, apellido, nacimiento, correo, vinculacion, rol, hash)
JOIN roles r ON r.nombre = v.rol
ON CONFLICT (correo) DO NOTHING;

-- Integrantes del equipo con su rol en ese equipo
INSERT INTO equipo_integrantes (equipo_ejecutor_id, usuario_id, rol_id)
SELECT e.id, u.id, r.id
FROM (VALUES
    ('lider@actas.local', 'Instructor líder de ficha'),
    ('instructor@actas.local', 'Instructor')
) AS v(correo, rol)
JOIN usuarios u ON u.correo = v.correo
JOIN roles r ON r.nombre = v.rol
JOIN equipos_ejecutores e ON e.nombre = 'Equipo ejecutor ficha 3210115'
ON CONFLICT (equipo_ejecutor_id, usuario_id) DO NOTHING;

COMMIT;
