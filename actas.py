# """
# Módulo de actas: crear acta y ver acta.

# Reglas de permiso:
# - Puede crear actas quien tenga un rol con puede_crear_acta = TRUE, o quien sea
#   "Instructor líder de ficha" en al menos una ficha (rol dentro del equipo ejecutor).
# - Actas de equipo ejecutor:
#     * Administrador y Coordinador académico: cualquier ficha activa.
#     * Los demás: solo las fichas donde son "Instructor líder de ficha".
#     * Un Instructor integrante NO puede crearlas.
# - Actas de "otros asuntos": cualquier usuario autorizado a crear actas.
# - Solo una acta de equipo ejecutor por ficha y mes.
# """
# import sys
# from contextlib import contextmanager
# from datetime import date, time
# from functools import wraps

# import psycopg2
# from flask import (Blueprint, abort, current_app, flash, redirect,
#                    render_template, request, send_from_directory, session, url_for)

# import adjuntos as adj
# from db import get_connection

# actas_bp = Blueprint("actas", __name__, url_prefix="/actas")

# ROL_LIDER = "Instructor líder de ficha"
# ROLES_TODAS_LAS_FICHAS = ("Administrador", "Coordinador académico")
# CODIGO_FORMATO_DEFECTO = "GOR-F-084 v2"
# MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
#          "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# SQL_TODAS_LAS_FICHAS = """
#     SELECT f.id, f.numero, p.nombre AS programa
#     FROM fichas f
#     JOIN programas p ON p.id = f.programa_id
#     WHERE f.activa
#     ORDER BY f.numero
# """

# SQL_FICHAS_LIDER = """
#     SELECT DISTINCT f.id, f.numero, p.nombre AS programa
#     FROM equipo_integrantes ei
#     JOIN roles r ON r.id = ei.rol_id AND r.nombre = %s
#     JOIN equipo_ficha ef ON ef.equipo_ejecutor_id = ei.equipo_ejecutor_id
#     JOIN fichas f ON f.id = ef.ficha_id AND f.activa
#     JOIN programas p ON p.id = f.programa_id
#     WHERE ei.usuario_id = %s
#     ORDER BY f.numero
# """


# # ----------------------------------------------------------------- utilidades
# @contextmanager
# def transaccion():
#     """Abre una conexión, confirma al terminar (o revierte si hay error) y la cierra."""
#     conn = get_connection()
#     try:
#         with conn:
#             with conn.cursor() as cur:
#                 yield cur
#     finally:
#         conn.close()


# def login_requerido(vista):
#     @wraps(vista)
#     def envoltura(*args, **kwargs):
#         if "usuario_id" not in session:
#             return redirect(url_for("login"))
#         return vista(*args, **kwargs)

#     return envoltura


# def _entero(valor):
#     try:
#         return int(valor)
#     except (TypeError, ValueError):
#         return None


# def obtener_permisos(cur, usuario_id):
#     """Devuelve si el usuario puede crear actas y en qué fichas puede crear actas de equipo ejecutor."""
#     cur.execute(
#         """
#         SELECT r.nombre, r.puede_crear_acta
#         FROM usuarios u
#         JOIN roles r ON r.id = u.rol_id
#         WHERE u.id = %s AND u.activo
#         """,
#         (usuario_id,),
#     )
#     fila = cur.fetchone()
#     if fila is None:
#         return {"puede_crear": False, "fichas": [], "rol": None}

#     if fila["nombre"] in ROLES_TODAS_LAS_FICHAS:
#         cur.execute(SQL_TODAS_LAS_FICHAS)
#     else:
#         cur.execute(SQL_FICHAS_LIDER, (ROL_LIDER, usuario_id))
#     fichas = cur.fetchall()

#     return {
#         "puede_crear": bool(fila["puede_crear_acta"]) or bool(fichas),
#         "fichas": fichas,
#         "rol": fila["nombre"],
#     }


# @actas_bp.app_context_processor
# def inyectar_permiso():
#     """Hace disponible `puede_crear_acta` en todas las plantillas (para el menú)."""
#     if "usuario_id" not in session:
#         return {}
#     try:
#         with transaccion() as cur:
#             return {"puede_crear_acta": obtener_permisos(cur, session["usuario_id"])["puede_crear"]}
#     except psycopg2.Error:
#         return {"puede_crear_acta": False}


# def cargar_catalogos(cur):
#     cur.execute("SELECT id, nombre FROM regionales ORDER BY nombre")
#     regionales = cur.fetchall()
#     cur.execute("SELECT id, regional_id, nombre FROM centros_formacion ORDER BY nombre")
#     centros = [dict(c) for c in cur.fetchall()]
#     return regionales, centros


