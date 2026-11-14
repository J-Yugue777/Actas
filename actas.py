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
import hashlib
import io
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import date, time
from functools import wraps

import psycopg2
from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)
from werkzeug.exceptions import HTTPException

import adjuntos as adj
import aportes
import pdf_acta
from db import get_connection

actas_bp = Blueprint("actas", __name__, url_prefix="/actas")
actas_bp.add_app_template_filter(aportes.miles, "miles")  # {{ 50000|miles }} -> 50.000

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


def validar(cur, datos, permisos):
    """Valida los datos en el servidor. Devuelve (errores, valores ya convertidos)."""
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
    if not regional_id or not centro_id:
        errores.append("Selecciona la regional y el centro de formación.")
    else:
        cur.execute(
            "SELECT 1 FROM centros_formacion WHERE id = %s AND regional_id = %s",
            (centro_id, regional_id),
        )
        if cur.fetchone() is None:
            errores.append("El centro de formación no pertenece a la regional elegida.")

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
                errores, valores = validar(cur, datos, permisos)
                if not errores:
                    acta_id, numero = guardar_acta(cur, usuario_id, valores)
                    flash(f"{numero} creada. Ya está abierta para recibir aportes.", "ok")
                    return redirect(url_for("actas.ver", acta_id=acta_id))
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


def listar_participantes(cur, acta_id, lider_id):
    """Participantes del acta (primero el líder) con su aporte y su firma (US-013).

    Las fechas vienen en hora de Colombia, sin zona, listas para strftime.
    """
    cur.execute(
        """
        SELECT p.usuario_id, u.nombre, u.apellido, r.nombre AS rol, (u.id = %s) AS es_creador,
               (p.desarrollo IS NOT NULL OR p.conclusiones IS NOT NULL) AS aporto,
               p.desarrollo, p.conclusiones,
               p.aporte_actualizado_en AT TIME ZONE 'America/Bogota' AS aporte_actualizado_en,
               p.firmado_en AT TIME ZONE 'America/Bogota' AS firmado_en
        FROM acta_participantes p
        JOIN usuarios u ON u.id = p.usuario_id
        JOIN roles r ON r.id = u.rol_id
        WHERE p.acta_id = %s
        ORDER BY (u.id = %s) DESC, u.apellido, u.nombre, u.id
        """,
        (lider_id, acta_id, lider_id),
    )
    return cur.fetchall()


def faltantes_cierre(participantes):
    """Quiénes impiden cerrar el acta y qué les falta (RN: cierre solo con todos firmados).

    [{'nombre': 'Sara Segunda', 'falta': 'aporte y firma'}, ...] en el orden de la tabla.
    """
    faltan = []
    for p in participantes:
        falta = [que for que, listo in (("aporte", p["aporto"]), ("firma", p["firmado_en"])) if not listo]
        if falta:
            faltan.append({"nombre": f"{p['nombre']} {p['apellido']}", "falta": " y ".join(falta)})
    return faltan


def texto_faltantes(faltantes):
    """'Iván Integrante (firma), Sara Segunda (aporte y firma)'."""
    return ", ".join(f"{f['nombre']} ({f['falta']})" for f in faltantes)


