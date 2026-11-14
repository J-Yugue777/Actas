"""
US-014 · Descarga del acta en PDF (para quien participó en ella).

- Acceso: líder, participantes y roles con acceso global (misma regla que ver el acta).
- Contenido: datos generales, agenda, objetivos, asistentes con firma, aportes,
  compromisos con firma y las imágenes adjuntas. Los demás adjuntos se listan.
"""
import re
from io import BytesIO

import psycopg2
from flask import Blueprint, abort, current_app, send_file, session
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)
from xml.sax.saxutils import escape

import adjuntos as adj
from actas import MESES, _acceso, login_requerido, transaccion

pdf_bp = Blueprint("pdf_acta", __name__)

VERDE = colors.HexColor("#39A900")  # verde institucional SENA
GRIS = colors.HexColor("#555555")
ANCHO_UTIL = letter[0] - 4 * cm

_base = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_base["Title"], fontSize=16, textColor=VERDE, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_base["Heading2"], fontSize=12, textColor=VERDE, spaceBefore=12, spaceAfter=4, keepWithNext=1)
TXT = ParagraphStyle("txt", parent=_base["BodyText"], fontSize=9.5, leading=13)
PEQ = ParagraphStyle("peq", parent=TXT, fontSize=8.5, textColor=GRIS)
CELDA = ParagraphStyle("celda", parent=TXT, fontSize=8.5, leading=11)


def _p(texto, estilo=TXT):
    """Párrafo seguro: escapa el texto y conserva los saltos de línea."""
    return Paragraph(escape(str(texto or "")).replace("\n", "<br/>"), estilo)


def _imagen(ruta, ancho_max, alto_max):
    """Imagen escalada para caber en la caja; None si no se puede leer."""
    try:
        with PILImage.open(ruta) as im:
            w, h = im.size
        factor = min(ancho_max / w, alto_max / h, 1)
        return Image(str(ruta), width=w * factor, height=h * factor)
    except Exception:
        current_app.logger.warning("No se pudo insertar la imagen %s en el PDF", ruta)
        return None


def _tabla(datos, anchos, encabezado=True):
    t = Table(datos, colWidths=anchos, repeatRows=1 if encabezado else 0)
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if encabezado:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), VERDE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    t.setStyle(TableStyle(estilo))
    return t


def _celda_firma(nombre_archivo):
    if not nombre_archivo:
        return _p("Sin firma", PEQ)
    img = _imagen(adj.carpeta_subidas() / nombre_archivo, 3 * cm, 1.3 * cm)
    return img or _p("Sin firma", PEQ)


