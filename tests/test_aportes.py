"""
Pruebas de US-020: el desarrollo y las conclusiones aceptan textos muy largos.

No necesitan base de datos. Ejecutar desde la raíz del repositorio:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request  # noqa: E402
from werkzeug.exceptions import RequestEntityTooLarge  # noqa: E402

import aporte_texto as aportes  # noqa: E402
from aporte_texto import MAX_LARGO_APORTE, leer_aporte, normalizar, validar_aporte  # noqa: E402

# Texto con tildes, eñes, emoji y saltos de línea como los envía el navegador (\r\n)
FRASE = "Reunión del equipo: la señora Muñoz explicó el cronograma 😀\r\n"
# Casi todo tildes, emoji y símbolos: cada carácter pesa ~7 bytes al enviarse (%XX)
DENSO = "ñÁéÍóÚü😀€—\r\n"


def texto_largo(n, frase=FRASE):
    """Texto de exactamente `n` caracteres ya normalizado (sin \\r, sin espacios en los extremos)."""
    base = normalizar(frase * (n // len(frase.strip()) + 2))
    return base[:n - 1] + "." if n else ""


class NormalizarTest(unittest.TestCase):
    def test_crlf_y_cr_pasan_a_un_solo_salto(self):
        self.assertEqual(normalizar("uno\r\ndos\rtres\ncuatro"), "uno\ndos\ntres\ncuatro")

    def test_conserva_saltos_y_espacios_internos(self):
        texto = "Punto 1:\n\n    - detalle   con  espacios\n\tTabulado"
        self.assertEqual(normalizar(texto), texto)

    def test_recorta_solo_el_inicio_y_el_final(self):
        self.assertEqual(normalizar("  \r\n  Hola\r\n\r\n  mundo  \r\n "), "Hola\n\n  mundo")

    def test_vacio_o_solo_espacios_queda_none(self):
        for valor in (None, "", "   ", "\r\n\r\n", " \t \n"):
            self.assertIsNone(normalizar(valor), repr(valor))

    def test_solo_caracteres_invisibles_queda_none(self):
        # BOM y espacios de ancho cero: str.strip() no los quita y el aporte se vería en blanco
        for valor in ("\ufeff", "\u200b", " \ufeff\r\n\u200b\u200c\u200d\u2060 ", "\u200b \u200b \u200b"):
            self.assertIsNone(normalizar(valor), repr(valor))

    def test_invisibles_solo_se_recortan_en_los_extremos(self):
        # El ZWJ interno une el emoji de familia: se conserva
        familia = "\U0001F468\u200d\U0001F469\u200d\U0001F467"
        self.assertEqual(normalizar("\ufeff Hola " + familia + "\u200b\n"), "Hola " + familia)

    def test_quita_el_caracter_nulo(self):
        # PostgreSQL no admite \x00 dentro de un TEXT
        self.assertEqual(normalizar("a\x00b"), "ab")


class ValidarTest(unittest.TestCase):
    def test_limite_exacto_es_valido(self):
        aporte = {"desarrollo": "a" * MAX_LARGO_APORTE, "conclusiones": "b" * MAX_LARGO_APORTE}
        self.assertEqual(validar_aporte(aporte), [])

    def test_un_caracter_de_mas_da_error_con_el_conteo(self):
        aporte = {"desarrollo": "a" * (MAX_LARGO_APORTE + 1), "conclusiones": None}
        self.assertEqual(
            validar_aporte(aporte),
            ["El desarrollo tiene 50.001 caracteres; el máximo es 50.000."],
        )

    def test_conclusiones_excedidas(self):
        aporte = {"desarrollo": "Hola", "conclusiones": "c" * 50_120}
        self.assertEqual(
            validar_aporte(aporte),
            ["Las conclusiones tienen 50.120 caracteres; el máximo es 50.000."],
        )

    def test_tildes_enes_y_emoji_cuentan_como_un_caracter(self):
        texto = texto_largo(MAX_LARGO_APORTE)
        self.assertEqual(len(texto), MAX_LARGO_APORTE)
        self.assertIn("ñ", texto)
        self.assertIn("😀", texto)
        self.assertEqual(validar_aporte({"desarrollo": texto, "conclusiones": texto}), [])
        self.assertEqual(len(validar_aporte({"desarrollo": texto + "😀", "conclusiones": None})), 1)

    def test_el_salto_crlf_cuenta_como_uno(self):
        # 25.000 + \r\n + 24.999 = 50.001 caracteres enviados, 50.000 al normalizar
        aporte = leer_aporte({"desarrollo": "a" * 25_000 + "\r\n" + "b" * 24_999})
        self.assertEqual(len(aporte["desarrollo"]), MAX_LARGO_APORTE)
        self.assertEqual(validar_aporte(aporte), [])

    def test_ambos_vacios_da_error(self):
        aporte = leer_aporte({"desarrollo": "  \r\n ", "conclusiones": ""})
        self.assertEqual(validar_aporte(aporte), ["Escribe el desarrollo o las conclusiones de tu aporte."])

    def test_solo_invisibles_en_ambos_da_error(self):
        aporte = leer_aporte({"desarrollo": "\ufeff", "conclusiones": "\u200b\r\n"})
        self.assertEqual(aporte, {"desarrollo": None, "conclusiones": None})
        self.assertEqual(validar_aporte(aporte), ["Escribe el desarrollo o las conclusiones de tu aporte."])

    def test_sin_campos_en_el_formulario_da_error(self):
        aporte = leer_aporte({})
        self.assertEqual(aporte, {"desarrollo": None, "conclusiones": None})
        self.assertEqual(len(validar_aporte(aporte)), 1)

    def test_un_campo_vacio_queda_null(self):
        aporte = leer_aporte({"desarrollo": "   ", "conclusiones": "Se aprueba el plan.\r\n"})
        self.assertEqual(aporte, {"desarrollo": None, "conclusiones": "Se aprueba el plan."})
        self.assertEqual(validar_aporte(aporte), [])

    def test_miles_con_punto(self):
        self.assertEqual(aportes.miles(50_000), "50.000")
        self.assertEqual(aportes.miles(1234567), "1.234.567")
        self.assertEqual(aportes.miles(999), "999")


class FormularioGrandeTest(unittest.TestCase):
    """Flask corta en 500 KB los formularios normales (413); el aporte completo debe caber."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SECRET_KEY", "clave-de-pruebas")
        from app import app
        cls.app = app
        texto = texto_largo(MAX_LARGO_APORTE, DENSO).replace("\n", "\r\n")
        cls.datos = {"desarrollo": texto, "conclusiones": texto}

    def test_el_tope_cubre_el_peor_caso(self):
        # 2 campos x 50.000 caracteres x 12 bytes (emoji: 4 bytes UTF-8 enviados como %XX)
        self.assertGreaterEqual(aportes.MAX_BYTES_FORMULARIO, 2 * MAX_LARGO_APORTE * 12)
        self.assertEqual(self.app.config["MAX_FORM_MEMORY_SIZE"], aportes.MAX_BYTES_FORMULARIO)

    def test_la_app_lee_dos_campos_largos_sin_413(self):
        with self.app.test_request_context("/actas/1/aporte", method="POST", data=self.datos):
            self.assertGreater(request.content_length, 500 * 1024)  # más que el tope de Flask
            aporte = leer_aporte(request.form)
        self.assertEqual(len(aporte["desarrollo"]), MAX_LARGO_APORTE)
        self.assertEqual(aporte["conclusiones"], self.datos["conclusiones"].replace("\r\n", "\n"))
        self.assertEqual(validar_aporte(aporte), [])

    def test_sin_el_ajuste_flask_responderia_413(self):
        with Flask("sin_ajuste").test_request_context("/", method="POST", data=self.datos):
            with self.assertRaises(RequestEntityTooLarge):
                request.form

    def test_si_se_pasa_del_tope_avisa_y_vuelve_al_acta(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["usuario_id"] = 1
        relleno = "x" * (aportes.MAX_BYTES_FORMULARIO + 1)
        respuesta = cliente.post("/actas/7/aporte", data={"desarrollo": relleno})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.headers["Location"].endswith("/actas/7#mi-aporte"))
        with cliente.session_transaction() as sesion:
            categoria, mensaje = sesion["_flashes"][0]
        self.assertEqual(categoria, "aporte_error")  # se pinta dentro de #mi-aporte
        self.assertIn("50.000", mensaje)


