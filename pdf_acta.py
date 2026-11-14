"""
US-013 · PDF del acta con el formato vigente GOR-F-084 v2.

generar_pdf_acta(datos) es una función pura: recibe un diccionario y devuelve los
bytes del PDF, sin Flask ni base de datos (actas.datos_pdf arma el diccionario).

- Determinista: los mismos datos dan exactamente los mismos bytes (invariant=1; por
  eso la fecha interna del archivo es fija y la fecha real del cierre va en el pie).
  Así un PDF perdido se puede regenerar y comparar con actas.pdf_sha256.
- Los textos largos (hasta 50.000 caracteres por campo, US-020) van en párrafos que
  se parten entre páginas, nunca en celdas de tabla: una fila más alta que la página
  hace fallar a reportlab (LayoutError).
- Tipografía Helvetica (fuente estándar del PDF, juego Latin-1/WinAnsi): tildes, eñes,
  ¿ ¡, comillas tipográficas, € y — se ven bien. Lo que está fuera de ese juego
  (emoji, letras griegas, chino...) puede salir como un cuadro o no verse; para eso
  habría que incrustar una fuente TrueType.

Claves de `datos` (texto ya formateado, salvo donde se indica otra cosa):
    numero_acta, codigo_formato, nombre_reunion, ciudad, fecha, hora_inicio, hora_fin,
    lugar_enlace, regional, centro, tipo_acta,
    ficha, programa, mes: solo en actas de equipo ejecutor (None si no aplica),
    agenda, objetivos: listas de textos,
    participantes: [{nombre, rol, desarrollo, conclusiones, firmado_en}],
    compromisos: [{actividad, fecha, responsable, firma}],
    anexos: [{nombre, tamano_bytes (int), es_imagen (bool), ruta o contenido (bytes)}],
    cerrado_en ('dd/mm/aaaa hh:mm:ss' o None), cerrado_por,
    logo: ruta del logo (opcional; si falta se usa static/img/logo-sena-color.png).
"""
import io
import math
import os
import re
import unicodedata
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from PIL import ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

LOGO_DEFECTO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "static", "img", "logo-sena-color.png")

ANCHO, ALTO = letter
MARGEN = 2 * cm
ANCHO_UTIL = ANCHO - 2 * MARGEN
ALTO_MAX_IMAGEN = 9 * cm
MAX_LADO_IMAGEN = 1600          # px: de sobra para 17 cm a ~230 ppp
MAX_PIXELES = 40_000_000        # más que esto no se abre (evita agotar la memoria)
LINEAS_POR_PARRAFO = 25         # párrafos cortos: partirlos entre páginas es barato
# Espacio mínimo para empezar una sección o el aporte de una persona; si no hay, pasa a
# la página siguiente (el título no queda solo al final de una página). No se usa
# keepWithNext con el texto: movería bloques enteros y dejaría páginas medio vacías.
ESPACIO_MINIMO = 3.5 * cm
MAX_NOMBRE_DESCARGA = 120

VERDE = colors.HexColor("#39a900")
VERDE_CLARO = colors.HexColor("#e8f6df")
AZUL = colors.HexColor("#13294b")
GRIS = colors.HexColor("#5f7080")
TEXTO = colors.HexColor("#1b2b36")
BORDE = colors.HexColor("#c9d6cf")
FONDO_ETIQUETA = colors.HexColor("#f3f7f5")

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


