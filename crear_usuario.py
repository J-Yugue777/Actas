"""
Crea un usuario de prueba con la contraseña ya cifrada.

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

with get_connection() as conn:
    with conn.cursor() as cur:
        # Reutiliza el rol si ya existe; si no, lo crea
        cur.execute("SELECT id FROM roles WHERE nombre = %s", (nombre_rol,))
        fila = cur.fetchone()
        if fila:
            rol_id = fila["id"]
        else:
            cur.execute("INSERT INTO roles (nombre) VALUES (%s) RETURNING id", (nombre_rol,))
            rol_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO usuarios
                (nombre, apellido, tipo_documento, fecha_nacimiento,
                 correo, password_hash, rol_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (nombre, apellido, tipo_documento, fecha_nacimiento,
             correo, generate_password_hash(password), rol_id),
        )

print("Usuario creado correctamente.")
