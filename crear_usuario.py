"""
Crea un usuario con la contraseña ya cifrada.

Uso:
    python crear_usuario.py
"""
from datetime import date
from getpass import getpass

from werkzeug.security import generate_password_hash

from db import get_connection

nombre = input("Nombre: ").strip()
apellido = input("Apellido: ").strip()
tipo_documento = input("Tipo de documento (ej. CC): ").strip()
fecha_nacimiento = date.fromisoformat(input("Fecha de nacimiento (AAAA-MM-DD): ").strip())
correo = input("Correo: ").strip()
password = getpass("Contraseña: ")
nombre_rol = input("Nombre del rol (ej. Administrador): ").strip()
tipo_vinculacion = input("Tipo de vinculación (ej. Carrera administrativa, Provisional, Contratista): ").strip()
direccion = input("Dirección: ").strip()
telefono = input("Teléfono: ").strip()

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM roles WHERE nombre = %s", (nombre_rol,))
        fila = cur.fetchone()
        if fila is None:
            cur.execute("SELECT nombre FROM roles ORDER BY nombre")
            disponibles = ", ".join(r["nombre"] for r in cur.fetchall())
            raise SystemExit(f'El rol "{nombre_rol}" no existe. Roles disponibles: {disponibles}')
        rol_id = fila["id"]

        cur.execute(
            """
            INSERT INTO usuarios
                (nombre, apellido, tipo_documento, fecha_nacimiento, correo,
                 password_hash, tipo_vinculacion, direccion, telefono, rol_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (nombre, apellido, tipo_documento, fecha_nacimiento, correo,
             generate_password_hash(password),
             tipo_vinculacion or None, direccion or None, telefono or None,
             rol_id),
        )

print("Usuario creado correctamente.")