import base64
import io
import json
import os
from itertools import zip_longest
from xml.sax.saxutils import escape

import psycopg2
from flask import Blueprint, abort, current_app, jsonify, request, send_file, session
from PIL import Image as PILImage
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from seguridad import ROLES_ACCESO_GLOBAL, creacion_requerida, login_requerido
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
    def guardar_en_bd(self, usuario_id):
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
                        conclusiones, compromisos, aprobacion_decisiones, asistentes, creado_por)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, (self.nombre_comite, self.ciudad, self.fecha or None,
                      self.hora_inicio or None, self.hora_fin or None,
                      self.lugar_enlace, self.direccion_regional, self.agenda,
                      self.objetivo_de_reunion, self.desarrollo, self.conclusiones,
                      json.dumps(compromisos), self.aprobacion_decisiones,
                      json.dumps(asistentes), usuario_id))
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
    def procesar(self, usuario_id):
        """Envía los datos a la BD, crea el PDF y guarda la ruta del PDF."""
        self.guardar_en_bd(usuario_id)
        self.generar_pdf()

        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("UPDATE actas SET pdf_ruta=%s WHERE id=%s",
                            (self.pdf_ruta, self.id))
        finally:
            conn.close()
        return self.id, self.pdf_ruta


def _puede_ver(creado_por):
    """Quien creó el acta, o los roles con acceso global."""
    return creado_por == session["usuario_id"] or session.get("rol") in ROLES_ACCESO_GLOBAL


# ======================= rutas =======================
@actas_bp.route("/api/actas", methods=["POST"])
@creacion_requerida
def recibir_acta():
    datos = request.get_json(silent=True)
    if not datos:
        return jsonify({"error": "No llegaron datos"}), 400
    try:
        acta_v2 = GORF084V2.from_html(datos)
        acta_id, pdf = acta_v2.procesar(session["usuario_id"])
        return jsonify({"id": acta_id, "pdf": os.path.basename(pdf),
                        "anexos": acta_v2.anexos_guardados})
    except Exception:
        current_app.logger.exception("Error al procesar el acta")
        return jsonify({"error": "No pudimos guardar el acta. Revisa los datos e intenta de nuevo."}), 500


@actas_bp.route("/api/actas/<int:acta_id>/pdf")
@login_requerido
def descargar_pdf(acta_id):
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pdf_ruta, creado_por FROM actas WHERE id=%s", (acta_id,))
                fila = cur.fetchone()
        finally:
            conn.close()
    except psycopg2.Error:
        current_app.logger.exception("Error consultando el PDF")
        abort(503)

    if not fila or not fila["pdf_ruta"] or not os.path.exists(fila["pdf_ruta"]):
        abort(404)
    if not _puede_ver(fila["creado_por"]):
        abort(403)
    return send_file(fila["pdf_ruta"], as_attachment=True, download_name=f"acta_{acta_id}.pdf",
                     mimetype="application/pdf")


@actas_bp.route("/api/actas/<int:acta_id>/anexos/<int:anexo_id>")
@login_requerido
def descargar_anexo(acta_id, anexo_id):
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT x.nombre, x.tipo, x.contenido, a.creado_por "
                            "FROM actas_anexos x JOIN actas a ON a.id = x.acta_id "
                            "WHERE x.id=%s AND x.acta_id=%s", (anexo_id, acta_id))
                fila = cur.fetchone()
        finally:
            conn.close()
    except psycopg2.Error:
        current_app.logger.exception("Error consultando el anexo")
        abort(503)

    if not fila:
        abort(404)
    if not _puede_ver(fila["creado_por"]):
        abort(403)
    respuesta = send_file(io.BytesIO(bytes(fila["contenido"])),
                          mimetype=fila["tipo"] or "application/octet-stream",
                          as_attachment=True, download_name=fila["nombre"] or "anexo")
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    return respuesta