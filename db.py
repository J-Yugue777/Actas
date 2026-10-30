import os


import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


load_dotenv()




def get_connection():
    """Abre una conexión nueva a PostgreSQL con los datos del archivo .env."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        cursor_factory=RealDictCursor,
    )




def buscar_usuario_por_correo(correo):
    """Devuelve el usuario (con el nombre de su rol) o None si no existe."""
    sql = """
        SELECT u.id, u.nombre, u.apellido, u.correo,
               u.password_hash, u.activo, r.nombre AS rol
        FROM usuarios u
        JOIN roles r ON r.id = u.rol_id
        WHERE LOWER(u.correo) = LOWER(%s)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (correo,))
            return cur.fetchone()
