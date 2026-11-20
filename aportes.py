"""
US-013 · Aporte del participante, compromisos y firma.

- Aporte: cada participante escribe su desarrollo y conclusiones (acta abierta).
  Textos largos (US-020): el límite y la normalización están en aporte_texto.py.
- Compromisos: actividad, fecha, responsable (otro participante del acta) y la
  firma de quien lo registra.
- Firma: imagen JPG/PNG que la persona sube una vez y se reutiliza en los
  compromisos y en la tabla de asistentes.
"""
from datetime import date

import psycopg2
from flask import (Blueprint, abort, current_app, flash, redirect, request,
                   send_from_directory, session, url_for)

import adjuntos as adj
import aporte_texto
from actas import _acceso, _entero, _mostrar_acta, login_requerido, transaccion

aportes_bp = Blueprint("aportes", __name__)

MAX_ACTIVIDAD = 300
MAX_BYTES_FIRMA = 2 * 1024 * 1024


def _volver(acta_id, ancla):
    return redirect(url_for("actas.ver", acta_id=acta_id) + f"#{ancla}")


# --------------------------------------------------------------------- aporte
@aportes_bp.route("/actas/<int:acta_id>/aporte", methods=["POST"])
@login_requerido
def guardar_aporte(acta_id):
    """Cada participante registra o corrige su desarrollo y sus conclusiones (US-020).

    US-013: si el texto cambia, la firma (aprobación) del aporte se anula.
    """
    usuario_id = session["usuario_id"]
    aporte = aporte_texto.leer_aporte(request.form)
    errores = aporte_texto.validar_aporte(aporte)
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


# ---------------------------------------------------------------- compromisos
@aportes_bp.route("/actas/<int:acta_id>/compromisos", methods=["POST"])
@login_requerido
def agregar_compromiso(acta_id):
    usuario_id = session["usuario_id"]
    actividad = " ".join(request.form.get("actividad", "").split())
    responsable_id = _entero(request.form.get("responsable_id"))
    try:
        fecha = date.fromisoformat(request.form.get("fecha_entrega", ""))
    except ValueError:
        fecha = None

    if not actividad or len(actividad) > MAX_ACTIVIDAD:
        flash(f"Escribe la actividad (máximo {MAX_ACTIVIDAD} caracteres).", "error")
        return _volver(acta_id, "compromisos")
    if fecha is None:
        flash("Escribe una fecha de entrega válida.", "error")
        return _volver(acta_id, "compromisos")
    if responsable_id is None:
        flash("Elige el responsable del compromiso.", "error")
        return _volver(acta_id, "compromisos")

    try:
        with transaccion() as cur:
            acceso = _acceso(cur, acta_id, usuario_id)
            if not acceso["participa"]:
                abort(403)
            if acceso["acta"]["estado"] != "abierta":
                flash("El acta ya no está abierta: no se pueden agregar compromisos.", "error")
                return _volver(acta_id, "compromisos")
            cur.execute(
                "SELECT 1 FROM acta_participantes WHERE acta_id = %s AND usuario_id = %s",
                (acta_id, responsable_id),
            )
            if cur.fetchone() is None:
                flash("El responsable debe ser participante del acta.", "error")
                return _volver(acta_id, "compromisos")
            cur.execute(
                "INSERT INTO acta_compromisos "
                "(acta_id, actividad, fecha_entrega, responsable_id, completado, creado_por) "
                "VALUES (%s, %s, %s, %s, FALSE, %s)",
                (acta_id, actividad, fecha, responsable_id, usuario_id),
            )
        flash("Compromiso agregado.", "ok")
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al agregar el compromiso")
        flash("No pudimos guardar el compromiso. Intenta de nuevo.", "error")
    return _volver(acta_id, "compromisos")


@aportes_bp.route("/actas/<int:acta_id>/compromisos/<int:compromiso_id>/eliminar", methods=["POST"])
@login_requerido
def eliminar_compromiso(acta_id, compromiso_id):
    usuario_id = session["usuario_id"]
    try:
        with transaccion() as cur:
            acceso = _acceso(cur, acta_id, usuario_id)
            if acceso["acta"]["estado"] != "abierta":
                flash("El acta ya no está abierta: no se pueden quitar compromisos.", "error")
                return _volver(acta_id, "compromisos")
            cur.execute(
                "SELECT creado_por FROM acta_compromisos WHERE id = %s AND acta_id = %s",
                (compromiso_id, acta_id),
            )
            fila = cur.fetchone()
            if fila is None:
                flash("Ese compromiso ya no existe.", "error")
            elif fila["creado_por"] != usuario_id and not acceso["es_lider"]:
                abort(403)  # solo quien lo registró o el líder del acta
            else:
                cur.execute("DELETE FROM acta_compromisos WHERE id = %s", (compromiso_id,))
                flash("Compromiso eliminado.", "ok")
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al eliminar el compromiso")
        flash("No pudimos eliminar el compromiso. Intenta de nuevo.", "error")
    return _volver(acta_id, "compromisos")


# ---------------------------------------------------------------------- firma
@aportes_bp.route("/firma", methods=["POST"])
@login_requerido
def subir_firma():
    destino = request.referrer or url_for("inicio")
    archivo = request.files.get("firma")
    if not archivo or not archivo.filename:
        flash("Selecciona la imagen de tu firma.", "error")
        return redirect(destino)
    try:
        extension, mime, es_imagen, tamano = adj.validar_archivo(archivo)
        if not es_imagen:
            raise ValueError("la firma debe ser una imagen JPG o PNG.")
        if tamano > MAX_BYTES_FIRMA:
            raise ValueError("la firma pesa más de 2 MB.")
    except ValueError as error:
        flash(f"No se guardó la firma: {error}", "error")
        return redirect(destino)

    nuevo = adj.guardar_en_disco(archivo, extension)
    anterior = None
    try:
        with transaccion() as cur:
            cur.execute("SELECT firma_archivo FROM usuarios WHERE id = %s", (session["usuario_id"],))
            anterior = cur.fetchone()["firma_archivo"]
            cur.execute(
                "UPDATE usuarios SET firma_archivo = %s, firma_mime = %s WHERE id = %s",
                (nuevo, mime, session["usuario_id"]),
            )
    except psycopg2.Error:
        adj.borrar_de_disco(nuevo)
        current_app.logger.exception("Error de base de datos al guardar la firma")
        flash("No pudimos guardar tu firma. Intenta de nuevo.", "error")
        return redirect(destino)
    if anterior:
        adj.borrar_de_disco(anterior)
    flash("Tu firma quedó guardada.", "ok")
    return redirect(destino)


@aportes_bp.route("/actas/<int:acta_id>/firma/<int:usuario_id>")
@login_requerido
def ver_firma(acta_id, usuario_id):
    """Firma de un participante; solo la ve quien tiene acceso al acta."""
    try:
        with transaccion() as cur:
            _acceso(cur, acta_id, session["usuario_id"])
            cur.execute(
                "SELECT u.firma_archivo, u.firma_mime FROM usuarios u "
                "JOIN acta_participantes p ON p.usuario_id = u.id "
                "WHERE p.acta_id = %s AND u.id = %s",
                (acta_id, usuario_id),
            )
            fila = cur.fetchone()
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al leer la firma")
        abort(503)
    if fila is None or not fila["firma_archivo"]:
        abort(404)
    respuesta = send_from_directory(adj.carpeta_subidas(), fila["firma_archivo"], mimetype=fila["firma_mime"])
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Cache-Control"] = "private, no-cache"
    return respuesta