class AvisosAporteTest(unittest.TestCase):
    """Tras guardar se salta a #mi-aporte: el aviso debe quedar dentro de ese panel, a la vista."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SECRET_KEY", "clave-de-pruebas")
        from app import app
        cls.app = app

    def pintar(self, avisos, **cambios):
        """HTML de ver_acta.html con datos de ejemplo, sin base de datos."""
        import psycopg2
        from datetime import date, time
        from unittest import mock
        from flask import flash, render_template, session
        import actas
        import adjuntos as adj

        acta = {
            "id": 7, "numero_acta": "ACTA-2026-0007", "nombre_reunion": "Comité", "lider_id": 1,
            "estado": "abierta", "tipo_acta": "otros_asuntos", "ficha": None, "programa": None,
            "mes": None, "ciudad": "Palmira", "fecha_reunion": date(2026, 11, 13),
            "hora_inicio": time(8), "hora_fin": time(10), "lugar_enlace": "Sala 1",
            "regional": "Valle", "centro": "Centro Agropecuario", "codigo_formato": None,
            "creador": "Ana Pérez",
        }
        participante = {
            "usuario_id": 1, "nombre": "Ana", "apellido": "Pérez", "rol": actas.ROL_LIDER,
            "es_creador": True, "aporto": False, "desarrollo": None, "conclusiones": None,
            "aporte_actualizado_en": None, "uid": 1, "tiene_firma": False,
        }
        contexto = dict(
            acta=acta, meses=actas.MESES, participantes=[participante], adjuntos=[],
            puede_adjuntar=False, puede_gestionar_adjuntos=True,
            max_mb=adj.MAX_BYTES // (1024 * 1024), max_bytes=adj.MAX_BYTES,
            max_por_persona=adj.MAX_POR_PERSONA, tipos_texto=adj.EXTENSIONES_TEXTO,
            accept=adj.ACCEPT_HTML, agenda=["Punto 1"], objetivos=["Objetivo 1"],
            puede_aportar=True, aporte={"desarrollo": None, "conclusiones": None},
            aporte_guardado_en=None, errores_aporte=[], max_aporte=MAX_LARGO_APORTE,
            compromisos=[], tengo_firma=False, es_participante=True, es_lider=True,
        )
        contexto.update(cambios)
        sin_bd = mock.patch("actas.get_connection", side_effect=psycopg2.OperationalError("sin BD"))
        with sin_bd, self.app.test_request_context("/actas/7"):
            session.update(usuario_id=1, nombre="Ana Pérez", rol=actas.ROL_LIDER)
            for categoria, mensaje in avisos:
                flash(mensaje, categoria)
            return render_template("ver_acta.html", **contexto)

    def test_guardado_se_ve_dentro_de_mi_aporte(self):
        html = self.pintar([("aporte_ok", "Tu aporte quedó guardado.")])
        self.assertEqual(html.count("Tu aporte quedó guardado."), 1)
        self.assertLess(html.index('id="mi-aporte"'), html.index("Tu aporte quedó guardado."))
        self.assertLess(html.index("Tu aporte quedó guardado."), html.index('id="form-aporte"'))

    def test_error_413_se_ve_dentro_de_mi_aporte(self):
        html = self.pintar([("aporte_error", "Tu aporte es demasiado grande para enviarlo.")])
        posicion = html.index("Tu aporte es demasiado grande para enviarlo.")
        self.assertLess(html.index('id="mi-aporte"'), posicion)
        self.assertLess(posicion, html.index('id="form-aporte"'))

    def test_sin_panel_mi_aporte_el_aviso_sale_arriba(self):
        # p. ej. el acta se cerró entre el guardado y la recarga: el aviso no se pierde
        html = self.pintar([("aporte_ok", "Tu aporte quedó guardado.")], puede_aportar=False)
        self.assertNotIn('id="mi-aporte"', html)
        self.assertEqual(html.count("Tu aporte quedó guardado."), 1)
        self.assertLess(html.index("Tu aporte quedó guardado."), html.index('class="encabezado-acta"'))

    def test_con_errores_el_ancla_del_formulario_es_la_caja(self):
        # Tras un 400 o 503 el navegador da el foco al ancla: debe ser la caja de errores
        html = self.pintar([], errores_aporte=["Escribe el desarrollo o las conclusiones de tu aporte."])
        self.assertIn('id="errores-aporte" tabindex="-1"', html)
        self.assertIn('action="/actas/7/aporte#errores-aporte"', html)

    def test_cada_campo_trae_su_aviso_de_pegado_recortado(self):
        html = self.pintar([])
        for campo in ("desarrollo", "conclusiones"):
            self.assertIn(f'data-recorte="recorte-{campo}"', html)
            self.assertIn(f'<p class="alerta aviso-recorte" id="recorte-{campo}" role="alert" hidden></p>', html)

    def test_los_demas_avisos_siguen_arriba(self):
        html = self.pintar([("ok", "Acta creada."), ("error", "Error de adjuntos.")])
        for mensaje in ("Acta creada.", "Error de adjuntos."):
            self.assertEqual(html.count(mensaje), 1)
            self.assertLess(html.index(mensaje), html.index('class="encabezado-acta"'))


if __name__ == "__main__":
    unittest.main()