# ------------------------------------------------------------------ textos
def _limpiar(texto):
    """Saltos de línea como \\n y sin caracteres de control (salvo \\n y \\t)."""
    texto = str(texto if texto is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL.sub("", texto)


def _xml(texto):
    """Texto de una línea listo para un Paragraph: escapa &, < y >."""
    return escape(" ".join(_limpiar(texto).split()))


def _linea_xml(linea):
    """Escapa una línea y conserva su sangría (los espacios del inicio)."""
    linea = linea.replace("\t", "    ")
    sangria = len(linea) - len(linea.lstrip(" "))
    contenido = escape(linea[sangria:])
    return ("&nbsp;" * sangria + contenido) or "&nbsp;"  # línea vacía: sigue ocupando su renglón


def _parrafos(texto, estilo):
    """Texto largo -> párrafos que se parten entre páginas, con sus saltos de línea.

    Cada párrafo junta a lo sumo LINEAS_POR_PARRAFO líneas unidas con <br/>: partir un
    párrafo enorme obliga a reportlab a reacomodarlo entero en cada página.
    """
    lineas = _limpiar(texto).split("\n")
    return [
        Paragraph("<br/>".join(_linea_xml(x) for x in lineas[i:i + LINEAS_POR_PARRAFO]), estilo)
        for i in range(0, len(lineas), LINEAS_POR_PARRAFO)
    ]


def _recortar(texto, fuente, tamano, ancho):
    """Recorta el texto con «…» para que quepa en `ancho` puntos (encabezado y pie)."""
    texto = " ".join(_limpiar(texto).split())
    if stringWidth(texto, fuente, tamano) <= ancho:
        return texto
    while texto and stringWidth(texto + "…", fuente, tamano) > ancho:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def _numero(numero_acta):
    """'Acta 12' -> '12', para que el encabezado diga «ACTA No. 12»."""
    numero = " ".join(_limpiar(numero_acta).split())
    return re.sub(r"(?i)^acta\s+(no\.?\s*)?", "", numero) or numero


def _tamano(n):
    """Igual que en la página del acta: '1.5 MB' o '35 KB'."""
    if n >= 1048576:
        return f"{n / 1048576:.1f} MB"
    return f"{math.ceil(n / 1024)} KB"


def nombre_regional(nombre):
    """'Valle' -> 'Regional Valle'; si el catálogo ya trae el prefijo, no lo repite."""
    nombre = " ".join((nombre or "").split())
    return nombre if nombre.lower().startswith("regional ") else f"Regional {nombre}"


def nombre_descarga(numero_acta, nombre_reunion):
    """Nombre legible del PDF al descargarlo: 'Acta 1 - Reunión de equipo.pdf'.

    Sin caracteres de control ni invisibles, sin separadores de ruta ni los que
    Windows no admite en un nombre de archivo, y de largo acotado.
    """
    base = f"{numero_acta} - {nombre_reunion}" if nombre_reunion else str(numero_acta or "")
    base = "".join(" " if unicodedata.category(c).startswith("C") else c for c in base)
    base = re.sub(r'[\\/:*?"<>|]', "-", base)
    base = " ".join(base.split())[:MAX_NOMBRE_DESCARGA - len(".pdf")].strip(" .-")
    return (base or "Acta") + ".pdf"


# ---------------------------------------------------------------- estilos
def _estilos():
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13.5,
                          textColor=TEXTO, splitLongWords=1)
    celda = ParagraphStyle("celda", parent=base, fontSize=8.5, leading=11)
    return {
        "base": base,
        "celda": celda,
        "etiqueta": ParagraphStyle("etiqueta", parent=celda, fontName="Helvetica-Bold",
                                   fontSize=7.5, leading=9.5, textColor=GRIS),
        "seccion": ParagraphStyle("seccion", parent=base, fontName="Helvetica-Bold",
                                  fontSize=10, leading=13, textColor=AZUL, backColor=VERDE_CLARO,
                                  borderPadding=(4, 6, 4, 6), spaceBefore=16, spaceAfter=9,
                                  keepWithNext=1),
        "persona": ParagraphStyle("persona", parent=base, fontName="Helvetica-Bold",
                                  fontSize=10, textColor=AZUL, spaceBefore=9, spaceAfter=3),
        "lista": ParagraphStyle("lista", parent=base, leftIndent=18, bulletIndent=2,
                                spaceAfter=2),
        "vacio": ParagraphStyle("vacio", parent=base, fontName="Helvetica-Oblique",
                                textColor=GRIS),
        "nota": ParagraphStyle("nota", parent=base, fontSize=8.5, leading=11.5,
                               textColor=GRIS, spaceBefore=6),
    }


