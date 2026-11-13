"""
US-013 · Aporte del participante, compromisos y firma.

- Aporte: cada participante escribe su desarrollo y conclusiones (acta abierta).
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
from actas import _acceso, _entero, login_requerido, transaccion

aportes_bp = Blueprint("aportes", __name__)

MAX_TEXTO_APORTE = 5000
MAX_ACTIVIDAD = 300
MAX_BYTES_FIRMA = 2 * 1024 * 1024


def _volver(acta_id, ancla):
    return redirect(url_for("actas.ver", acta_id=acta_id) + f"#{ancla}")


# --------------------------------------------------------------------- aporte
@aportes_bp.route("/actas/<int:acta_id>/aporte", methods=["POST"])
@login_requerido
def guardar_aporte(acta_id):
    desarrollo = request.form.get("desarrollo", "").strip()
    conclusiones = request.form.get("conclusiones", "").strip()
    if len(desarrollo) > MAX_TEXTO_APORTE or len(conclusiones) > MAX_TEXTO_APORTE:
        flash(f"Cada campo admite máximo {MAX_TEXTO_APORTE} caracteres.", "error")
        return _volver(acta_id, "aporte")
    try:
        with transaccion() as cur:
            acceso = _acceso(cur, acta_id, session["usuario_id"])
            if acceso["acta"]["estado"] != "abierta":
                flash("El acta ya no está abierta: no se puede modificar tu aporte.", "error")
                return _volver(acta_id, "aporte")
            # Un aporte vacío se guarda como NULL para que el acta lo muestre "Pendiente"
            cur.execute(
                "UPDATE acta_participantes SET desarrollo = %s, conclusiones = %s "
                "WHERE acta_id = %s AND usuario_id = %s",
                (desarrollo or None, conclusiones or None, acta_id, session["usuario_id"]),
            )
            if cur.rowcount == 0:
                abort(403)  # el líder o admin que no es participante no tiene aporte
        flash("Tu aporte quedó registrado.", "ok")
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al guardar el aporte")
        flash("No pudimos guardar tu aporte. Intenta de nuevo.", "error")
    return _volver(acta_id, "aporte")


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
