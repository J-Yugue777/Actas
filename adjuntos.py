"""
US-012 · Adjuntos del acta (fotos y otros documentos que soportan lo tratado).

Reglas (RN-012):
- Tipos permitidos: imágenes JPG/PNG y documentos PDF, Word (.docx), Excel (.xlsx)
  y PowerPoint (.pptx). Se valida la extensión Y los primeros bytes del archivo
  (no basta con renombrar un .exe a .jpg).
- Tamaño máximo: 10 MB por archivo y 10 archivos por persona en cada acta.
- Las imágenes se pueden insertar en el PDF del acta (ver `es_imagen`);
  el resto de documentos queda como archivo aparte, descargable.
- Solo se adjunta mientras el acta está abierta.

Los archivos se guardan en disco (carpeta UPLOAD_DIR) con un nombre aleatorio;
el nombre original solo vive en la base de datos y nunca se usa como ruta.
"""
import os
import uuid
from pathlib import Path

from flask import current_app

MAX_BYTES = 10 * 1024 * 1024
MAX_POR_PERSONA = 10
MAX_LARGO_NOMBRE = 255

_ZIP = (b"PK\x03\x04",)
# extensión -> (tipo MIME, ¿es imagen?, firmas válidas al inicio del archivo)
TIPOS_PERMITIDOS = {
    "jpg": ("image/jpeg", True, (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", True, (b"\xff\xd8\xff",)),
    "png": ("image/png", True, (b"\x89PNG\r\n\x1a\n",)),
    "pdf": ("application/pdf", False, (b"%PDF-",)),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", False, _ZIP),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False, _ZIP),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", False, _ZIP),
}
EXTENSIONES_TEXTO = "JPG, PNG, PDF, DOCX, XLSX, PPTX"
ACCEPT_HTML = ",".join(f".{e}" for e in TIPOS_PERMITIDOS)


def carpeta_subidas():
    """Carpeta donde se guardan los archivos (se crea si no existe)."""
    base = Path(os.getenv("UPLOAD_DIR", "uploads"))
    if not base.is_absolute():
        base = Path(current_app.root_path) / base
    base.mkdir(parents=True, exist_ok=True)
    return base


def _mb(n):
    return f"{n / (1024 * 1024):g} MB"


def validar_archivo(archivo):
    """Revisa un FileStorage. Devuelve (extension, mime, es_imagen, tamano) o lanza ValueError."""
    nombre = os.path.basename((archivo.filename or "").replace("\\", "/")).strip()
    if not nombre:
        raise ValueError("Archivo sin nombre.")
    if len(nombre) > MAX_LARGO_NOMBRE:
        raise ValueError("el nombre es demasiado largo.")

    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension not in TIPOS_PERMITIDOS:
        raise ValueError(f"tipo no permitido (solo {EXTENSIONES_TEXTO}).")
    mime, es_imagen, firmas = TIPOS_PERMITIDOS[extension]

    flujo = archivo.stream
    flujo.seek(0, os.SEEK_END)
    tamano = flujo.tell()
    flujo.seek(0)
    if tamano == 0:
        raise ValueError("el archivo está vacío.")
    if tamano > MAX_BYTES:
        raise ValueError(f"supera el máximo de {_mb(MAX_BYTES)}.")

    cabecera = flujo.read(16)
    flujo.seek(0)
    if not cabecera.startswith(firmas):
        raise ValueError(f"el contenido no corresponde a un archivo .{extension} válido.")
    return extension, mime, es_imagen, tamano


def nombre_para_mostrar(archivo):
    return os.path.basename((archivo.filename or "").replace("\\", "/")).strip()


def guardar_en_disco(archivo, extension):
    """Escribe el archivo con nombre aleatorio y devuelve ese nombre."""
    nombre = f"{uuid.uuid4().hex}.{extension}"
    archivo.save(carpeta_subidas() / nombre)
    return nombre


def borrar_de_disco(nombre_archivo):
    try:
        (carpeta_subidas() / nombre_archivo).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        current_app.logger.exception("No se pudo borrar el adjunto %s", nombre_archivo)


def listar_adjuntos(cur, acta_id):
    cur.execute(
        """
        SELECT ad.id, ad.usuario_id, ad.nombre_original, ad.tipo_mime, ad.tamano_bytes,
               ad.es_imagen, ad.creado_en, u.nombre || ' ' || u.apellido AS autor
        FROM acta_adjuntos ad
        JOIN usuarios u ON u.id = ad.usuario_id
        WHERE ad.acta_id = %s
        ORDER BY ad.creado_en, ad.id
        """,
        (acta_id,),
    )
    return cur.fetchall()


def contar_de_persona(cur, acta_id, usuario_id):
    cur.execute(
        "SELECT COUNT(*) AS n FROM acta_adjuntos WHERE acta_id = %s AND usuario_id = %s",
        (acta_id, usuario_id),
    )
    return cur.fetchone()["n"]


def insertar_adjunto(cur, acta_id, usuario_id, nombre_original, nombre_archivo, mime, tamano, es_imagen):
    cur.execute(
        """
        INSERT INTO acta_adjuntos
            (acta_id, usuario_id, nombre_original, nombre_archivo, tipo_mime, tamano_bytes, es_imagen)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (acta_id, usuario_id, nombre_original, nombre_archivo, mime, tamano, es_imagen),
    )
