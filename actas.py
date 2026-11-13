"""
Módulo de actas: crear acta y ver acta.

Reglas de permiso:
- Puede crear actas quien tenga un rol con puede_crear_acta = TRUE, o quien sea
  "Instructor líder de ficha" en al menos una ficha (rol dentro del equipo ejecutor).
- Actas de equipo ejecutor:
    * Administrador y Coordinador académico: cualquier ficha activa.
    * Los demás: solo las fichas donde son "Instructor líder de ficha".
    * Un Instructor integrante NO puede crearlas.
- Actas de "otros asuntos": cualquier usuario autorizado a crear actas.
- Solo una acta de equipo ejecutor por ficha y mes.
"""
import sys
from contextlib import contextmanager
from datetime import date, time
from functools import wraps

import psycopg2
from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_from_directory, session, url_for)

import adjuntos as adj
from db import get_connection

actas_bp = Blueprint("actas", __name__, url_prefix="/actas")

ROL_LIDER = "Instructor líder de ficha"
ROLES_TODAS_LAS_FICHAS = ("Administrador", "Coordinador académico")
CODIGO_FORMATO_DEFECTO = "GOR-F-084 v2"
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

SQL_TODAS_LAS_FICHAS = """
    SELECT f.id, f.numero, p.nombre AS programa
    FROM fichas f
    JOIN programas p ON p.id = f.programa_id
    WHERE f.activa
    ORDER BY f.numero
"""

SQL_FICHAS_LIDER = """
    SELECT DISTINCT f.id, f.numero, p.nombre AS programa
    FROM equipo_integrantes ei
    JOIN roles r ON r.id = ei.rol_id AND r.nombre = %s
    JOIN equipo_ficha ef ON ef.equipo_ejecutor_id = ei.equipo_ejecutor_id
    JOIN fichas f ON f.id = ef.ficha_id AND f.activa
    JOIN programas p ON p.id = f.programa_id
    WHERE ei.usuario_id = %s
    ORDER BY f.numero
"""


