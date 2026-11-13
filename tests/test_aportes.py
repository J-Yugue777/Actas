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

import aportes  # noqa: E402
from aportes import MAX_LARGO_APORTE, leer_aporte, normalizar, validar_aporte  # noqa: E402

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
        self.assertEqual(categoria, "error")
        self.assertIn("50.000", mensaje)


if __name__ == "__main__":
    unittest.main()