def _pie(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRIS)
    canvas.drawString(2 * cm, 1.2 * cm, doc.title)
    canvas.drawRightString(letter[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


def cargar_datos(cur, acta_id):
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
    cur.execute("SELECT tipo, descripcion FROM acta_items WHERE acta_id = %s ORDER BY tipo, orden", (acta_id,))
    items = cur.fetchall()
    cur.execute(
        """
        SELECT u.nombre, u.apellido, r.nombre AS rol, p.desarrollo, p.conclusiones, u.firma_archivo
        FROM acta_participantes p
        JOIN usuarios u ON u.id = p.usuario_id
        JOIN roles r ON r.id = u.rol_id
        WHERE p.acta_id = %s
        ORDER BY (u.id = %s) DESC, u.apellido, u.nombre
        """,
        (acta_id, acta["lider_id"]),
    )
    participantes = cur.fetchall()
    cur.execute(
        """
        SELECT c.actividad, c.fecha_entrega, c.completado,
               COALESCE(ur.nombre || ' ' || ur.apellido, c.responsable_texto) AS responsable,
               uc.firma_archivo
        FROM acta_compromisos c
        LEFT JOIN usuarios ur ON ur.id = c.responsable_id
        LEFT JOIN usuarios uc ON uc.id = c.creado_por
        WHERE c.acta_id = %s
        ORDER BY c.fecha_entrega, c.id
        """,
        (acta_id,),
    )
    compromisos = cur.fetchall()
    cur.execute(
        "SELECT ad.nombre_original, ad.nombre_archivo, ad.es_imagen, u.nombre || ' ' || u.apellido AS autor "
        "FROM acta_adjuntos ad JOIN usuarios u ON u.id = ad.usuario_id "
        "WHERE ad.acta_id = %s ORDER BY ad.creado_en, ad.id",
        (acta_id,),
    )
    adjuntos = cur.fetchall()
    return acta, items, participantes, compromisos, adjuntos


def construir_pdf(acta, items, participantes, compromisos, adjuntos):
    """Arma el PDF en memoria y devuelve un BytesIO."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.8 * cm, bottomMargin=2 * cm,
        title=f"{acta['numero_acta']} - {acta['nombre_reunion']}", author="Actas SENA",
    )
    h = []
    h.append(_p("SERVICIO NACIONAL DE APRENDIZAJE SENA", PEQ))
    h.append(Paragraph(escape(f"{acta['numero_acta']} · {acta['nombre_reunion']}"), H1))
    if acta["codigo_formato"]:
        h.append(_p(f"Formato {acta['codigo_formato']}", PEQ))

    filas = [
        ("Tipo de acta", "Equipo ejecutor" if acta["tipo_acta"] == "equipo_ejecutor" else "Otros asuntos"),
        ("Ciudad y fecha", f"{acta['ciudad']}, {acta['fecha_reunion'].strftime('%d/%m/%Y')}"),
        ("Horario", f"{acta['hora_inicio'].strftime('%H:%M')} a {acta['hora_fin'].strftime('%H:%M')}"),
        ("Lugar o enlace", acta["lugar_enlace"]),
        ("Regional", acta["regional"]),
        ("Centro de formación", acta["centro"]),
    ]
    if acta["ficha"]:
        filas.insert(1, ("Ficha", f"{acta['ficha']} — {acta['programa']}"))
        filas.insert(2, ("Mes", f"{MESES[acta['mes'] - 1]} de {acta['anio']}"))
    filas.append(("Creada por", acta["creador"]))
    filas.append(("Estado", acta["estado"].capitalize()))
    h.append(Spacer(1, 6))
    h.append(_tabla([[_p(k, CELDA), _p(v, CELDA)] for k, v in filas],
                    [4.5 * cm, ANCHO_UTIL - 4.5 * cm], encabezado=False))

    for tipo, titulo in (("agenda", "Agenda / puntos a desarrollar"), ("objetivo", "Objetivos de la reunión")):
        h.append(Paragraph(titulo, H2))
        textos = [i["descripcion"] for i in items if i["tipo"] == tipo]
        if textos:
            for n, t in enumerate(textos, 1):
                h.append(_p(f"{n}. {t}"))
        else:
            h.append(_p("Sin elementos.", PEQ))

    h.append(Paragraph("Asistentes", H2))
    h.append(_tabla(
        [[_p("Nombre", CELDA), _p("Rol", CELDA), _p("Firma", CELDA)]] +
        [[_p(f"{p['nombre']} {p['apellido']}", CELDA), _p(p["rol"], CELDA), _celda_firma(p["firma_archivo"])]
         for p in participantes],
        [7 * cm, 5.5 * cm, ANCHO_UTIL - 12.5 * cm],
    ))
    # el texto del encabezado de las tablas debe verse blanco
    h[-1].setStyle(TableStyle([("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))

    h.append(Paragraph("Aportes de los participantes", H2))
    hay_aportes = False
    for p in participantes:
        if p["desarrollo"] or p["conclusiones"]:
            hay_aportes = True
            bloque = [_p(f"{p['nombre']} {p['apellido']}", ParagraphStyle("b", parent=TXT, fontName="Helvetica-Bold"))]
            if p["desarrollo"]:
                bloque += [_p("Desarrollo", PEQ), _p(p["desarrollo"])]
            if p["conclusiones"]:
                bloque += [_p("Conclusiones", PEQ), _p(p["conclusiones"])]
            bloque.append(Spacer(1, 6))
            h.append(KeepTogether(bloque[:3]))
            h.extend(bloque[3:])
    if not hay_aportes:
        h.append(_p("Ningún participante ha registrado su aporte.", PEQ))

    h.append(Paragraph("Compromisos", H2))
    if compromisos:
        h.append(_tabla(
            [[_p(x, CELDA) for x in ("Actividad", "Fecha", "Responsable", "Firma")]] +
            [[_p(c["actividad"], CELDA), _p(c["fecha_entrega"].strftime("%d/%m/%Y"), CELDA),
              _p(c["responsable"] or "Sin asignar", CELDA), _celda_firma(c["firma_archivo"])]
             for c in compromisos],
            [6.5 * cm, 2.4 * cm, 4.2 * cm, ANCHO_UTIL - 13.1 * cm],
        ))
        h[-1].setStyle(TableStyle([("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
    else:
        h.append(_p("Sin compromisos.", PEQ))

    h.append(Paragraph("Anexos", H2))
    if not adjuntos:
        h.append(_p("Sin archivos adjuntos.", PEQ))
    otros = [a for a in adjuntos if not a["es_imagen"]]
    for a in adjuntos:
        if not a["es_imagen"]:
            continue
        img = _imagen(adj.carpeta_subidas() / a["nombre_archivo"], ANCHO_UTIL, 9 * cm)
        if img:
            h.append(KeepTogether([img, _p(f"{a['nombre_original']} · {a['autor']}", PEQ), Spacer(1, 8)]))
        else:
            otros.append(a)
    if otros:
        h.append(_p("Documentos adjuntos aparte:", PEQ))
        for a in otros:
            h.append(_p(f"• {a['nombre_original']} ({a['autor']})"))

    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    buf.seek(0)
    return buf


@pdf_bp.route("/actas/<int:acta_id>/pdf")
@login_requerido
def descargar_pdf(acta_id):
    try:
        with transaccion() as cur:
            _acceso(cur, acta_id, session["usuario_id"])  # 404 si no existe, 403 si no participa
            datos = cargar_datos(cur, acta_id)
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos al generar el PDF")
        abort(503)

    acta = datos[0]
    nombre = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{acta['numero_acta']}_{acta['fecha_reunion']:%Y-%m-%d}")
    respuesta = send_file(construir_pdf(*datos), mimetype="application/pdf",
                          as_attachment=True, download_name=f"{nombre}.pdf")
    respuesta.headers["Cache-Control"] = "private, no-store"
    return respuesta