# # ---------------------------------------------------------------- formulario
# def datos_iniciales(permisos):
#     return {
#         "tipo_acta": "equipo_ejecutor" if permisos["fichas"] else "otros_asuntos",
#         "nombre_reunion": "", "ciudad": "", "fecha_reunion": "",
#         "hora_inicio": "", "hora_fin": "", "lugar_enlace": "",
#         "regional_id": "", "centro_id": "", "ficha_id": "", "mes": "",
#         "codigo_formato": CODIGO_FORMATO_DEFECTO,
#         "agenda": [], "objetivos": [],
#     }


# def _limpiar_lista(items):
#     """Colapsa espacios y quita vacíos y repetidos (sin distinguir mayúsculas), como db.agregar_item."""
#     limpios, vistos = [], set()
#     for t in items:
#         t = " ".join(t.split())
#         if t and t.lower() not in vistos:
#             vistos.add(t.lower())
#             limpios.append(t)
#     return limpios


# def leer_formulario(form):
#     texto = lambda campo: form.get(campo, "").strip()  # noqa: E731
#     return {
#         "tipo_acta": texto("tipo_acta"),
#         "nombre_reunion": texto("nombre_reunion"),
#         "ciudad": texto("ciudad"),
#         "fecha_reunion": texto("fecha_reunion"),
#         "hora_inicio": texto("hora_inicio"),
#         "hora_fin": texto("hora_fin"),
#         "lugar_enlace": texto("lugar_enlace"),
#         "regional_id": texto("regional_id"),
#         "centro_id": texto("centro_id"),
#         "ficha_id": texto("ficha_id"),
#         "mes": texto("mes"),
#         "codigo_formato": texto("codigo_formato"),
#         "agenda": _limpiar_lista(form.getlist("agenda")),
#         "objetivos": _limpiar_lista(form.getlist("objetivos")),
#     }


# def validar(cur, datos, permisos):
#     """Valida los datos en el servidor. Devuelve (errores, valores ya convertidos)."""
#     errores = []

#     tipos_permitidos = ["otros_asuntos"] + (["equipo_ejecutor"] if permisos["fichas"] else [])
#     if datos["tipo_acta"] not in tipos_permitidos:
#         errores.append("Elige un tipo de acta permitido para tu rol.")

#     for campo, etiqueta, maximo in (
#         ("nombre_reunion", "El nombre de la reunión", 200),
#         ("ciudad", "La ciudad", 100),
#         ("lugar_enlace", "El lugar o enlace de la reunión", 300),
#     ):
#         if not datos[campo]:
#             errores.append(f"{etiqueta} es obligatorio.")
#         elif len(datos[campo]) > maximo:
#             errores.append(f"{etiqueta} no puede superar {maximo} caracteres.")

#     if len(datos["codigo_formato"]) > 30:
#         errores.append("El código y versión del formato no puede superar 30 caracteres.")

#     fecha = hora_inicio = hora_fin = None
#     try:
#         fecha = date.fromisoformat(datos["fecha_reunion"])
#     except ValueError:
#         errores.append("Escribe una fecha de reunión válida.")
#     try:
#         hora_inicio = time.fromisoformat(datos["hora_inicio"])
#     except ValueError:
#         errores.append("Escribe una hora de inicio válida.")
#     try:
#         hora_fin = time.fromisoformat(datos["hora_fin"])
#     except ValueError:
#         errores.append("Escribe una hora de fin válida.")
#     if hora_inicio and hora_fin and hora_fin <= hora_inicio:
#         errores.append("La hora de fin debe ser posterior a la hora de inicio.")

#     regional_id = _entero(datos["regional_id"])
#     centro_id = _entero(datos["centro_id"])
#     if not regional_id or not centro_id:
#         errores.append("Selecciona la regional y el centro de formación.")
#     else:
#         cur.execute(
#             "SELECT 1 FROM centros_formacion WHERE id = %s AND regional_id = %s",
#             (centro_id, regional_id),
#         )
#         if cur.fetchone() is None:
#             errores.append("El centro de formación no pertenece a la regional elegida.")

#     ficha_id = mes = None
#     if datos["tipo_acta"] == "equipo_ejecutor":
#         ficha_id = _entero(datos["ficha_id"])
#         mes = _entero(datos["mes"])
#         permitidas = {f["id"] for f in permisos["fichas"]}

#         if ficha_id not in permitidas:
#             errores.append("Selecciona una ficha en la que tengas permiso para crear actas.")
#         if mes is None or not 1 <= mes <= 12:
#             errores.append("Selecciona el mes del acta.")
#         elif ficha_id in permitidas and fecha:
#             cur.execute(
#                 """
#                 SELECT numero_acta FROM actas
#                 WHERE tipo_acta = 'equipo_ejecutor'
#                   AND ficha_id = %s AND anio = %s AND mes = %s
#                 """,
#                 (ficha_id, fecha.year, mes),
#             )
#             existente = cur.fetchone()
#             if existente:
#                 errores.append(
#                     f"Ya existe un acta de esa ficha para {MESES[mes - 1].lower()} de {fecha.year} "
#                     f"({existente['numero_acta']}). No se puede crear otra."
#                 )