# ----------------------------------------------------------------- utilidades
@contextmanager
def transaccion():
    """Abre una conexión, confirma al terminar (o revierte si hay error) y la cierra."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    finally:
        conn.close()


def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return vista(*args, **kwargs)

    return envoltura


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def obtener_permisos(cur, usuario_id):
    """Devuelve si el usuario puede crear actas y en qué fichas puede crear actas de equipo ejecutor."""
    cur.execute(
        """
        SELECT r.nombre, r.puede_crear_acta
        FROM usuarios u
        JOIN roles r ON r.id = u.rol_id
        WHERE u.id = %s AND u.activo
        """,
        (usuario_id,),
    )
    fila = cur.fetchone()
    if fila is None:
        return {"puede_crear": False, "fichas": [], "rol": None}

    if fila["nombre"] in ROLES_TODAS_LAS_FICHAS:
        cur.execute(SQL_TODAS_LAS_FICHAS)
    else:
        cur.execute(SQL_FICHAS_LIDER, (ROL_LIDER, usuario_id))
    fichas = cur.fetchall()

    return {
        "puede_crear": bool(fila["puede_crear_acta"]) or bool(fichas),
        "fichas": fichas,
        "rol": fila["nombre"],
    }


@actas_bp.app_context_processor
def inyectar_permiso():
    """Hace disponible `puede_crear_acta` en todas las plantillas (para el menú)."""
    if "usuario_id" not in session:
        return {}
    try:
        with transaccion() as cur:
            return {"puede_crear_acta": obtener_permisos(cur, session["usuario_id"])["puede_crear"]}
    except psycopg2.Error:
        return {"puede_crear_acta": False}


def cargar_catalogos(cur):
    cur.execute("SELECT id, nombre FROM regionales ORDER BY nombre")
    regionales = cur.fetchall()
    cur.execute("SELECT id, regional_id, nombre FROM centros_formacion ORDER BY nombre")
    centros = [dict(c) for c in cur.fetchall()]
    return regionales, centros


# ------------------------------------------- US-005 · regional y centro
def errores_lugar(regional_id, centro_id, regionales, centros):
    """Revisa la regional y el centro (ya convertidos a entero) contra el catálogo."""
    if regional_id is None:
        return ["Selecciona la dirección regional."]
    if regional_id not in {r["id"] for r in regionales}:
        return ["La regional elegida no existe. Vuelve a elegirla de la lista."]

    regional_del_centro = {c["id"]: c["regional_id"] for c in centros}
    if centro_id is None:
        if regional_id not in regional_del_centro.values():
            return ["La regional elegida no tiene centros de formación registrados. Elige otra regional."]
        return ["Selecciona el centro de formación."]
    if centro_id not in regional_del_centro:
        return ["El centro de formación elegido no existe. Vuelve a elegirlo de la lista."]
    if regional_del_centro[centro_id] != regional_id:
        return ["El centro de formación no pertenece a la regional elegida."]
    return []


def lugar_a_conservar(regional_id, centro_id, regionales, centros):
    """Regional y centro que se vuelven a mostrar cuando el formulario tiene errores.

    La regional solo si existe; el centro solo si pertenece a esa regional.
    """
    regional = _entero(regional_id)
    centro = _entero(centro_id)
    if regional not in {r["id"] for r in regionales}:
        return "", ""
    if not any(c["id"] == centro and c["regional_id"] == regional for c in centros):
        return str(regional), ""
    return str(regional), str(centro)


# ---------------------------------------------------------------- formulario
def datos_iniciales(permisos):
    return {
        "tipo_acta": "equipo_ejecutor" if permisos["fichas"] else "otros_asuntos",
        "nombre_reunion": "", "ciudad": "", "fecha_reunion": "",
        "hora_inicio": "", "hora_fin": "", "lugar_enlace": "",
        "regional_id": "", "centro_id": "", "ficha_id": "", "mes": "",
        "codigo_formato": CODIGO_FORMATO_DEFECTO,
        "agenda": [], "objetivos": [],
    }


def _limpiar_lista(items):
    """Colapsa espacios y quita vacíos y repetidos (sin distinguir mayúsculas), como db.agregar_item."""
    limpios, vistos = [], set()
    for t in items:
        t = " ".join(t.split())
        if t and t.lower() not in vistos:
            vistos.add(t.lower())
            limpios.append(t)
    return limpios


def leer_formulario(form):
    texto = lambda campo: form.get(campo, "").strip()  # noqa: E731
    return {
        "tipo_acta": texto("tipo_acta"),
        "nombre_reunion": texto("nombre_reunion"),
        "ciudad": texto("ciudad"),
        "fecha_reunion": texto("fecha_reunion"),
        "hora_inicio": texto("hora_inicio"),
        "hora_fin": texto("hora_fin"),
        "lugar_enlace": texto("lugar_enlace"),
        "regional_id": texto("regional_id"),
        "centro_id": texto("centro_id"),
        "ficha_id": texto("ficha_id"),
        "mes": texto("mes"),
        "codigo_formato": texto("codigo_formato"),
        "agenda": _limpiar_lista(form.getlist("agenda")),
        "objetivos": _limpiar_lista(form.getlist("objetivos")),
    }


def validar(cur, datos, permisos, catalogo=None):
    """Valida los datos en el servidor. Devuelve (errores, valores ya convertidos).

    `catalogo` es (regionales, centros) ya cargados; si no llega, se consulta.
    """
    errores = []

    tipos_permitidos = ["otros_asuntos"] + (["equipo_ejecutor"] if permisos["fichas"] else [])
    if datos["tipo_acta"] not in tipos_permitidos:
        errores.append("Elige un tipo de acta permitido para tu rol.")

    for campo, etiqueta, maximo in (
        ("nombre_reunion", "El nombre de la reunión", 200),
        ("ciudad", "La ciudad", 100),
        ("lugar_enlace", "El lugar o enlace de la reunión", 300),
    ):
        if not datos[campo]:
            errores.append(f"{etiqueta} es obligatorio.")
        elif len(datos[campo]) > maximo:
            errores.append(f"{etiqueta} no puede superar {maximo} caracteres.")

    if len(datos["codigo_formato"]) > 30:
        errores.append("El código y versión del formato no puede superar 30 caracteres.")

    fecha = hora_inicio = hora_fin = None
    try:
        fecha = date.fromisoformat(datos["fecha_reunion"])
    except ValueError:
        errores.append("Escribe una fecha de reunión válida.")
    try:
        hora_inicio = time.fromisoformat(datos["hora_inicio"])
    except ValueError:
        errores.append("Escribe una hora de inicio válida.")
    try:
        hora_fin = time.fromisoformat(datos["hora_fin"])
    except ValueError:
        errores.append("Escribe una hora de fin válida.")
    if hora_inicio and hora_fin and hora_fin <= hora_inicio:
        errores.append("La hora de fin debe ser posterior a la hora de inicio.")

    regional_id = _entero(datos["regional_id"])
    centro_id = _entero(datos["centro_id"])
    regionales, centros = catalogo or cargar_catalogos(cur)
    errores += errores_lugar(regional_id, centro_id, regionales, centros)

    ficha_id = mes = None
    if datos["tipo_acta"] == "equipo_ejecutor":
        ficha_id = _entero(datos["ficha_id"])
        mes = _entero(datos["mes"])
        permitidas = {f["id"] for f in permisos["fichas"]}

        if ficha_id not in permitidas:
            errores.append("Selecciona una ficha en la que tengas permiso para crear actas.")
        if mes is None or not 1 <= mes <= 12:
            errores.append("Selecciona el mes del acta.")
        elif ficha_id in permitidas and fecha:
            cur.execute(
                """
                SELECT numero_acta FROM actas
                WHERE tipo_acta = 'equipo_ejecutor'
                  AND ficha_id = %s AND anio = %s AND mes = %s
                """,
                (ficha_id, fecha.year, mes),
            )
            existente = cur.fetchone()
            if existente:
                errores.append(
                    f"Ya existe un acta de esa ficha para {MESES[mes - 1].lower()} de {fecha.year} "
                    f"({existente['numero_acta']}). No se puede crear otra."
                )

    if not datos["agenda"]:
        errores.append("Agrega al menos un punto a la agenda.")
    if not datos["objetivos"]:
        errores.append("Agrega al menos un objetivo de la reunión.")
    if any(len(t) > 500 for t in datos["agenda"] + datos["objetivos"]):
        errores.append("Cada punto de agenda u objetivo puede tener máximo 500 caracteres.")

    valores = {
        "tipo_acta": datos["tipo_acta"],
        "nombre_reunion": datos["nombre_reunion"],
        "ciudad": datos["ciudad"],
        "fecha": fecha,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "lugar_enlace": datos["lugar_enlace"],
        "regional_id": regional_id,
        "centro_id": centro_id,
        "ficha_id": ficha_id,
        "mes": mes,
        "codigo_formato": datos["codigo_formato"] or None,
        "agenda": datos["agenda"],
        "objetivos": datos["objetivos"],
    }
    return errores, valores


def guardar_acta(cur, usuario_id, v):
    """Inserta el acta, su agenda/objetivos y sus participantes. Devuelve (id, numero_acta)."""
    anio = v["fecha"].year

    # Evita que dos personas obtengan el mismo consecutivo al mismo tiempo
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"acta:{v['centro_id']}:{v['ficha_id'] or 0}:{anio}",),
    )
    cur.execute(
        """
        SELECT COALESCE(MAX(consecutivo), 0) + 1 AS n
        FROM actas
        WHERE centro_id = %s AND COALESCE(ficha_id, 0) = %s AND anio = %s
        """,
        (v["centro_id"], v["ficha_id"] or 0, anio),
    )
    consecutivo = cur.fetchone()["n"]
    numero_acta = f"Acta {consecutivo}"

    cur.execute(
        """
        INSERT INTO actas
            (tipo_acta, consecutivo, anio, numero_acta, nombre_reunion, ciudad,
             fecha_reunion, hora_inicio, hora_fin, lugar_enlace, regional_id,
             centro_id, ficha_id, mes, codigo_formato, lider_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (v["tipo_acta"], consecutivo, anio, numero_acta, v["nombre_reunion"], v["ciudad"],
         v["fecha"], v["hora_inicio"], v["hora_fin"], v["lugar_enlace"], v["regional_id"],
         v["centro_id"], v["ficha_id"], v["mes"], v["codigo_formato"], usuario_id),
    )
    acta_id = cur.fetchone()["id"]

    for tipo, items in (("agenda", v["agenda"]), ("objetivo", v["objetivos"])):
        for orden, texto in enumerate(items, start=1):
            cur.execute(
                "INSERT INTO acta_items (acta_id, tipo, descripcion, orden) VALUES (%s, %s, %s, %s)",
                (acta_id, tipo, texto, orden),
            )

    # Participantes: quien crea el acta + los integrantes de los equipos de la ficha.
    # En actas de "otros asuntos" (sin ficha) solo entra el creador.
    cur.execute(
        """
        INSERT INTO acta_participantes (acta_id, usuario_id)
        SELECT %s, x.usuario_id
        FROM (
            SELECT %s::int AS usuario_id
            UNION
            SELECT ei.usuario_id
            FROM equipo_integrantes ei
            JOIN equipo_ficha ef ON ef.equipo_ejecutor_id = ei.equipo_ejecutor_id
            WHERE ef.ficha_id = %s
        ) x
        """,
        (acta_id, usuario_id, v["ficha_id"]),
    )
    return acta_id, numero_acta


