"""
US-014 · Descarga del acta en PDF (para quien tiene acceso a ella).

- Acceso: líder, participantes y roles con acceso global (misma regla que ver el acta).
- Formato GOR-F-084 v2 (pdf_formato.py): datos generales, agenda, objetivos,
  desarrollo y conclusiones de cada participante, compromisos y asistentes con su
  firma, y las imágenes adjuntas (los demás adjuntos se listan).
- Acta abierta: se genera al momento un BORRADOR (marca de agua y pie con la hora
  en que se generó). No se guarda.
- Acta cerrada (US-013): se entrega el PDF que se guardó al cerrarla. Si el archivo
  se perdió o se alteró, se rehace desde la base de datos, donde el acta cerrada ya
  no cambia; si sale igual a la huella del cierre, se repone en disco.
"""
import hashlib
import io

import psycopg2
from flask import Blueprint, abort, current_app, send_file, send_from_directory, session

import adjuntos as adj
import pdf_formato
from actas import (PATRON_PDF, _acceso, _escribir_pdf, _pdf_intacto, datos_pdf,
                   login_requerido, transaccion)

pdf_bp = Blueprint("pdf_acta", __name__)


@pdf_bp.route("/actas/<int:acta_id>/pdf")
@login_requerido
def descargar_pdf(acta_id):
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
            borrador = acta["estado"] != "cerrada"
            if borrador:
                contenido = pdf_formato.generar_pdf_acta(datos_pdf(cur, acta_id, borrador=True))
            elif not (acta["pdf_archivo"] and _pdf_intacto(
                    adj.carpeta_subidas() / acta["pdf_archivo"], acta["pdf_sha256"])):
                # Archivo perdido (p. ej. volumen nuevo) o alterado: se rehace desde la BD
                contenido = pdf_formato.generar_pdf_acta(datos_pdf(cur, acta_id))
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al generar el PDF del acta")
        abort(503)

    nombre = pdf_formato.nombre_descarga(acta["numero_acta"], acta["nombre_reunion"])
    if borrador:
        respuesta = send_file(io.BytesIO(contenido), mimetype="application/pdf",
                              as_attachment=True, download_name=f"Borrador - {nombre}")
        respuesta.headers["Cache-Control"] = "private, no-store"  # cambia con cada aporte
    elif contenido is None:
        respuesta = send_from_directory(
            adj.carpeta_subidas(), acta["pdf_archivo"], mimetype="application/pdf",
            as_attachment=True, download_name=nombre,
        )
        respuesta.headers["Cache-Control"] = "private, max-age=300"
    else:
        # El PDF sale igual byte a byte con los mismos datos: si coincide con la huella
        # del cierre se repone en disco; si no (cambió el generador o una firma), se
        # entrega sin guardar para no tocar el acta cerrada.
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
        respuesta.headers["Cache-Control"] = "private, max-age=300"
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    return respuesta