#     if not datos["agenda"]:
#         errores.append("Agrega al menos un punto a la agenda.")
#     if not datos["objetivos"]:
#         errores.append("Agrega al menos un objetivo de la reunión.")
#     if any(len(t) > 500 for t in datos["agenda"] + datos["objetivos"]):
#         errores.append("Cada punto de agenda u objetivo puede tener máximo 500 caracteres.")

#     valores = {
#         "tipo_acta": datos["tipo_acta"],
#         "nombre_reunion": datos["nombre_reunion"],
#         "ciudad": datos["ciudad"],
#         "fecha": fecha,
#         "hora_inicio": hora_inicio,
#         "hora_fin": hora_fin,
#         "lugar_enlace": datos["lugar_enlace"],
#         "regional_id": regional_id,
#         "centro_id": centro_id,
#         "ficha_id": ficha_id,
#         "mes": mes,
#         "codigo_formato": datos["codigo_formato"] or None,
#         "agenda": datos["agenda"],
#         "objetivos": datos["objetivos"],
#     }
#     return errores, valores


# def guardar_acta(cur, usuario_id, v):
#     """Inserta el acta, su agenda/objetivos y sus participantes. Devuelve (id, numero_acta)."""
#     anio = v["fecha"].year

#     # Evita que dos personas obtengan el mismo consecutivo al mismo tiempo
#     cur.execute(
#         "SELECT pg_advisory_xact_lock(hashtext(%s))",
#         (f"acta:{v['centro_id']}:{v['ficha_id'] or 0}:{anio}",),
#     )
#     cur.execute(
#         """
#         SELECT COALESCE(MAX(consecutivo), 0) + 1 AS n
#         FROM actas
#         WHERE centro_id = %s AND COALESCE(ficha_id, 0) = %s AND anio = %s
#         """,
#         (v["centro_id"], v["ficha_id"] or 0, anio),
#     )
#     consecutivo = cur.fetchone()["n"]
#     numero_acta = f"Acta {consecutivo}"

#     cur.execute(
#         """
#         INSERT INTO actas
#             (tipo_acta, consecutivo, anio, numero_acta, nombre_reunion, ciudad,
#              fecha_reunion, hora_inicio, hora_fin, lugar_enlace, regional_id,
#              centro_id, ficha_id, mes, codigo_formato, lider_id)
#         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#         RETURNING id
#         """,
#         (v["tipo_acta"], consecutivo, anio, numero_acta, v["nombre_reunion"], v["ciudad"],
#          v["fecha"], v["hora_inicio"], v["hora_fin"], v["lugar_enlace"], v["regional_id"],
#          v["centro_id"], v["ficha_id"], v["mes"], v["codigo_formato"], usuario_id),
#     )
#     acta_id = cur.fetchone()["id"]

#     for tipo, items in (("agenda", v["agenda"]), ("objetivo", v["objetivos"])):
#         for orden, texto in enumerate(items, start=1):
#             cur.execute(
#                 "INSERT INTO acta_items (acta_id, tipo, descripcion, orden) VALUES (%s, %s, %s, %s)",
#                 (acta_id, tipo, texto, orden),
#             )

#     # Participantes: quien crea el acta + los integrantes de los equipos de la ficha.
#     # En actas de "otros asuntos" (sin ficha) solo entra el creador.
#     cur.execute(
#         """
#         INSERT INTO acta_participantes (acta_id, usuario_id)
#         SELECT %s, x.usuario_id
#         FROM (
#             SELECT %s::int AS usuario_id
#             UNION
#             SELECT ei.usuario_id
#             FROM equipo_integrantes ei
#             JOIN equipo_ficha ef ON ef.equipo_ejecutor_id = ei.equipo_ejecutor_id
#             WHERE ef.ficha_id = %s
#         ) x
#         """,
#         (acta_id, usuario_id, v["ficha_id"]),
#     )
#     return acta_id, numero_acta


# # --------------------------------------------------------------------- rutas
# @actas_bp.route("/crear", methods=["GET", "POST"])
# @login_requerido
# def crear():
#     usuario_id = session["usuario_id"]
#     errores = []
#     try:
#         with transaccion() as cur:
#             permisos = obtener_permisos(cur, usuario_id)
#             if not permisos["puede_crear"]:
#                 abort(403)
#             regionales, centros = cargar_catalogos(cur)
#             datos = datos_iniciales(permisos)