# --------------------------------------------------------------------- rutas
@actas_bp.route("/crear", methods=["GET", "POST"])
@login_requerido
def crear():
    usuario_id = session["usuario_id"]
    errores = []
    try:
        with transaccion() as cur:
            permisos = obtener_permisos(cur, usuario_id)
            if not permisos["puede_crear"]:
                abort(403)
            regionales, centros = cargar_catalogos(cur)
            datos = datos_iniciales(permisos)

            if request.method == "POST":
                datos = leer_formulario(request.form)
                errores, valores = validar(cur, datos, permisos, (regionales, centros))
                if not errores:
                    acta_id, numero = guardar_acta(cur, usuario_id, valores)
                    flash(f"{numero} creada. Ya está abierta para recibir aportes.", "ok")
                    return redirect(url_for("actas.ver", acta_id=acta_id))
                datos["regional_id"], datos["centro_id"] = lugar_a_conservar(
                    datos["regional_id"], datos["centro_id"], regionales, centros)
    except psycopg2.errors.UniqueViolation:
        errores = ["No se pudo guardar: ya existe un acta para esa ficha y mes, "
                   "o alguien más la creó al mismo tiempo. Intenta de nuevo."]
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al crear el acta")
        abort(503)

    return render_template(
        "crear_acta.html",
        datos=datos, errores=errores, regionales=regionales, centros=centros,
        fichas=permisos["fichas"], puede_equipo=bool(permisos["fichas"]), meses=MESES,
    )


