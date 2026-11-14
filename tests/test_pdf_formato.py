"""
Pruebas de US-013: PDF del acta con el formato GOR-F-084 v2 (pdf_formato.py).

No necesitan base de datos ni librerías extra. Ejecutar desde la raíz del repositorio:
    python -m unittest discover -s tests -v
"""
import base64
import io
import os
import re
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

import pdf_formato as pdf_acta  # noqa: E402
from pdf_formato import generar_pdf_acta, nombre_descarga  # noqa: E402

LARGO = 50_000
PALABRA_LARGA = "Z" * 5_000


def texto_largo(marcador, quien):
    """50.000 caracteres con &, <, >, tildes, saltos de línea, sangría y una palabra de
    5.000 letras; el marcador va al FINAL para comprobar que nada se recortó."""
    frase = (f"Reunión de {quien}: la señora Muñoz & el señor Núñez revisaron <cronograma> "
             "y acordaron más acciones (ñandú, pingüino).\n")
    bloque = frase * 30 + "\n\t- viñeta con sangría\n" + PALABRA_LARGA + "\n\n"
    fin = f"\n{marcador}"
    texto = (bloque * (LARGO // len(bloque) + 1))[:LARGO - len(fin)] + fin
    assert len(texto) == LARGO
    return texto


def imagen(formato="PNG", tam=(800, 600), modo="RGB", color=(30, 120, 40)):
    salida = io.BytesIO()
    Image.new(modo, tam, color).save(salida, formato)
    return salida.getvalue()


def datos_base(**cambios):
    datos = {
        "numero_acta": "Acta 7", "codigo_formato": "GOR-F-084 v2",
        "nombre_reunion": "Comité de seguimiento & <revisión>", "ciudad": "Palmira",
        "fecha": "13/11/2026", "hora_inicio": "08:00", "hora_fin": "10:00",
        "lugar_enlace": "Sala 1", "regional": "Valle", "centro": "Centro de Biotecnología Industrial",
        "tipo_acta": "Otros asuntos", "ficha": None, "programa": None, "mes": None,
        "agenda": ["Punto uno"], "objetivos": ["Objetivo uno"],
        "participantes": [{"nombre": "Lina Líder", "rol": "Instructor líder de ficha",
                           "desarrollo": "Se revisó el avance.", "conclusiones": None,
                           "firmado_en": "13/11/2026 09:58:01"}],
        "compromisos": [], "anexos": [],
        "cerrado_en": "13/11/2026 10:20:05", "cerrado_por": "Lina Líder",
        "logo": pdf_acta.LOGO_DEFECTO,
    }
    datos.update(cambios)
    return datos


def contenido(pdf):
    """Contenido de los flujos del PDF (reportlab los guarda en ASCII85 + Flate).

    Sirve para buscar textos ASCII sin instalar un lector de PDF. Se saltan las
    imágenes; en el texto, los paréntesis quedan escapados: «\\(».
    """
    partes = []
    patron = rb"/Filter \[ /ASCII85Decode /FlateDecode \]([^>]*)>>\s*stream\r?\n(.*?)endstream"
    for m in re.finditer(patron, pdf, re.S):
        if b"/Subtype" in m.group(1):
            continue
        datos = m.group(2).strip()
        if datos.endswith(b"~>"):
            datos = datos[:-2]
        partes.append(zlib.decompress(base64.a85decode(datos)))
    return b"\n".join(partes)


def paginas(pdf):
    """Número de páginas (el /Count del árbol de páginas; el PDF no tiene marcadores)."""
    return int(re.search(rb"/Count (\d+)", pdf).group(1))


class TextosLargosTest(unittest.TestCase):
    """Tres participantes con 50.000 caracteres en cada campo (300.000 en total)."""

    @classmethod
    def setUpClass(cls):
        participantes = []
        for i, nombre in enumerate(["Lina Líder", "Iván Integrante", "Sara Segunda"]):
            participantes.append({
                "nombre": nombre, "rol": "Instructor",
                "desarrollo": texto_largo(f"FINDESARROLLO{i}MARCA", nombre),
                "conclusiones": texto_largo(f"FINCONCLUSIONES{i}MARCA", nombre),
                "firmado_en": f"13/11/2026 10:0{i}:00",
            })
        cls.datos = datos_base(participantes=participantes, tipo_acta="Equipo ejecutor",
                               ficha="2876540", programa="ADSO", mes="Noviembre de 2026")
        cls.pdf = generar_pdf_acta(cls.datos)
        cls.texto = contenido(cls.pdf)

    def test_devuelve_un_pdf(self):
        self.assertIsInstance(self.pdf, bytes)
        self.assertTrue(self.pdf.startswith(b"%PDF-"))
        self.assertTrue(self.pdf.rstrip().endswith(b"%%EOF"))

    def test_se_parte_en_muchas_paginas(self):
        self.assertGreater(paginas(self.pdf), 30)

    def test_no_recorta_ningun_texto(self):
        for i in range(3):
            self.assertIn(f"FINDESARROLLO{i}MARCA".encode(), self.texto)
            self.assertIn(f"FINCONCLUSIONES{i}MARCA".encode(), self.texto)

    def test_numera_las_paginas_con_el_total(self):
        total = paginas(self.pdf)
        # «Página» se guarda en Latin-1: la á es \341
        self.assertIn(f"gina 1 de {total})".encode(), self.texto)
        self.assertIn(f"gina {total} de {total})".encode(), self.texto)

    def test_pie_con_la_fecha_exacta_del_cierre(self):
        self.assertIn(rb"Cerrada el 13/11/2026 10:20:05 \(hora de Colombia\) por L", self.texto)

    def test_es_determinista(self):
        # Mismos datos, mismos bytes: un PDF perdido se regenera con el mismo SHA-256
        self.assertEqual(generar_pdf_acta(self.datos), self.pdf)


class CasosBordeTest(unittest.TestCase):
    def test_acta_sin_compromisos_ni_anexos(self):
        texto = contenido(generar_pdf_acta(datos_base()))
        self.assertIn(b"No se registraron compromisos.", texto)
        self.assertIn(b"No se adjuntaron anexos.", texto)
        self.assertIn(b"Sin aporte en esta secci", texto)  # Lina no escribió conclusiones

    def test_imagen_danada_no_rompe_el_pdf(self):
        anexos = [
            {"nombre": "dañada.png", "tamano_bytes": 20, "es_imagen": True,
             "contenido": b"\x89PNG\r\n\x1a\nbasura"},
            {"nombre": "perdida.jpg", "tamano_bytes": 20, "es_imagen": True,
             "ruta": "/ruta/que/no/existe.jpg"},
        ]
        pdf = generar_pdf_acta(datos_base(anexos=anexos))
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertEqual(contenido(pdf).count(b"No se pudo insertar esta imagen"), 2)

    def test_inserta_imagenes_y_lista_los_documentos(self):
        anexos = [
            {"nombre": "foto.jpg", "tamano_bytes": 3_000_000, "es_imagen": True,
             "contenido": imagen("JPEG", (3000, 4000))},
            {"nombre": "captura.png", "tamano_bytes": 4_000, "es_imagen": True,
             "contenido": imagen("PNG", (300, 200), "RGBA", (200, 0, 0, 90))},
            {"nombre": "Informe.pdf", "tamano_bytes": 1_572_864, "es_imagen": False},
        ]
        pdf = generar_pdf_acta(datos_base(anexos=anexos))
        texto = contenido(pdf)
        self.assertGreaterEqual(pdf.count(b"/Subtype /Image"), 3)  # logo + 2 fotos
        self.assertIn(b"se entregan como archivos aparte", texto)
        self.assertIn(rb"Informe.pdf \(1.5 MB\)", texto)
        self.assertNotIn(b"No se pudo insertar", texto)

    def test_sin_logo_tambien_sale(self):
        pdf = generar_pdf_acta(datos_base(logo="/no/existe/logo.png"))
        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_caracteres_raros_no_rompen(self):
        raro = "Emoji 😀, griego Ω, chino 中文, control \x01\x0b y </para><b>sin cerrar"
        p = {"nombre": "Ana </b>", "rol": "<i>", "desarrollo": raro, "conclusiones": raro,
             "firmado_en": "13/11/2026 10:00:00"}
        pdf = generar_pdf_acta(datos_base(participantes=[p], nombre_reunion=raro,
                                          agenda=[raro], objetivos=[raro]))
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"sin cerrar", contenido(pdf))

    def test_compromisos_en_tabla(self):
        compromisos = [{"actividad": "Enviar informe", "fecha": "20/11/2026",
                        "responsable": "Iván Integrante", "firma": None}]
        texto = contenido(generar_pdf_acta(datos_base(compromisos=compromisos)))
        self.assertIn(b"Enviar informe", texto)
        self.assertNotIn(b"No se registraron compromisos.", texto)

    def test_encabezado_con_numero_y_formato(self):
        texto = contenido(generar_pdf_acta(datos_base()))
        self.assertIn(b"ACTA No. 7", texto)
        self.assertIn(b"GOR-F-084 v2", texto)


class NombreDescargaTest(unittest.TestCase):
    def test_nombre_legible(self):
        self.assertEqual(nombre_descarga("Acta 1", "Reunión de equipo"), "Acta 1 - Reunión de equipo.pdf")

    def test_sin_separadores_de_ruta_ni_control(self):
        nombre = nombre_descarga("Acta 2", '../../etc/passwd\r\nX-Malo: 1\x00 a\\b:c*?"<>|‮fdp.exe')
        self.assertTrue(nombre.endswith(".pdf"))
        for c in '/\\\r\n\x00:*?"<>|‮':
            self.assertNotIn(c, nombre)

    def test_largo_acotado(self):
        nombre = nombre_descarga("Acta 3", "x" * 500)
        self.assertLessEqual(len(nombre), pdf_acta.MAX_NOMBRE_DESCARGA)
        self.assertTrue(nombre.startswith("Acta 3 - xxx") and nombre.endswith(".pdf"))

    def test_vacio(self):
        self.assertEqual(nombre_descarga("", "   "), "Acta.pdf")


class NombreRegionalTest(unittest.TestCase):
    def test_agrega_el_prefijo(self):
        self.assertEqual(pdf_acta.nombre_regional("Valle"), "Regional Valle")

    def test_no_repite_el_prefijo_del_catalogo(self):
        # La migración de US-005 puede guardar las regionales como "Regional Arauca"
        self.assertEqual(pdf_acta.nombre_regional("Regional Arauca"), "Regional Arauca")
        self.assertEqual(pdf_acta.nombre_regional("REGIONAL  Arauca"), "REGIONAL Arauca")

    def test_en_el_pdf_sale_una_sola_vez(self):
        texto = contenido(generar_pdf_acta(datos_base(regional="Regional Valle")))
        self.assertIn(b"Regional Valle", texto)
        self.assertNotIn(b"Regional Regional", texto)


class BorradorYFirmaTest(unittest.TestCase):
    """US-014: borrador con el acta abierta; firma con imagen («Mi firma») en las tablas."""

    def test_borrador_lleva_la_marca_y_la_hora_en_que_se_genero(self):
        pdf = generar_pdf_acta(datos_base(borrador=True, generado_en="13/11/2026 09:00:00",
                                          cerrado_en=None, cerrado_por=None))
        texto = contenido(pdf)
        self.assertIn(b"BORRADOR", texto)
        self.assertIn(b"13/11/2026 09:00:00", texto)
        self.assertNotIn(b"Cerrada el", texto)

    def test_borrador_muestra_las_firmas_pendientes(self):
        sin_firmar = [{"nombre": "Iván", "rol": "Instructor", "desarrollo": "x",
                       "conclusiones": None, "firmado_en": None}]
        pdf = generar_pdf_acta(datos_base(borrador=True, participantes=sin_firmar))
        self.assertIn(b"Pendiente de firma", contenido(pdf))

    def test_acta_cerrada_sin_marca_de_borrador(self):
        self.assertNotIn(b"BORRADOR", contenido(generar_pdf_acta(datos_base())))

    def test_firma_con_imagen_en_asistentes_y_compromisos(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as archivo:
            archivo.write(imagen("PNG", (400, 120), "RGBA", (10, 20, 120, 255)))
        try:
            participante = dict(datos_base()["participantes"][0], firma_ruta=archivo.name)
            compromiso = {"actividad": "Entregar informe", "fecha": "20/11/2026",
                          "responsable": "Lina Líder", "firma": "Registrado por Lina Líder",
                          "firma_ruta": archivo.name}
            sin = generar_pdf_acta(datos_base())
            con = generar_pdf_acta(datos_base(participantes=[participante], compromisos=[compromiso]))
        finally:
            os.unlink(archivo.name)
        self.assertGreater(con.count(b"/Subtype /Image"), sin.count(b"/Subtype /Image"))
        self.assertIn(b"Registrado por Lina L", contenido(con))

    def test_firma_perdida_deja_solo_el_texto(self):
        participante = dict(datos_base()["participantes"][0], firma_ruta="/no/existe/firma.png")
        pdf = generar_pdf_acta(datos_base(participantes=[participante]))
        self.assertIn(b"Firmado electr", contenido(pdf))


if __name__ == "__main__":
    unittest.main()