#             if request.method == "POST":
#                 datos = leer_formulario(request.form)
#                 errores, valores = validar(cur, datos, permisos)
#                 if not errores:
#                     acta_id, numero = guardar_acta(cur, usuario_id, valores)
#                     flash(f"{numero} creada. Ya está abierta para recibir aportes.", "ok")
#                     return redirect(url_for("actas.ver", acta_id=acta_id))
#     except psycopg2.errors.UniqueViolation:
#         errores = ["No se pudo guardar: ya existe un acta para esa ficha y mes, "
#                    "o alguien más la creó al mismo tiempo. Intenta de nuevo."]
#     except psycopg2.Error:
#         current_app.logger.exception("Error de base de datos al crear el acta")
#         abort(503)

#     return render_template(
#         "crear_acta.html",
#         datos=datos, errores=errores, regionales=regionales, centros=centros,
#         fichas=permisos["fichas"], puede_equipo=bool(permisos["fichas"]), meses=MESES,
#     )


# @actas_bp.route("/<int:acta_id>")
# @login_requerido
# def ver(acta_id):
#     usuario_id = session["usuario_id"]
#     try:
#         with transaccion() as cur:
#             cur.execute(
#                 """
#                 SELECT a.*, rg.nombre AS regional, c.nombre AS centro,
#                        f.numero AS ficha, p.nombre AS programa,
#                        u.nombre || ' ' || u.apellido AS creador
#                 FROM actas a
#                 JOIN regionales rg ON rg.id = a.regional_id
#                 JOIN centros_formacion c ON c.id = a.centro_id
#                 JOIN usuarios u ON u.id = a.lider_id
#                 LEFT JOIN fichas f ON f.id = a.ficha_id
#                 LEFT JOIN programas p ON p.id = f.programa_id
#                 WHERE a.id = %s
#                 """,
#                 (acta_id,),
#             )
#             acta = cur.fetchone()
#             if acta is None:
#                 abort(404)

#             cur.execute(
#                 "SELECT r.nombre FROM usuarios u JOIN roles r ON r.id = u.rol_id WHERE u.id = %s",
#                 (usuario_id,),
#             )
#             rol = cur.fetchone()["nombre"]
#             cur.execute(
#                 "SELECT 1 FROM acta_participantes WHERE acta_id = %s AND usuario_id = %s",
#                 (acta_id, usuario_id),
#             )
#             es_participante = cur.fetchone() is not None
#             if not (es_participante or acta["lider_id"] == usuario_id or rol in ROLES_TODAS_LAS_FICHAS):
#                 abort(403)

#             cur.execute(
#                 "SELECT tipo, descripcion FROM acta_items WHERE acta_id = %s ORDER BY tipo, orden",
#                 (acta_id,),
#             )
#             puntos = cur.fetchall()
#             cur.execute(
#                 """
#                 SELECT u.nombre, u.apellido, r.nombre AS rol, (u.id = %s) AS es_creador,
#                        (p.desarrollo IS NOT NULL OR p.conclusiones IS NOT NULL) AS aporto
#                 FROM acta_participantes p
#                 JOIN usuarios u ON u.id = p.usuario_id
#                 JOIN roles r ON r.id = u.rol_id
#                 WHERE p.acta_id = %s
#                 ORDER BY (u.id = %s) DESC, u.apellido, u.nombre
#                 """,
#                 (acta["lider_id"], acta_id, acta["lider_id"]),
#             )
#             participantes = cur.fetchall()
#             lista_adjuntos = adj.listar_adjuntos(cur, acta_id)
#             puede_adjuntar = acta["estado"] == "abierta" and (
#                 es_participante or acta["lider_id"] == usuario_id)
#     except psycopg2.Error:
#         current_app.logger.exception("Error de base de datos al ver el acta")
#         abort(503)

#     return render_template(
#         "ver_acta.html", acta=acta, meses=MESES, participantes=participantes,
#         adjuntos=lista_adjuntos, puede_adjuntar=puede_adjuntar,
#         puede_gestionar_adjuntos=acta["estado"] == "abierta",
#         max_mb=adj.MAX_BYTES // (1024 * 1024), max_bytes=adj.MAX_BYTES,
#         max_por_persona=adj.MAX_POR_PERSONA, tipos_texto=adj.EXTENSIONES_TEXTO,
#         accept=adj.ACCEPT_HTML,
#         agenda=[p["descripcion"] for p in puntos if p["tipo"] == "agenda"],
#         objetivos=[p["descripcion"] for p in puntos if p["tipo"] == "objetivo"],
#     )


# # ------------------------------------------------------- US-012 · adjuntos
# def _acceso(cur, acta_id, usuario_id):
#     """Datos de acceso del usuario al acta. 404 si no existe, 403 si no participa."""
#     cur.execute("SELECT id, lider_id, estado FROM actas WHERE id = %s", (acta_id,))
#     acta = cur.fetchone()
#     if acta is None:
#         abort(404)
#     cur.execute(
#         "SELECT r.nombre FROM usuarios u JOIN roles r ON r.id = u.rol_id WHERE u.id = %s",
#         (usuario_id,),
#     )
#     rol = cur.fetchone()["nombre"]
#     cur.execute(
#         "SELECT 1 FROM acta_participantes WHERE acta_id = %s AND usuario_id = %s",
#         (acta_id, usuario_id),
#     )
#     participa = cur.fetchone() is not None or acta["lider_id"] == usuario_id
#     if not (participa or rol in ROLES_TODAS_LAS_FICHAS):
#         abort(403)
#     return {"acta": acta, "participa": participa, "es_lider": acta["lider_id"] == usuario_id}