@actas_bp.route("/<int:acta_id>")
@login_requerido
def ver(acta_id):
    usuario_id = session["usuario_id"]
    try:
        with transaccion() as cur:
            cur.execute(
                """
                SELECT a.*, rg.nombre AS regional, c.nombre AS centro,
                       f.numero AS ficha, p.nombre AS programa,
                       u.nombre || ' ' || u.apellido AS creador
                FROM actas a
                JOIN regionales rg ON rg.id = a.regional_id
                JOIN centros_formacion c ON c.id = a.centro_id
                JOIN usuarios u ON u.id = a.lider_id
                LEFT JOIN fichas f ON f.id = a.ficha_id
                LEFT JOIN programas p ON p.id = f.programa_id
                WHERE a.id = %s
                """,
                (acta_id,),
            )
            acta = cur.fetchone()
            if acta is None:
                abort(404)

            cur.execute(
                "SELECT r.nombre FROM usuarios u JOIN roles r ON r.id = u.rol_id WHERE u.id = %s",
                (usuario_id,),
            )
            rol = cur.fetchone()["nombre"]
            cur.execute(
                "SELECT 1 FROM acta_participantes WHERE acta_id = %s AND usuario_id = %s",
                (acta_id, usuario_id),
            )
            es_participante = cur.fetchone() is not None
            if not (es_participante or acta["lider_id"] == usuario_id or rol in ROLES_TODAS_LAS_FICHAS):
                abort(403)

            cur.execute(
                "SELECT tipo, descripcion FROM acta_items WHERE acta_id = %s ORDER BY tipo, orden",
                (acta_id,),
            )
            puntos = cur.fetchall()
            cur.execute(
                """
                SELECT u.nombre, u.apellido, r.nombre AS rol, (u.id = %s) AS es_creador,
                       (p.desarrollo IS NOT NULL OR p.conclusiones IS NOT NULL) AS aporto
                FROM acta_participantes p
                JOIN usuarios u ON u.id = p.usuario_id
                JOIN roles r ON r.id = u.rol_id
                WHERE p.acta_id = %s
                ORDER BY (u.id = %s) DESC, u.apellido, u.nombre
                """,
                (acta["lider_id"], acta_id, acta["lider_id"]),
            )
            participantes = cur.fetchall()
            lista_adjuntos = adj.listar_adjuntos(cur, acta_id)
            puede_adjuntar = acta["estado"] == "abierta" and (
                es_participante or acta["lider_id"] == usuario_id)
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al ver el acta")
        abort(503)

    return render_template(
        "ver_acta.html", acta=acta, meses=MESES, participantes=participantes,
        adjuntos=lista_adjuntos, puede_adjuntar=puede_adjuntar,
        puede_gestionar_adjuntos=acta["estado"] == "abierta",
        max_mb=adj.MAX_BYTES // (1024 * 1024), max_bytes=adj.MAX_BYTES,
        max_por_persona=adj.MAX_POR_PERSONA, tipos_texto=adj.EXTENSIONES_TEXTO,
        accept=adj.ACCEPT_HTML,
        agenda=[p["descripcion"] for p in puntos if p["tipo"] == "agenda"],
        objetivos=[p["descripcion"] for p in puntos if p["tipo"] == "objetivo"],
    )


