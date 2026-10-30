-- SQLBook: Code

-- SQLBook: Code
-- Se ejecuta automáticamente la PRIMERA vez que se crea el contenedor.

CREATE TABLE tipos_documento (
    id     SERIAL PRIMARY KEY,
    nombre VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE usuarios (
    id                SERIAL PRIMARY KEY,
    tipo_documento_id INTEGER NOT NULL REFERENCES tipos_documento(id),
    numero_documento  VARCHAR(20) NOT NULL,
    password_hash     TEXT NOT NULL,
    UNIQUE (tipo_documento_id, numero_documento)
);
-- SQLBook: Code
-- Datos iniciales (solo para desarrollo).

INSERT INTO tipos_documento (nombre) VALUES
    ('Cédula de ciudadanía'),
    ('Tarjeta de identidad'),
    ('Cédula de extranjería'),
    ('Pasaporte');

-- Usuario de prueba -> documento: 123456789 | contraseña: Demo12345
INSERT INTO usuarios (tipo_documento_id, numero_documento, password_hash)
VALUES (1, '123456789', 'scrypt:32768:8:1$qvoo9vxumpMEEGJ2$527d4a3297ec5711d1bf363bb7dd9c722a4e0526b7fd417ec986c96913384646398ad22e438d5d61aec8d71c630e1060ee6e5cf3f211e0af4615c42b8efe4626');