# @actas_bp.route("/<int:acta_id>/adjuntos", methods=["POST"])
# @login_requerido
# def subir_adjuntos(acta_id):
#     usuario_id = session["usuario_id"]
#     archivos = [f for f in request.files.getlist("archivos") if f and f.filename]
#     destino = redirect(url_for("actas.ver", acta_id=acta_id) + "#adjuntos")
#     if not archivos:
#         flash("Selecciona al menos un archivo para adjuntar.", "error")
#         return destino

#     guardados, rechazados, rutas = 0, [], []
#     try:
#         with transaccion() as cur:
#             acceso = _acceso(cur, acta_id, usuario_id)
#             if not acceso["participa"]:
#                 abort(403)
#             if acceso["acta"]["estado"] != "abierta":
#                 flash("El acta ya no está abierta: no se pueden adjuntar más archivos.", "error")
#                 return destino

#             # Serializa las subidas del mismo acta para respetar el tope por persona
#             cur.execute("SELECT id FROM actas WHERE id = %s FOR UPDATE", (acta_id,))
#             disponibles = adj.MAX_POR_PERSONA - adj.contar_de_persona(cur, acta_id, usuario_id)

#             for archivo in archivos:
#                 nombre = adj.nombre_para_mostrar(archivo)
#                 try:
#                     if disponibles <= 0:
#                         raise ValueError(f"ya alcanzaste el máximo de {adj.MAX_POR_PERSONA} archivos en esta acta.")
#                     extension, mime, es_imagen, tamano = adj.validar_archivo(archivo)
#                 except ValueError as error:
#                     rechazados.append(f"{nombre or 'Archivo'}: {error}")
#                     continue
#                 guardado = adj.guardar_en_disco(archivo, extension)
#                 rutas.append(guardado)
#                 adj.insertar_adjunto(cur, acta_id, usuario_id, nombre, guardado, mime, tamano, es_imagen)
#                 disponibles -= 1
#                 guardados += 1
#     except BaseException:
#         for ruta in rutas:  # la transacción se revirtió: no dejes archivos huérfanos
#             adj.borrar_de_disco(ruta)
#         if isinstance(sys.exc_info()[1], psycopg2.Error):
#             current_app.logger.exception("Error de base de datos al subir adjuntos")
#             flash("No pudimos guardar los archivos. Intenta de nuevo.", "error")
#             return destino
#         raise

#     if guardados:
#         flash(f"{guardados} archivo(s) adjuntado(s).", "ok")
#     for motivo in rechazados:
#         flash(f"No se adjuntó {motivo}", "error")
#     return destino


# @actas_bp.route("/<int:acta_id>/adjuntos/<int:adjunto_id>")
# @login_requerido
# def descargar_adjunto(acta_id, adjunto_id):
#     try:
#         with transaccion() as cur:
#             _acceso(cur, acta_id, session["usuario_id"])
#             cur.execute(
#                 "SELECT nombre_original, nombre_archivo, tipo_mime, es_imagen "
#                 "FROM acta_adjuntos WHERE id = %s AND acta_id = %s",
#                 (adjunto_id, acta_id),
#             )
#             fila = cur.fetchone()
#     except psycopg2.Error:
#         current_app.logger.exception("Error de base de datos al descargar el adjunto")
#         abort(503)
#     if fila is None:
#         abort(404)

#     # Las imágenes se muestran en la página; todo lo demás se descarga.
#     como_descarga = (not fila["es_imagen"]) or request.args.get("descargar") == "1"
#     respuesta = send_from_directory(
#         adj.carpeta_subidas(), fila["nombre_archivo"], mimetype=fila["tipo_mime"],
#         as_attachment=como_descarga, download_name=fila["nombre_original"],
#     )
#     respuesta.headers["X-Content-Type-Options"] = "nosniff"
#     respuesta.headers["Cache-Control"] = "private, max-age=300"
#     return respuesta