# ------------------------------------------------------- US-012 · adjuntos
def _acceso(cur, acta_id, usuario_id):
    """Datos de acceso del usuario al acta. 404 si no existe, 403 si no participa."""
    cur.execute("SELECT id, lider_id, estado FROM actas WHERE id = %s", (acta_id,))
    acta = cur.fetchone()
    if acta is None:
        abort(404)
    cur.execute(
        "SELECT r.nombre FROM usuarios u JOIN roles r ON r.id = u.rol_id WHERE u.id = %s",
        (usuario_id,),
    )
    rol = cur.fetchone()["nombre"]
    cur.execute(
        "SELECT 1 FROM acta_participantes WHERE acta_id = %s AND usuario_id = %s",
        (acta_id, usuario_id),
    )
    participa = cur.fetchone() is not None or acta["lider_id"] == usuario_id
    if not (participa or rol in ROLES_TODAS_LAS_FICHAS):
        abort(403)
    return {"acta": acta, "participa": participa, "es_lider": acta["lider_id"] == usuario_id}


@actas_bp.route("/<int:acta_id>/adjuntos", methods=["POST"])
@login_requerido
def subir_adjuntos(acta_id):
    usuario_id = session["usuario_id"]
    archivos = [f for f in request.files.getlist("archivos") if f and f.filename]
    destino = redirect(url_for("actas.ver", acta_id=acta_id) + "#adjuntos")
    if not archivos:
        flash("Selecciona al menos un archivo para adjuntar.", "error")
        return destino

    guardados, rechazados, rutas = 0, [], []
    try:
        with transaccion() as cur:
            acceso = _acceso(cur, acta_id, usuario_id)
            if not acceso["participa"]:
                abort(403)
            if acceso["acta"]["estado"] != "abierta":
                flash("El acta ya no está abierta: no se pueden adjuntar más archivos.", "error")
                return destino

            # Serializa las subidas del mismo acta para respetar el tope por persona
            cur.execute("SELECT id FROM actas WHERE id = %s FOR UPDATE", (acta_id,))
            disponibles = adj.MAX_POR_PERSONA - adj.contar_de_persona(cur, acta_id, usuario_id)

            for archivo in archivos:
                nombre = adj.nombre_para_mostrar(archivo)
                try:
                    if disponibles <= 0:
                        raise ValueError(f"ya alcanzaste el máximo de {adj.MAX_POR_PERSONA} archivos en esta acta.")
                    extension, mime, es_imagen, tamano = adj.validar_archivo(archivo)
                except ValueError as error:
                    rechazados.append(f"{nombre or 'Archivo'}: {error}")
                    continue
                guardado = adj.guardar_en_disco(archivo, extension)
                rutas.append(guardado)
                adj.insertar_adjunto(cur, acta_id, usuario_id, nombre, guardado, mime, tamano, es_imagen)
                disponibles -= 1
                guardados += 1
    except BaseException:
        for ruta in rutas:  # la transacción se revirtió: no dejes archivos huérfanos
            adj.borrar_de_disco(ruta)
        if isinstance(sys.exc_info()[1], psycopg2.Error):
            current_app.logger.exception("Error de base de datos al subir adjuntos")
            flash("No pudimos guardar los archivos. Intenta de nuevo.", "error")
            return destino
        raise

    if guardados:
        flash(f"{guardados} archivo(s) adjuntado(s).", "ok")
    for motivo in rechazados:
        flash(f"No se adjuntó {motivo}", "error")
    return destino