def _estilo_tabla(con_cabecera):
    reglas = [
        ("GRID", (0, 0), (-1, -1), 0.5, BORDE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if con_cabecera:
        reglas.append(("BACKGROUND", (0, 0), (-1, 0), VERDE_CLARO))
    return reglas


# --------------------------------------------------------------- secciones
def _tabla_datos(d, est):
    """Datos de la reunión en cuatro columnas: etiqueta, valor, etiqueta, valor."""
    def et(texto):
        return Paragraph(escape(texto.upper()), est["etiqueta"])

    def val(texto):
        return Paragraph(_xml(texto), est["celda"])

    filas = [
        [et("Nombre del comité o de la reunión"), val(d["nombre_reunion"]), "", ""],
        [et("Ciudad y fecha"), val(f"{d['ciudad']}, {d['fecha']}"), "", ""],
        [et("Hora de inicio"), val(d["hora_inicio"]), et("Hora de fin"), val(d["hora_fin"])],
        [et("Lugar y/o enlace"), val(d["lugar_enlace"]), "", ""],
        [et("Dirección regional / centro de formación"),
         val(f"{nombre_regional(d['regional'])} / {d['centro']}"), "", ""],
    ]
    if d.get("ficha"):
        filas += [
            [et("Tipo de acta"), val(d["tipo_acta"]), et("Mes"), val(d.get("mes") or "")],
            [et("Ficha y programa"), val(f"{d['ficha']} — {d.get('programa') or ''}"), "", ""],
        ]
    else:
        filas.append([et("Tipo de acta"), val(d["tipo_acta"]), "", ""])

    reglas = _estilo_tabla(False) + [("BACKGROUND", (0, 0), (0, -1), FONDO_ETIQUETA)]
    for i, fila in enumerate(filas):
        if fila[2] == "":
            reglas.append(("SPAN", (1, i), (3, i)))
        else:
            reglas.append(("BACKGROUND", (2, i), (2, i), FONDO_ETIQUETA))
    anchos = [4.4 * cm, 4.6 * cm, 2.6 * cm]
    tabla = Table(filas, colWidths=anchos + [ANCHO_UTIL - sum(anchos)])
    tabla.setStyle(TableStyle(reglas))
    return tabla


def _titulo(texto, est):
    return [CondPageBreak(ESPACIO_MINIMO), Paragraph(texto, est["seccion"])]


def _lista_numerada(titulo, items, est):
    flujo = _titulo(titulo, est)
    for i, texto in enumerate(items, start=1):
        flujo.append(Paragraph(_xml(texto), est["lista"], bulletText=f"{i}."))
    if not items:
        flujo.append(Paragraph("Sin puntos registrados.", est["vacio"]))
    return flujo


def _textos_por_participante(titulo, campo, participantes, est):
    flujo = _titulo(titulo, est)
    for i, p in enumerate(participantes):
        if i:
            flujo.append(CondPageBreak(ESPACIO_MINIMO - 1 * cm))
        flujo.append(Paragraph(
            f"{_xml(p['nombre'])} <font name=\"Helvetica\" size=\"8.5\" color=\"#5f7080\">"
            f"· {_xml(p.get('rol') or '')}</font>", est["persona"]))
        texto = _limpiar(p.get(campo)).strip()
        if texto:
            flujo += _parrafos(texto, est["base"])
        else:
            flujo.append(Paragraph("Sin aporte en esta sección.", est["vacio"]))
    if not participantes:
        flujo.append(Paragraph("El acta no tiene participantes registrados.", est["vacio"]))
    return flujo


def _tabla(cabecera, filas, anchos, est):
    datos = [[Paragraph(escape(c.upper()), est["etiqueta"]) for c in cabecera]]
    datos += [[Paragraph(_xml(c), est["celda"]) for c in fila] for fila in filas]
    tabla = Table(datos, colWidths=anchos + [ANCHO_UTIL - sum(anchos)], repeatRows=1)
    tabla.setStyle(TableStyle(_estilo_tabla(True)))
    return tabla


def _compromisos(compromisos, est):
    flujo = _titulo("ESTABLECIMIENTO Y ACEPTACIÓN DE COMPROMISOS", est)
    if not compromisos:
        return flujo + [Paragraph("No se registraron compromisos.", est["vacio"])]
    filas = [[c["actividad"], c["fecha"], c["responsable"], c.get("firma") or "—"]
             for c in compromisos]
    cabecera = ["Actividad / decisión", "Fecha", "Responsable", "Firma o participación virtual"]
    return flujo + [_tabla(cabecera, filas, [7 * cm, 2.2 * cm, 3.6 * cm], est)]


def _asistentes(participantes, est):
    flujo = _titulo("ASISTENTES Y APROBACIÓN DE DECISIONES", est)
    filas = [[
        p["nombre"], p.get("rol") or "", "Sí", "—",
        f"Firmado electrónicamente el {p['firmado_en']}" if p.get("firmado_en") else "Sin firma",
    ] for p in participantes]
    cabecera = ["Nombre", "Dependencia / rol", "Aprueba", "Observación",
                "Firma o participación virtual"]
    flujo.append(_tabla(cabecera, filas, [4 * cm, 3.8 * cm, 1.7 * cm, 2.4 * cm], est))
    flujo.append(Paragraph(
        "Cada participante firmó electrónicamente su aporte en el sistema Actas SENA con su "
        "usuario; esa firma es su aprobación del acta.", est["nota"]))
    return flujo


def _imagen(anexo):
    """Imagen del anexo escalada al ancho del marco (alto máximo 9 cm). None si no abre."""
    fuente = anexo.get("contenido")
    fuente = io.BytesIO(fuente) if fuente is not None else anexo.get("ruta")
    try:
        with PILImage.open(fuente) as original:
            if original.width * original.height > MAX_PIXELES:
                return None
            formato = "PNG" if original.format == "PNG" else "JPEG"
            if original.format == "JPEG":
                original.draft("RGB", (MAX_LADO_IMAGEN, MAX_LADO_IMAGEN))  # decodifica más pequeño
            img = ImageOps.exif_transpose(original)  # fotos del celular con su orientación real
            if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                fondo = PILImage.new("RGB", img.size, "white")
                fondo.paste(img, mask=img.getchannel("A"))
                img = fondo
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((MAX_LADO_IMAGEN, MAX_LADO_IMAGEN))
            salida = io.BytesIO()
            img.save(salida, formato, **({"quality": 85} if formato == "JPEG" else {}))
    except Exception:  # archivo dañado, perdido o que Pillow no entiende: va una nota
        return None
    escala = min(ANCHO_UTIL / img.width, ALTO_MAX_IMAGEN / img.height, 1)
    salida.seek(0)
    return Image(salida, width=img.width * escala, height=img.height * escala)


def _anexos(anexos, est):
    flujo = _titulo("ANEXOS", est)
    if not anexos:
        return flujo + [Paragraph("No se adjuntaron anexos.", est["vacio"])]
    for a in (a for a in anexos if a.get("es_imagen")):
        titulo = Paragraph(f"Imagen: {_xml(a['nombre'])} ({_tamano(a['tamano_bytes'])})", est["nota"])
        imagen = _imagen(a) or Paragraph(
            "No se pudo insertar esta imagen: el archivo no está disponible o no se puede abrir.",
            est["vacio"])
        flujo.append(KeepTogether([titulo, Spacer(1, 3), imagen, Spacer(1, 8)]))
    documentos = [a for a in anexos if not a.get("es_imagen")]
    if documentos:
        flujo.append(Paragraph("Estos documentos se entregan como archivos aparte, junto con el acta:",
                               est["nota"]))
        for a in documentos:
            flujo.append(Paragraph(f"{_xml(a['nombre'])} ({_tamano(a['tamano_bytes'])})",
                                   est["lista"], bulletText="•"))
    return flujo


# ------------------------------------------------- encabezado, pie y páginas
PIE_Y = 1.25 * cm


class _CanvasNumerado(canvas.Canvas):
    """Escribe «Página X de Y»: guarda cada página y la dibuja al final, cuando ya sabe Y."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(GRIS)
            self.drawRightString(ANCHO - MARGEN, PIE_Y, f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def _logo(ruta):
    try:
        return ImageReader(ruta) if ruta and os.path.isfile(ruta) else None
    except Exception:
        return None  # logo dañado: el acta sale sin logo


def _marco(d):
    """Función que dibuja el encabezado y el pie de cada página."""
    numero = f"ACTA No. {_numero(d['numero_acta'])}"
    codigo = d.get("codigo_formato") or ""
    reunion = d.get("nombre_reunion") or ""
    if d.get("cerrado_en"):
        pie = f"Cerrada el {d['cerrado_en']} (hora de Colombia) por {d.get('cerrado_por') or '—'}"
    else:
        pie = "Acta cerrada (la fecha del cierre no quedó registrada)"
    logo = _logo(d.get("logo", LOGO_DEFECTO))

    def dibujar(canv, doc):
        canv.saveState()
        arriba, alto = ALTO - 1.1 * cm, 1.9 * cm
        abajo = arriba - alto
        x_logo, x_codigo = MARGEN + 2.6 * cm, ANCHO - MARGEN - 4.4 * cm
        canv.setStrokeColor(BORDE)
        canv.setLineWidth(0.6)
        canv.rect(MARGEN, abajo, ANCHO_UTIL, alto)
        canv.line(x_logo, abajo, x_logo, arriba)
        canv.line(x_codigo, abajo, x_codigo, arriba)
        canv.setFillColor(VERDE)
        canv.rect(MARGEN, abajo - 0.1 * cm, ANCHO_UTIL, 0.1 * cm, stroke=0, fill=1)
        if logo:
            canv.drawImage(logo, MARGEN + 0.45 * cm, abajo + 0.2 * cm, width=1.7 * cm,
                           height=1.5 * cm, preserveAspectRatio=True, mask="auto")

        medio, ancho_medio = (x_logo + x_codigo) / 2, x_codigo - x_logo - 0.6 * cm
        canv.setFillColor(AZUL)
        canv.setFont("Helvetica-Bold", 13)
        canv.drawCentredString(medio, abajo + 1.05 * cm, _recortar(numero, "Helvetica-Bold", 13, ancho_medio))
        canv.setFillColor(GRIS)
        canv.setFont("Helvetica", 8)
        canv.drawCentredString(medio, abajo + 0.5 * cm, _recortar(reunion, "Helvetica", 8, ancho_medio))

        der = (x_codigo + ANCHO - MARGEN) / 2
        canv.setFont("Helvetica", 6.5)
        canv.drawCentredString(der, abajo + 1.2 * cm, "CÓDIGO Y VERSIÓN DEL FORMATO")
        canv.setFillColor(AZUL)
        canv.setFont("Helvetica-Bold", 10.5)
        canv.drawCentredString(der, abajo + 0.6 * cm, _recortar(codigo, "Helvetica-Bold", 10.5, 4 * cm))

        canv.setStrokeColor(BORDE)
        canv.line(MARGEN, PIE_Y + 0.45 * cm, ANCHO - MARGEN, PIE_Y + 0.45 * cm)
        canv.setFillColor(GRIS)
        canv.setFont("Helvetica", 7.5)
        canv.drawString(MARGEN, PIE_Y, _recortar(pie, "Helvetica", 7.5, ANCHO_UTIL - 3 * cm))
        canv.restoreState()

    return dibujar


# ---------------------------------------------------------------- principal
def generar_pdf_acta(datos):
    """Devuelve los bytes del PDF del acta (formato GOR-F-084 v2). Ver las claves arriba."""
    est = _estilos()
    participantes = datos.get("participantes") or []
    flujo = [_tabla_datos(datos, est)]
    flujo += _lista_numerada("AGENDA O PUNTOS PARA DESARROLLAR", datos.get("agenda") or [], est)
    flujo += _lista_numerada("OBJETIVO(S) DE LA REUNIÓN", datos.get("objetivos") or [], est)
    flujo += _textos_por_participante("DESARROLLO DE LA REUNIÓN", "desarrollo", participantes, est)
    flujo += _textos_por_participante("CONCLUSIONES", "conclusiones", participantes, est)
    flujo += _compromisos(datos.get("compromisos") or [], est)
    flujo += _asistentes(participantes, est)
    flujo += _anexos(datos.get("anexos") or [], est)

    salida = io.BytesIO()
    doc = SimpleDocTemplate(
        salida, pagesize=letter, invariant=1,
        leftMargin=MARGEN, rightMargin=MARGEN, topMargin=3.6 * cm, bottomMargin=2.3 * cm,
        title=" ".join(_limpiar(f"{datos['numero_acta']} - {datos.get('nombre_reunion') or ''}").split()),
        author="Actas SENA", creator="Actas SENA", subject=datos.get("codigo_formato") or "",
    )
    marco = _marco(datos)
    doc.build(flujo, onFirstPage=marco, onLaterPages=marco, canvasmaker=_CanvasNumerado)
    return salida.getvalue()