# @actas_bp.route("/<int:acta_id>/adjuntos/<int:adjunto_id>/eliminar", methods=["POST"])
# @login_requerido
# def eliminar_adjunto(acta_id, adjunto_id):
#     usuario_id = session["usuario_id"]
#     archivo_a_borrar = None
#     try:
#         with transaccion() as cur:
#             acceso = _acceso(cur, acta_id, usuario_id)
#             if acceso["acta"]["estado"] != "abierta":
#                 flash("El acta ya no está abierta: no se pueden quitar archivos.", "error")
#             else:
#                 cur.execute(
#                     "SELECT usuario_id, nombre_archivo FROM acta_adjuntos WHERE id = %s AND acta_id = %s",
#                     (adjunto_id, acta_id),
#                 )
#                 fila = cur.fetchone()
#                 if fila is None:
#                     flash("Ese archivo ya no existe.", "error")
#                 elif fila["usuario_id"] != usuario_id and not acceso["es_lider"]:
#                     abort(403)  # solo quien lo subió o el líder del acta
#                 else:
#                     cur.execute("DELETE FROM acta_adjuntos WHERE id = %s", (adjunto_id,))
#                     archivo_a_borrar = fila["nombre_archivo"]
#                     flash("Archivo eliminado.", "ok")
#     except psycopg2.Error:
#         current_app.logger.exception("Error de base de datos al eliminar el adjunto")
#         flash("No pudimos eliminar el archivo. Intenta de nuevo.", "error")
#     if archivo_a_borrar:
#         adj.borrar_de_disco(archivo_a_borrar)
#     return redirect(url_for("actas.ver", acta_id=acta_id) + "#adjuntos")


# @actas_bp.app_errorhandler(413)
# def archivo_demasiado_grande(error):
#     """La petición completa superó MAX_CONTENT_LENGTH (ver app.py)."""
#     if request.endpoint == "actas.subir_adjuntos":
#         flash("Los archivos juntos pesan demasiado. Sube menos archivos a la vez "
#               f"(máximo {adj.MAX_BYTES // (1024 * 1024)} MB cada uno).", "error")
#         return redirect(url_for("actas.ver", acta_id=request.view_args["acta_id"]) + "#adjuntos")
#     return error

"""actas.py - Blueprint para el acta GOR-F084 V2 (guardar en BD, generar PDF y descargas)."""

import base64
import io
import json
import os
from itertools import zip_longest
from xml.sax.saxutils import escape

import psycopg2
from flask import Blueprint, current_app, jsonify, request, send_file
from PIL import Image as PILImage
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from db import get_connection

actas_bp = Blueprint("actas", __name__)

# Carpeta donde se guardan los PDF (se puede cambiar con PDF_DIR en el .env)
PDF_DIR = os.getenv("PDF_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfs_actas"))
os.makedirs(PDF_DIR, exist_ok=True)


def _item(lista, i):
    """Devuelve lista[i] o '' si la lista es más corta (evita IndexError)."""
    return lista[i] if i < len(lista) else ""


