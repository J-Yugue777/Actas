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




# ---------------------------------------------------------------------------
# US-006 · Agenda y objetivos del acta
# ---------------------------------------------------------------------------
TIPOS_ITEM = ("agenda", "objetivo")
MAX_LARGO_ITEM = 500


def acta_del_lider(acta_id, usuario_id):
    """Devuelve el acta si existe y `usuario_id` es su líder; si no, None.

    Si la tabla real de actas (US-004) usa otro nombre para la columna del
    líder, cámbiala solo aquí.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM actas WHERE id = %s AND lider_id = %s",
                (acta_id, usuario_id),
            )
            return cur.fetchone()


def listar_items(acta_id):
    """Devuelve {'agenda': [...], 'objetivo': [...]} ordenados."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tipo, descripcion FROM acta_items "
                "WHERE acta_id = %s ORDER BY tipo, orden",
                (acta_id,),
            )
            filas = cur.fetchall()
    return {t: [f for f in filas if f["tipo"] == t] for t in TIPOS_ITEM}


def agregar_item(acta_id, tipo, descripcion):
    """Agrega un ítem al final de la lista. Lanza ValueError si no es válido."""
    if tipo not in TIPOS_ITEM:
        raise ValueError("Tipo de ítem no válido.")
    descripcion = " ".join((descripcion or "").split())  # recorta y colapsa espacios
    if not descripcion:
        raise ValueError("Escribe el texto antes de agregar.")
    if len(descripcion) > MAX_LARGO_ITEM:
        raise ValueError(f"Máximo {MAX_LARGO_ITEM} caracteres.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Serializa las altas concurrentes del mismo acta para que `orden` no choque
            cur.execute("SELECT id FROM actas WHERE id = %s FOR UPDATE", (acta_id,))
            cur.execute(
                "SELECT 1 FROM acta_items "
                "WHERE acta_id = %s AND tipo = %s AND LOWER(descripcion) = LOWER(%s)",
                (acta_id, tipo, descripcion),
            )
            if cur.fetchone():
                raise ValueError("Ese ítem ya está en la lista.")
            cur.execute(
                "INSERT INTO acta_items (acta_id, tipo, descripcion, orden) "
                "SELECT %s, %s, %s, COALESCE(MAX(orden), 0) + 1 "
                "FROM acta_items WHERE acta_id = %s AND tipo = %s",
                (acta_id, tipo, descripcion, acta_id, tipo),
            )


def eliminar_item(acta_id, item_id):
    """Quita un ítem del acta y vuelve a numerar los que quedan. True si existía."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM actas WHERE id = %s FOR UPDATE", (acta_id,))
            cur.execute(
                "DELETE FROM acta_items WHERE id = %s AND acta_id = %s RETURNING tipo",
                (item_id, acta_id),
            )
            fila = cur.fetchone()
            if not fila:
                return False
            cur.execute(
                """
                UPDATE acta_items a SET orden = n.nuevo
                FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY orden) AS nuevo
                      FROM acta_items WHERE acta_id = %s AND tipo = %s) n
                WHERE a.id = n.id AND a.orden <> n.nuevo
                """,
                (acta_id, fila["tipo"]),
            )
            return True