def contexto_ver(cur, acta_id, usuario_id):
    """Datos de la plantilla ver_acta.html. 404 si el acta no existe, 403 si no tiene acceso."""
    cur.execute(
        """
        SELECT a.*, rg.nombre AS regional, c.nombre AS centro,
               f.numero AS ficha, p.nombre AS programa,
               u.nombre || ' ' || u.apellido AS creador,
               a.cerrado_en AT TIME ZONE 'America/Bogota' AS cerrado_local,
               uc.nombre || ' ' || uc.apellido AS cerrado_por_nombre
        FROM actas a
        JOIN regionales rg ON rg.id = a.regional_id
        JOIN centros_formacion c ON c.id = a.centro_id
        JOIN usuarios u ON u.id = a.lider_id
        LEFT JOIN fichas f ON f.id = a.ficha_id
        LEFT JOIN programas p ON p.id = f.programa_id
        LEFT JOIN usuarios uc ON uc.id = a.cerrado_por
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
    participantes = listar_participantes(cur, acta_id, acta["lider_id"])
    lista_adjuntos = adj.listar_adjuntos(cur, acta_id)
    puede_adjuntar = acta["estado"] == "abierta" and (
        es_participante or acta["lider_id"] == usuario_id)
    mio = next((p for p in participantes if p["usuario_id"] == usuario_id), None)

    return dict(
        acta=acta, meses=MESES, participantes=participantes,
        adjuntos=lista_adjuntos, puede_adjuntar=puede_adjuntar,
        puede_gestionar_adjuntos=acta["estado"] == "abierta",
        max_mb=adj.MAX_BYTES // (1024 * 1024), max_bytes=adj.MAX_BYTES,
        max_por_persona=adj.MAX_POR_PERSONA, tipos_texto=adj.EXTENSIONES_TEXTO,
        accept=adj.ACCEPT_HTML,
        agenda=[p["descripcion"] for p in puntos if p["tipo"] == "agenda"],
        objetivos=[p["descripcion"] for p in puntos if p["tipo"] == "objetivo"],
        # US-020: el formulario "Mi aporte" solo es para participantes con el acta abierta
        puede_aportar=acta["estado"] == "abierta" and es_participante,
        aporte={c: mio[c] if mio else None for c in aportes.CAMPOS},
        aporte_guardado_en=mio["aporte_actualizado_en"] if mio else None,
        errores_aporte=[], max_aporte=aportes.MAX_LARGO_APORTE,
        # US-013: firma del aporte guardado (no del texto que se esté editando) y cierre
        mi_aporto=bool(mio and mio["aporto"]), mi_firma=mio["firmado_en"] if mio else None,
        firmados=sum(1 for p in participantes if p["firmado_en"]),
        faltantes=faltantes_cierre(participantes),
        panel_cierre=acta["estado"] == "abierta" and acta["lider_id"] == usuario_id,
    )


def _mostrar_acta(acta_id, usuario_id, estado_http=200, **cambios):
    try:
        with transaccion() as cur:
            contexto = contexto_ver(cur, acta_id, usuario_id)
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al ver el acta")
        abort(503)
    contexto.update(cambios)
    return render_template("ver_acta.html", **contexto), estado_http


@actas_bp.route("/<int:acta_id>")
@login_requerido
def ver(acta_id):
    return _mostrar_acta(acta_id, session["usuario_id"])


# ------------------------------------------- US-020 · aporte del participante
@actas_bp.route("/<int:acta_id>/aporte", methods=["POST"])
@login_requerido
def guardar_aporte(acta_id):
    """Cada participante registra o corrige su desarrollo y sus conclusiones."""
    usuario_id = session["usuario_id"]
    aporte = aportes.leer_aporte(request.form)
    errores = aportes.validar_aporte(aporte)
    abierta = guardado = firma_anulada = firma_conservada = False
    try:
        with transaccion() as cur:
            _acceso(cur, acta_id, usuario_id)  # 404 si no existe, 403 si no tiene acceso
            # Bloquea el acta hasta terminar: nadie la cierra a mitad del guardado
            cur.execute("SELECT estado FROM actas WHERE id = %s FOR SHARE", (acta_id,))
            abierta = cur.fetchone()["estado"] == "abierta"
            # Solo escribe quien tiene fila de participante (el líder también la necesita);
            # Administrador y Coordinador que no participan solo leen. 403 sea cual sea el texto.
            cur.execute(
                "SELECT desarrollo, conclusiones, firmado_en FROM acta_participantes "
                "WHERE acta_id = %s AND usuario_id = %s FOR UPDATE",
                (acta_id, usuario_id),
            )
            fila = cur.fetchone()
            if fila is None:
                abort(403)
            if abierta and not errores:
                # US-013: la firma aprueba un texto; si el texto cambia, la firma se anula
                cambio = (fila["desarrollo"], fila["conclusiones"]) != (
                    aporte["desarrollo"], aporte["conclusiones"])
                firma_anulada = cambio and fila["firmado_en"] is not None
                firma_conservada = not cambio and fila["firmado_en"] is not None
                if cambio:  # el mismo texto no se reescribe: conserva la hora y la firma
                    cur.execute(
                        """
                        UPDATE acta_participantes
                        SET desarrollo = %s, conclusiones = %s, aporte_actualizado_en = now(),
                            firmado_en = NULL
                        WHERE acta_id = %s AND usuario_id = %s
                        """,
                        (aporte["desarrollo"], aporte["conclusiones"], acta_id, usuario_id),
                    )
                guardado = True
    except psycopg2.errors.ObjectNotInPrerequisiteState:
        abierta = False  # el trigger de US-013 lo rechazó: el acta ya está cerrada
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al guardar el aporte")
        errores = ["No pudimos guardar tu aporte. Tu texto sigue aquí: intenta de nuevo."]
        return _mostrar_acta(acta_id, usuario_id, 503, aporte=aporte, errores_aporte=errores)

    if not abierta:
        flash("El acta ya no está abierta: no se puede registrar ni cambiar el aporte.", "error")
        return redirect(url_for("actas.ver", acta_id=acta_id))
    if guardado:
        # aporte_ok/aporte_error se pintan dentro de #mi-aporte, a la vista al llegar al ancla
        if firma_conservada:
            flash("Tu aporte no cambió: tu firma sigue vigente.", "aporte_ok")
        else:
            flash("Tu aporte quedó guardado.", "aporte_ok")
        if firma_anulada:
            flash("Tu aporte cambió: vuelve a firmarlo. La firma anterior quedó anulada.", "aporte_error")
        return redirect(url_for("actas.ver", acta_id=acta_id) + "#mi-aporte")
    # Error de validación: no se redirige, para no perder lo que la persona escribió
    return _mostrar_acta(acta_id, usuario_id, 400, aporte=aporte, errores_aporte=errores)


# ---------------------------------------- US-013 · firma del aporte y cierre
@actas_bp.route("/<int:acta_id>/firmar", methods=["POST"])
@login_requerido
def firmar(acta_id):
    """El participante firma su aporte guardado: firmar es aprobar el acta."""
    usuario_id = session["usuario_id"]
    destino = redirect(url_for("actas.ver", acta_id=acta_id) + "#mi-aporte")
    try:
        with transaccion() as cur:
            _acceso(cur, acta_id, usuario_id)  # 404 si no existe, 403 si no tiene acceso
            # Como al guardar el aporte: nadie cierra el acta a mitad de la firma
            cur.execute("SELECT estado FROM actas WHERE id = %s FOR SHARE", (acta_id,))
            abierta = cur.fetchone()["estado"] == "abierta"
            cur.execute(
                "SELECT desarrollo, conclusiones, firmado_en FROM acta_participantes "
                "WHERE acta_id = %s AND usuario_id = %s FOR UPDATE",
                (acta_id, usuario_id),
            )
            fila = cur.fetchone()
            if fila is None:
                abort(403)  # solo firman los participantes
            if not abierta:
                flash("El acta ya está cerrada: no se puede firmar.", "error")
                return redirect(url_for("actas.ver", acta_id=acta_id))
            if fila["desarrollo"] is None and fila["conclusiones"] is None:
                aviso = ("Guarda tu aporte antes de firmarlo.", "aporte_error")
            elif fila["firmado_en"] is not None:
                aviso = ("Tu aporte ya estaba firmado.", "aporte_ok")
            else:
                cur.execute(
                    "UPDATE acta_participantes SET firmado_en = now() "
                    "WHERE acta_id = %s AND usuario_id = %s",
                    (acta_id, usuario_id),
                )
                aviso = ("Firmaste tu aporte: con eso apruebas el acta.", "aporte_ok")
    except psycopg2.errors.ObjectNotInPrerequisiteState:
        flash("El acta ya está cerrada: no se puede firmar.", "error")
        return redirect(url_for("actas.ver", acta_id=acta_id))
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al firmar el aporte")
        aviso = ("No pudimos registrar tu firma. Intenta de nuevo.", "aporte_error")
    flash(*aviso)  # después del COMMIT: no anuncia una firma que no quedó guardada
    return destino


def datos_pdf(cur, acta_id, cerrado_por=None):
    """Diccionario para pdf_acta.generar_pdf_acta con los datos del acta en la BD.

    Al cerrar se pasa `cerrado_por` y la hora es now(): dentro de la transacción es la
    misma que queda en actas.cerrado_en, así un PDF regenerado después dice lo mismo.
    """
    cur.execute(
        """
        SELECT a.numero_acta, a.nombre_reunion, a.ciudad, a.fecha_reunion, a.hora_inicio,
               a.hora_fin, a.lugar_enlace, a.tipo_acta, a.anio, a.mes, a.codigo_formato,
               a.lider_id, rg.nombre AS regional, c.nombre AS centro,
               f.numero AS ficha, pr.nombre AS programa,
               to_char(CASE WHEN a.estado = 'cerrada' THEN a.cerrado_en ELSE now() END
                       AT TIME ZONE 'America/Bogota', 'DD/MM/YYYY HH24:MI:SS') AS cerrado_en,
               uc.nombre || ' ' || uc.apellido AS cerrado_por
        FROM actas a
        JOIN regionales rg ON rg.id = a.regional_id
        JOIN centros_formacion c ON c.id = a.centro_id
        LEFT JOIN fichas f ON f.id = a.ficha_id
        LEFT JOIN programas pr ON pr.id = f.programa_id
        LEFT JOIN usuarios uc ON uc.id = COALESCE(a.cerrado_por, %s)
        WHERE a.id = %s
        """,
        (cerrado_por, acta_id),
    )
    a = cur.fetchone()
    cur.execute(
        "SELECT tipo, descripcion FROM acta_items WHERE acta_id = %s ORDER BY tipo, orden, id",
        (acta_id,),
    )
    puntos = cur.fetchall()
    participantes = listar_participantes(cur, acta_id, a["lider_id"])
    cur.execute(
        """
        SELECT c.actividad, c.fecha_entrega,
               COALESCE(ur.nombre || ' ' || ur.apellido, c.responsable_texto, 'Sin asignar') AS responsable,
               p.firmado_en AT TIME ZONE 'America/Bogota' AS firmado_en
        FROM acta_compromisos c
        LEFT JOIN usuarios ur ON ur.id = c.responsable_id
        LEFT JOIN acta_participantes p ON p.acta_id = c.acta_id AND p.usuario_id = c.responsable_id
        WHERE c.acta_id = %s
        ORDER BY c.fecha_entrega, c.id
        """,
        (acta_id,),
    )
    compromisos = cur.fetchall()
    cur.execute(
        "SELECT nombre_original, nombre_archivo, tamano_bytes, es_imagen FROM acta_adjuntos "
        "WHERE acta_id = %s ORDER BY creado_en, id",
        (acta_id,),
    )
    carpeta = adj.carpeta_subidas()
    firma = lambda f: f"Firmado electrónicamente el {f:%d/%m/%Y %H:%M:%S}" if f else None  # noqa: E731

    return {
        "numero_acta": a["numero_acta"],
        "codigo_formato": a["codigo_formato"] or CODIGO_FORMATO_DEFECTO,
        "nombre_reunion": a["nombre_reunion"],
        "ciudad": a["ciudad"],
        "fecha": a["fecha_reunion"].strftime("%d/%m/%Y"),
        "hora_inicio": a["hora_inicio"].strftime("%H:%M"),
        "hora_fin": a["hora_fin"].strftime("%H:%M"),
        "lugar_enlace": a["lugar_enlace"],
        "regional": a["regional"],
        "centro": a["centro"],
        "tipo_acta": "Equipo ejecutor" if a["tipo_acta"] == "equipo_ejecutor" else "Otros asuntos",
        "ficha": a["ficha"],
        "programa": a["programa"],
        "mes": f"{MESES[a['mes'] - 1]} de {a['anio']}" if a["mes"] else None,
        "agenda": [p["descripcion"] for p in puntos if p["tipo"] == "agenda"],
        "objetivos": [p["descripcion"] for p in puntos if p["tipo"] == "objetivo"],
        "participantes": [{
            "nombre": f"{p['nombre']} {p['apellido']}", "rol": p["rol"],
            "desarrollo": p["desarrollo"], "conclusiones": p["conclusiones"],
            "firmado_en": f"{p['firmado_en']:%d/%m/%Y %H:%M:%S}" if p["firmado_en"] else None,
        } for p in participantes],
        "compromisos": [{
            "actividad": c["actividad"], "fecha": c["fecha_entrega"].strftime("%d/%m/%Y"),
            "responsable": c["responsable"], "firma": firma(c["firmado_en"]),
        } for c in compromisos],
        "anexos": [{
            "nombre": f["nombre_original"], "tamano_bytes": f["tamano_bytes"],
            "es_imagen": f["es_imagen"], "ruta": str(carpeta / f["nombre_archivo"]),
        } for f in cur.fetchall()],
        "cerrado_en": a["cerrado_en"],
        "cerrado_por": a["cerrado_por"],
    }


# Nombre con que se guarda el PDF del cierre (aleatorio, sin datos del usuario)
PATRON_PDF = re.compile(r"acta-\d+-[0-9a-f]{32}\.pdf")


def _escribir_pdf(nombre, contenido):
    """Guarda el PDF en la carpeta de subidas sin dejar archivos a medias (temporal + rename)."""
    destino = adj.carpeta_subidas() / nombre
    temporal = destino.with_name(f".{nombre}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporal, "xb") as archivo:
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, destino)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise


def _pdf_intacto(ruta, sha256):
    """True si el PDF está en disco y su huella es la que se guardó al cerrar."""
    huella = hashlib.sha256()
    try:
        with open(ruta, "rb") as archivo:
            for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
                huella.update(bloque)
    except OSError:
        return False
    return huella.hexdigest() == (sha256 or "").strip()


@actas_bp.route("/<int:acta_id>/cerrar", methods=["POST"])
@login_requerido
def cerrar(acta_id):
    """El líder cierra el acta cuando todos aportaron y firmaron: genera el PDF y la bloquea."""
    usuario_id = session["usuario_id"]
    ver_acta = url_for("actas.ver", acta_id=acta_id)
    archivo = None
    try:
        with transaccion() as cur:
            if not _acceso(cur, acta_id, usuario_id)["es_lider"]:
                abort(403)  # solo el líder del acta la cierra
            # FOR UPDATE: espera a quien esté guardando o firmando, y lo que llegue
            # después espera al cierre (y lo rechaza el trigger de la migración US-013)
            cur.execute("SELECT estado FROM actas WHERE id = %s FOR UPDATE", (acta_id,))
            if cur.fetchone()["estado"] == "cerrada":
                flash("El acta ya estaba cerrada.", "error")
                return redirect(ver_acta)
            participantes = listar_participantes(cur, acta_id, usuario_id)
            faltantes = faltantes_cierre(participantes)
            if faltantes:  # decisión del equipo: se bloquea el cierre, no solo se advierte
                flash(f"No se puede cerrar el acta todavía. Falta: {texto_faltantes(faltantes)}.",
                      "cierre_error")
                return redirect(ver_acta + "#cierre")
            if not participantes:
                flash("El acta no tiene participantes que la aprueben.", "cierre_error")
                return redirect(ver_acta + "#cierre")

            contenido = pdf_acta.generar_pdf_acta(datos_pdf(cur, acta_id, cerrado_por=usuario_id))
            archivo = f"acta-{acta_id}-{uuid.uuid4().hex}.pdf"
            _escribir_pdf(archivo, contenido)
            # now() es la hora de inicio de la transacción: la misma que dice el PDF
            cur.execute(
                """
                UPDATE actas
                SET estado = 'cerrada', cerrado_en = now(), cerrado_por = %s,
                    pdf_archivo = %s, pdf_sha256 = %s
                WHERE id = %s
                """,
                (usuario_id, archivo, hashlib.sha256(contenido).hexdigest(), acta_id),
            )
    except BaseException as error:
        if archivo:  # la transacción se revirtió: no dejes el PDF huérfano
            adj.borrar_de_disco(archivo)
        if isinstance(error, HTTPException) or not isinstance(error, Exception):
            raise
        if isinstance(error, psycopg2.Error):
            current_app.logger.exception("Error de base de datos al cerrar el acta")
            flash("No pudimos cerrar el acta. Intenta de nuevo.", "cierre_error")
        else:  # el PDF no se pudo generar o guardar en disco
            current_app.logger.exception("No se pudo generar o guardar el PDF del acta")
            flash("No pudimos generar el PDF, así que el acta sigue abierta. Intenta de nuevo.",
                  "cierre_error")
        return redirect(ver_acta + "#cierre")

    flash("Acta cerrada. Ya no admite cambios y su PDF está listo para descargar.", "ok")
    return redirect(ver_acta)


@actas_bp.route("/<int:acta_id>/pdf")
@login_requerido
def descargar_pdf(acta_id):
    """PDF del acta cerrada, para cualquiera con acceso al acta."""
    contenido = None
    try:
        with transaccion() as cur:
            _acceso(cur, acta_id, session["usuario_id"])  # 404 si no existe, 403 si no tiene acceso
            cur.execute(
                "SELECT numero_acta, nombre_reunion, estado, pdf_archivo, pdf_sha256 "
                "FROM actas WHERE id = %s",
                (acta_id,),
            )
            acta = cur.fetchone()
            if acta["estado"] != "cerrada":
                abort(404)  # el PDF existe solo desde el cierre
            if not (acta["pdf_archivo"] and _pdf_intacto(
                    adj.carpeta_subidas() / acta["pdf_archivo"], acta["pdf_sha256"])):
                # Archivo perdido (p. ej. volumen nuevo) o alterado: se rehace desde la BD,
                # donde el acta cerrada ya no cambia
                contenido = pdf_acta.generar_pdf_acta(datos_pdf(cur, acta_id))
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al descargar el PDF del acta")
        abort(503)

    nombre = pdf_acta.nombre_descarga(acta["numero_acta"], acta["nombre_reunion"])
    if contenido is None:
        respuesta = send_from_directory(
            adj.carpeta_subidas(), acta["pdf_archivo"], mimetype="application/pdf",
            as_attachment=True, download_name=nombre,
        )
    else:
        # El PDF sale igual byte a byte con los mismos datos: si coincide con la huella
        # del cierre se repone en disco; si no (cambió el generador), se entrega sin guardar
        # para no tocar el acta cerrada.
        if (acta["pdf_archivo"] and PATRON_PDF.fullmatch(acta["pdf_archivo"])
                and hashlib.sha256(contenido).hexdigest() == acta["pdf_sha256"]):
            try:
                _escribir_pdf(acta["pdf_archivo"], contenido)
                current_app.logger.warning("PDF del acta %s repuesto en disco", acta_id)
            except OSError:
                current_app.logger.exception("No se pudo reponer el PDF del acta %s", acta_id)
        else:
            current_app.logger.warning("PDF del acta %s regenerado distinto al del cierre: "
                                       "se entrega sin guardarlo", acta_id)
        respuesta = send_file(io.BytesIO(contenido), mimetype="application/pdf",
                              as_attachment=True, download_name=nombre)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Cache-Control"] = "private, max-age=300"
    return respuesta


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
        if isinstance(sys.exc_info()[1], psycopg2.errors.ObjectNotInPrerequisiteState):
            # US-013: el acta se cerró mientras se subían los archivos
            flash("El acta ya no está abierta: no se pueden adjuntar más archivos.", "error")
            return destino
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
    except psycopg2.errors.ObjectNotInPrerequisiteState:
        archivo_a_borrar = None  # US-013: el acta se cerró en ese momento; el archivo se queda
        flash("El acta ya no está abierta: no se pueden quitar archivos.", "error")
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al eliminar el adjunto")
        flash("No pudimos eliminar el archivo. Intenta de nuevo.", "error")
    if archivo_a_borrar:
        adj.borrar_de_disco(archivo_a_borrar)
    return redirect(url_for("actas.ver", acta_id=acta_id) + "#adjuntos")


@actas_bp.app_errorhandler(413)
def archivo_demasiado_grande(error):
    """La petición completa superó MAX_CONTENT_LENGTH o MAX_FORM_MEMORY_SIZE (ver app.py)."""
    if request.endpoint == "actas.guardar_aporte":
        flash("Tu aporte es demasiado grande para enviarlo. Recorta el texto: máximo "
              f"{aportes.miles(aportes.MAX_LARGO_APORTE)} caracteres en el desarrollo y otros tantos "
              "en las conclusiones.", "aporte_error")
        return redirect(url_for("actas.ver", acta_id=request.view_args["acta_id"]) + "#mi-aporte")
    if request.endpoint == "actas.subir_adjuntos":
        flash("Los archivos juntos pesan demasiado. Sube menos archivos a la vez "
              f"(máximo {adj.MAX_BYTES // (1024 * 1024)} MB cada uno).", "error")
        return redirect(url_for("actas.ver", acta_id=request.view_args["acta_id"]) + "#adjuntos")
    return error