# ================== Clase Acta GOR-F084 V2 ==================
class GORF084V2:
    """Clase para generar el acta GOR-F084 V2 en PDF."""

    def __init__(self, Nombre_comite, ciudad, fecha, hora_inicio, hora_fin, lugar_enlace,
                 direccion_regional, agenda, objetivos_de_reunion, desarrollo, conclusiones,
                 compromisos_actividad_decision, compromiso_fechas, compromisos_responsables,
                 compromiso_firma_participacionVirtual, aprobacion_decisiones, AD_nombre,
                 AD_dependencia_empresa, AD_aprueba, AD_observaciones,
                 AD_firma_ParticipacionVirtual, anexos):  # AD = asistentes y aprobación decisiones
        self.nombre_comite = Nombre_comite
        self.ciudad = ciudad
        self.fecha = fecha
        self.hora_inicio = hora_inicio
        self.hora_fin = hora_fin
        self.lugar_enlace = lugar_enlace
        self.direccion_regional = direccion_regional
        self.agenda = agenda
        self.objetivo_de_reunion = objetivos_de_reunion
        self.desarrollo = desarrollo
        self.conclusiones = conclusiones
        self.compromisos_actividad_decision = compromisos_actividad_decision
        self.compromiso_fechas = compromiso_fechas
        self.compromisos_responsables = compromisos_responsables
        self.compromiso_firma_participacionVirtual = compromiso_firma_participacionVirtual
        self.aprobacion_decisiones = aprobacion_decisiones
        self.AD_nombre = AD_nombre
        self.AD_dependencia_empresa = AD_dependencia_empresa
        self.AD_aprueba = AD_aprueba
        self.AD_observaciones = AD_observaciones
        self.AD_firma_ParticipacionVirtual = AD_firma_ParticipacionVirtual
        self.anexos = anexos
        self.id = None
        self.pdf_ruta = None
        self.anexos_guardados = []

    # ---------- Crear el objeto con los datos que llegan del HTML ----------
    @classmethod
    def from_html(cls, datos):
        """Toma el JSON enviado por acta.html y devuelve el objeto 'Acta v2'."""
        return cls(
            Nombre_comite=datos.get("Nombre_comite", ""),
            ciudad=datos.get("ciudad", ""),
            fecha=datos.get("fecha", ""),
            hora_inicio=datos.get("hora_inicio"),
            hora_fin=datos.get("hora_fin"),
            lugar_enlace=datos.get("lugar_enlace", ""),
            direccion_regional=datos.get("direccion_regional", ""),
            agenda=datos.get("agenda", ""),
            objetivos_de_reunion=datos.get("objetivos_de_reunion", ""),
            desarrollo=datos.get("desarrollo", ""),
            conclusiones=datos.get("conclusiones", ""),
            compromisos_actividad_decision=datos.get("compromisos_actividad_decision", []),
            compromiso_fechas=datos.get("compromiso_fechas", []),
            compromisos_responsables=datos.get("compromisos_responsables", []),
            compromiso_firma_participacionVirtual=datos.get(
                "compromiso_firma_participacionVirtual", []),
            aprobacion_decisiones=datos.get("aprobacion_decisiones", ""),
            AD_nombre=datos.get("AD_nombre", []),
            AD_dependencia_empresa=datos.get("AD_dependencia_empresa", []),
            AD_aprueba=datos.get("AD_aprueba", []),
            AD_observaciones=datos.get("AD_observaciones", []),
            AD_firma_ParticipacionVirtual=datos.get("AD_firma_ParticipacionVirtual", []),
            anexos=datos.get("anexos", []),
        )

    # ---------- 1) Guardar en la base de datos ----------
    def guardar_en_bd(self):
        compromisos = [
            {"actividad": a, "fecha": f, "responsable": r, "firma": s}
            for a, f, r, s in zip_longest(
                self.compromisos_actividad_decision, self.compromiso_fechas,
                self.compromisos_responsables, self.compromiso_firma_participacionVirtual,
                fillvalue="")
        ]
        asistentes = [
            {"nombre": n, "dependencia": d, "aprueba": ap, "observacion": o, "firma": f}
            for n, d, ap, o, f in zip_longest(
                self.AD_nombre, self.AD_dependencia_empresa, self.AD_aprueba,
                self.AD_observaciones, self.AD_firma_ParticipacionVirtual,
                fillvalue="")
        ]

        conn = get_connection()
        try:
            # "with conn" hace commit si todo sale bien y rollback si hay error
            with conn, conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO actas (nombre_comite, ciudad, fecha, hora_inicio, hora_fin,
                        lugar_enlace, direccion_regional, agenda, objetivo_de_reunion, desarrollo,
                        conclusiones, compromisos, aprobacion_decisiones, asistentes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, (self.nombre_comite, self.ciudad, self.fecha or None,
                      self.hora_inicio or None, self.hora_fin or None,
                      self.lugar_enlace, self.direccion_regional, self.agenda,
                      self.objetivo_de_reunion, self.desarrollo, self.conclusiones,
                      json.dumps(compromisos), self.aprobacion_decisiones,
                      json.dumps(asistentes)))
                # RealDictCursor -> la fila es un diccionario, no una tupla
                self.id = cur.fetchone()["id"]

                self.anexos_guardados = []
                for anexo in self.anexos:
                    cur.execute(
                        "INSERT INTO actas_anexos (acta_id, nombre, tipo, contenido) "
                        "VALUES (%s,%s,%s,%s) RETURNING id",
                        (self.id, anexo.get("nombre"), anexo.get("tipo"),
                         psycopg2.Binary(base64.b64decode(anexo.get("base64", "")))))
                    self.anexos_guardados.append(
                        {"id": cur.fetchone()["id"], "nombre": anexo.get("nombre")})
        finally:
            conn.close()
        return self.id

    # ---------- 2) Crear el PDF (texto simple, sin decoración) ----------
    def generar_pdf(self):
        estilos = getSampleStyleSheet()
        normal = estilos["Normal"]

        def linea(etiqueta, valor):
            texto = escape(str(valor if valor is not None else "")).replace("\n", "<br/>")
            return Paragraph(f"{escape(etiqueta)}: {texto}", normal)

        historia = [Paragraph("ACTA GOR-F084 V2", normal), Spacer(1, 10)]
        historia += [
            linea("Nombre del comité o de la reunión", self.nombre_comite),
            linea("Ciudad", self.ciudad),
            linea("Fecha", self.fecha),
            linea("Hora inicio", self.hora_inicio),
            linea("Hora fin", self.hora_fin),
            linea("Lugar y/o enlace", self.lugar_enlace),
            linea("Dirección regional centro", self.direccion_regional),
            linea("Agenda o puntos para desarrollar", self.agenda),
            linea("Objetivos de la reunión", self.objetivo_de_reunion),
            linea("Desarrollo de la reunión", self.desarrollo),
            linea("Conclusiones", self.conclusiones),
            Spacer(1, 10),
            Paragraph("COMPROMISOS", normal),
        ]
        for i, act in enumerate(self.compromisos_actividad_decision):
            historia += [
                linea(f"Compromiso {i + 1} - Actividad / decisión", act),
                linea("Fecha", _item(self.compromiso_fechas, i)),
                linea("Responsable", _item(self.compromisos_responsables, i)),
                linea("Firma o participación virtual",
                      _item(self.compromiso_firma_participacionVirtual, i)),
                Spacer(1, 6),
            ]
        historia += [
            Paragraph("ASISTENTES Y APROBACIÓN DE DECISIONES", normal),
            linea("Resultado general", self.aprobacion_decisiones),
        ]
        for i, nombre in enumerate(self.AD_nombre):
            historia += [
                linea(f"Asistente {i + 1} - Nombre", nombre),
                linea("Dependencia / empresa", _item(self.AD_dependencia_empresa, i)),
                linea("Aprueba", _item(self.AD_aprueba, i)),
                linea("Observación", _item(self.AD_observaciones, i)),
                linea("Firma o participación virtual",
                      _item(self.AD_firma_ParticipacionVirtual, i)),
                Spacer(1, 6),
            ]
        historia += [
            Paragraph("ANEXOS", normal),
            linea("Archivos adjuntos", ", ".join(a.get("nombre", "") for a in self.anexos)),
            Spacer(1, 6),
        ]
        # Imágenes incrustadas (se ajustan al ancho y alto útil de la página)
        ancho_max, alto_max = 6.5 * 72, 8.5 * 72
        for anexo in self.anexos:
            historia.append(linea("Imagen", anexo.get("nombre", "")))
            try:
                crudo = base64.b64decode(anexo.get("base64", ""))
                img = PILImage.open(io.BytesIO(crudo)).convert("RGB")
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                buffer.seek(0)
                ancho, alto = img.size
                escala = min(ancho_max / ancho, alto_max / alto, 1)
                historia.append(Image(buffer, width=ancho * escala, height=alto * escala))
            except Exception:
                historia.append(linea("No se pudo incrustar la imagen", anexo.get("nombre", "")))
            historia.append(Spacer(1, 10))

        nombre_pdf = f"acta_{self.id if self.id else 'sin_id'}.pdf"
        self.pdf_ruta = os.path.join(PDF_DIR, nombre_pdf)
        SimpleDocTemplate(self.pdf_ruta, pagesize=letter).build(historia)
        return self.pdf_ruta

    # ---------- 3) Flujo completo ----------
    def procesar(self):
        """Envía los datos a la BD, crea el PDF y guarda la ruta del PDF."""
        self.guardar_en_bd()
        self.generar_pdf()

        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("UPDATE actas SET pdf_ruta=%s WHERE id=%s",
                            (self.pdf_ruta, self.id))
        finally:
            conn.close()
        return self.id, self.pdf_ruta


