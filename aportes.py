"""
US-020 · Aporte de cada participante al acta: desarrollo de la reunión y conclusiones.

Límite real (NFR-02): MAX_LARGO_APORTE = 50.000 caracteres por campo.
- Son unas 15 páginas carta a espacio sencillo (~3.300 caracteres por página):
  alcanza para el relato completo de una reunión larga sin truncarlo.
- Pone un techo a lo que viaja en cada envío, a lo que se guarda por persona y a
  lo que se dibuja en la página y en el PDF del acta.
- Es el MISMO número del CHECK de la base de datos
  (db/migraciones/US-020_aporte_textos_largos.sql). Si cambias uno, cambia el otro.

Cómo se cuenta: len() de Python, es decir, una tilde, una eñe o un emoji valen 1.
El salto de línea vale 1: el navegador lo envía como \\r\\n, por eso se normaliza
a \\n ANTES de contar. Solo se recortan los espacios al inicio y al final del
texto completo; los saltos de línea y los espacios internos se conservan.
"""

MAX_LARGO_APORTE = 50_000

# Flask lee en memoria los formularios normales (no multipart) y por defecto los
# corta en 500 KB con un error 413, perdiendo lo escrito. Peor caso del aporte: un
# emoji ocupa 4 bytes en UTF-8 y cada byte viaja como %XX (3 bytes) = 12 bytes por
# carácter; 2 campos x 50.000 x 12 = 1,2 MB. Con 2 MB queda margen. Ver app.py.
MAX_BYTES_FORMULARIO = 2 * 1024 * 1024

# campo del formulario y de acta_participantes -> cómo se nombra en los mensajes
CAMPOS = {
    "desarrollo": "El desarrollo tiene",
    "conclusiones": "Las conclusiones tienen",
}


def miles(n):
    """50000 -> '50.000' (separador de miles con punto)."""
    return f"{n:,}".replace(",", ".")


def normalizar(texto):
    """Deja el texto como se guarda: saltos \\n y sin espacios en los extremos. Vacío -> None."""
    texto = (texto or "").replace("\r\n", "\n").replace("\r", "\n")
    texto = texto.replace("\x00", "")  # PostgreSQL no admite el carácter nulo en un TEXT
    return texto.strip() or None


def leer_aporte(form):
    return {campo: normalizar(form.get(campo)) for campo in CAMPOS}


def validar_aporte(aporte):
    """Devuelve la lista de errores (vacía si el aporte se puede guardar)."""
    if not any(aporte.values()):
        return ["Escribe el desarrollo o las conclusiones de tu aporte."]
    errores = []
    for campo, sujeto in CAMPOS.items():
        largo = len(aporte[campo] or "")
        if largo > MAX_LARGO_APORTE:
            errores.append(f"{sujeto} {miles(largo)} caracteres; el máximo es {miles(MAX_LARGO_APORTE)}.")
    return errores