@actas_bp.route("/<int:acta_id>/adjuntos/<int:adjunto_id>")
@login_requerido
def descargar_adjunto(acta_id, adjunto_id):
    try:
        with transaccion() as cur:
            _acceso(cur, acta_id, session["usuario_id"])
            cur.execute(
                "SELECT nombre_original, nombre_archivo, tipo_mime, es_imagen "
                "FROM acta_adjuntos WHERE id = %s AND acta_id = %s",
                (adjunto_id, acta_id),
            )
            fila = cur.fetchone()
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al descargar el adjunto")
        abort(503)
    if fila is None:
        abort(404)

    # Las imágenes se muestran en la página; todo lo demás se descarga.
    como_descarga = (not fila["es_imagen"]) or request.args.get("descargar") == "1"
    respuesta = send_from_directory(
        adj.carpeta_subidas(), fila["nombre_archivo"], mimetype=fila["tipo_mime"],
        as_attachment=como_descarga, download_name=fila["nombre_original"],
    )
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Cache-Control"] = "private, max-age=300"
    return respuesta


@actas_bp.route("/<int:acta_id>/adjuntos/<int:adjunto_id>/eliminar", methods=["POST"])
@login_requerido
def eliminar_adjunto(acta_id, adjunto_id):
    usuario_id = session["usuario_id"]
    archivo_a_borrar = None
    try:
        with transaccion() as cur:
            acceso = _acceso(cur, acta_id, usuario_id)
            if acceso["acta"]["estado"] != "abierta":
                flash("El acta ya no está abierta: no se pueden quitar archivos.", "error")
            else:
                cur.execute(
                    "SELECT usuario_id, nombre_archivo FROM acta_adjuntos WHERE id = %s AND acta_id = %s",
                    (adjunto_id, acta_id),
                )
                fila = cur.fetchone()
                if fila is None:
                    flash("Ese archivo ya no existe.", "error")
                elif fila["usuario_id"] != usuario_id and not acceso["es_lider"]:
                    abort(403)  # solo quien lo subió o el líder del acta
                else:
                    cur.execute("DELETE FROM acta_adjuntos WHERE id = %s", (adjunto_id,))
                    archivo_a_borrar = fila["nombre_archivo"]
                    flash("Archivo eliminado.", "ok")
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al eliminar el adjunto")
        flash("No pudimos eliminar el archivo. Intenta de nuevo.", "error")
    if archivo_a_borrar:
        adj.borrar_de_disco(archivo_a_borrar)
    return redirect(url_for("actas.ver", acta_id=acta_id) + "#adjuntos")


@actas_bp.app_errorhandler(413)
def archivo_demasiado_grande(error):
    """La petición completa superó MAX_CONTENT_LENGTH (ver app.py)."""
    if request.endpoint == "actas.subir_adjuntos":
        flash("Los archivos juntos pesan demasiado. Sube menos archivos a la vez "
              f"(máximo {adj.MAX_BYTES // (1024 * 1024)} MB cada uno).", "error")
        return redirect(url_for("actas.ver", acta_id=request.view_args["acta_id"]) + "#adjuntos")
    return error