# ======================= rutas =======================
@actas_bp.route("/api/actas", methods=["POST"])
def recibir_acta():
    datos = request.get_json(silent=True)
    if not datos:
        return jsonify({"error": "No llegaron datos"}), 400
    try:
        acta_v2 = GORF084V2.from_html(datos)
        acta_id, pdf = acta_v2.procesar()
        return jsonify({"id": acta_id, "pdf": os.path.basename(pdf),
                        "anexos": acta_v2.anexos_guardados})
    except Exception as e:
        current_app.logger.exception("Error al procesar el acta")
        return jsonify({"error": str(e)}), 500


@actas_bp.route("/api/actas/<int:acta_id>/pdf")
def descargar_pdf(acta_id):
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pdf_ruta FROM actas WHERE id=%s", (acta_id,))
                fila = cur.fetchone()
        finally:
            conn.close()
    except psycopg2.Error as e:
        current_app.logger.exception("Error consultando el PDF")
        return jsonify({"error": str(e)}), 500

    ruta = fila["pdf_ruta"] if fila else None
    if not ruta or not os.path.exists(ruta):
        return jsonify({"error": "PDF no encontrado"}), 404
    return send_file(ruta, as_attachment=True, download_name=f"acta_{acta_id}.pdf",
                     mimetype="application/pdf")


@actas_bp.route("/api/actas/<int:acta_id>/anexos/<int:anexo_id>")
def descargar_anexo(acta_id, anexo_id):
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT nombre, tipo, contenido FROM actas_anexos "
                            "WHERE id=%s AND acta_id=%s", (anexo_id, acta_id))
                fila = cur.fetchone()
        finally:
            conn.close()
    except psycopg2.Error as e:
        current_app.logger.exception("Error consultando el anexo")
        return jsonify({"error": str(e)}), 500

    if not fila:
        return jsonify({"error": "Anexo no encontrado"}), 404
    return send_file(io.BytesIO(bytes(fila["contenido"])),
                     mimetype=fila["tipo"] or "application/octet-stream",
                     as_attachment=True, download_name=fila["nombre"])