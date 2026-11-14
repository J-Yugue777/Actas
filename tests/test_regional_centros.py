"""US-005 · Regional y centros de formación al crear el acta (sin base de datos)."""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "clave-de-pruebas")

import actas  # noqa: E402

REGIONALES = [
    {"id": 4, "nombre": "Amazonas"},
    {"id": 2, "nombre": "Antioquia"},
    {"id": 1, "nombre": "Valle"},
]
CENTROS = [
    {"id": 2, "regional_id": 1, "nombre": "Centro Agropecuario de Buga"},
    {"id": 1, "regional_id": 1, "nombre": "Centro de Biotecnología Industrial"},
    {"id": 4, "regional_id": 2, "nombre": "Centro de Servicios y Gestión Empresarial"},
    {"id": 3, "regional_id": 1, "nombre": "Centro de Gestión Tecnológica de Servicios"},
]


class AgruparCentros(unittest.TestCase):
    def test_respeta_el_orden_de_las_regionales_y_de_los_centros(self):
        grupos = actas.agrupar_centros(REGIONALES, CENTROS)
        self.assertEqual([g["nombre"] for g in grupos], ["Amazonas", "Antioquia", "Valle"])
        self.assertEqual([c["id"] for c in grupos[2]["centros"]], [2, 1, 3])
        self.assertEqual([c["id"] for c in grupos[1]["centros"]], [4])

    def test_incluye_regionales_sin_centros(self):
        grupos = actas.agrupar_centros(REGIONALES, CENTROS)
        self.assertEqual(grupos[0], {"id": 4, "nombre": "Amazonas", "centros": []})

    def test_ignora_centros_de_regionales_que_no_estan(self):
        grupos = actas.agrupar_centros(REGIONALES, CENTROS + [{"id": 9, "regional_id": 99, "nombre": "X"}])
        self.assertEqual(sum(len(g["centros"]) for g in grupos), len(CENTROS))

    def test_catalogo_vacio(self):
        self.assertEqual(actas.agrupar_centros([], []), [])


class ErroresLugar(unittest.TestCase):
    def errores(self, regional_id, centro_id):
        return actas.errores_lugar(regional_id, centro_id, REGIONALES, CENTROS)

    def test_centro_de_la_regional_es_valido(self):
        self.assertEqual(self.errores(1, 3), [])

    def test_sin_regional(self):
        self.assertEqual(self.errores(None, 3), ["Selecciona la dirección regional."])

    def test_regional_inexistente(self):
        self.assertEqual(self.errores(99, 1),
                         ["La regional elegida no existe. Vuelve a elegirla de la lista."])

    def test_centro_de_otra_regional(self):
        self.assertEqual(self.errores(2, 1),
                         ["El centro de formación no pertenece a la regional elegida."])

    def test_los_dos_mensajes_son_distintos(self):
        self.assertNotEqual(self.errores(99, 1), self.errores(2, 1))

    def test_centro_inexistente(self):
        self.assertEqual(self.errores(1, 99),
                         ["El centro de formación elegido no existe. Vuelve a elegirlo de la lista."])

    def test_sin_centro(self):
        self.assertEqual(self.errores(1, None), ["Selecciona el centro de formación."])

    def test_regional_sin_centros(self):
        self.assertEqual(self.errores(4, None), [
            "La regional elegida no tiene centros de formación registrados. Elige otra regional."])


class LugarAConservar(unittest.TestCase):
    def conservar(self, regional_id, centro_id):
        return actas.lugar_a_conservar(regional_id, centro_id, REGIONALES, CENTROS)

    def test_conserva_regional_y_centro_si_coinciden(self):
        self.assertEqual(self.conservar("1", "2"), ("1", "2"))

    def test_descarta_el_centro_de_otra_regional(self):
        self.assertEqual(self.conservar("2", "1"), ("2", ""))

    def test_descarta_todo_si_la_regional_no_existe(self):
        self.assertEqual(self.conservar("99", "1"), ("", ""))

    def test_valores_que_no_son_numeros(self):
        self.assertEqual(self.conservar("abc", "1"), ("", ""))
        self.assertEqual(self.conservar("1", "<script>"), ("1", ""))
        self.assertEqual(self.conservar("", ""), ("", ""))

    def test_normaliza_el_texto_del_formulario(self):
        # "01" debe volver como "1" para que la plantilla marque la opción
        self.assertEqual(self.conservar("01", "002"), ("1", "2"))


class ValidarLugar(unittest.TestCase):
    """validar() usa el catálogo ya cargado: en un acta de otros asuntos no consulta la base."""

    def datos(self, **cambios):
        datos = {
            "tipo_acta": "otros_asuntos", "nombre_reunion": "Comité", "ciudad": "Palmira",
            "fecha_reunion": "2026-11-13", "hora_inicio": "08:00", "hora_fin": "10:00",
            "lugar_enlace": "Sala 1", "regional_id": "1", "centro_id": "1", "ficha_id": "",
            "mes": "", "codigo_formato": "GOR-F-084 v2",
            "agenda": ["Punto 1"], "objetivos": ["Objetivo 1"],
        }
        datos.update(cambios)
        return datos

    def validar(self, **cambios):
        return actas.validar(None, self.datos(**cambios), {"fichas": []}, (REGIONALES, CENTROS))

    def test_lugar_valido(self):
        errores, valores = self.validar()
        self.assertEqual(errores, [])
        self.assertEqual((valores["regional_id"], valores["centro_id"]), (1, 1))

    def test_regional_inexistente(self):
        errores, _ = self.validar(regional_id="99")
        self.assertIn("La regional elegida no existe. Vuelve a elegirla de la lista.", errores)

    def test_numero_enorme_no_llega_a_la_base(self):
        errores, _ = self.validar(regional_id="9" * 30)
        self.assertIn("La regional elegida no existe. Vuelve a elegirla de la lista.", errores)

    def test_centro_de_otra_regional(self):
        errores, _ = self.validar(regional_id="2", centro_id="1")
        self.assertIn("El centro de formación no pertenece a la regional elegida.", errores)


class PlantillaCrearActa(unittest.TestCase):
    """La plantilla pinta los centros agrupados por regional (funciona sin JavaScript)."""

    @classmethod
    def setUpClass(cls):
        from app import app
        cls.app = app

    def pintar(self, regional_id="", centro_id="", regionales=REGIONALES, centros=CENTROS):
        from flask import render_template, session
        datos = actas.datos_iniciales({"fichas": []})
        datos.update(regional_id=regional_id, centro_id=centro_id)
        with self.app.test_request_context("/actas/crear"):
            session["nombre"] = "Ana Admin"
            session["rol"] = "Administrador"
            return render_template(
                "crear_acta.html", datos=datos, errores=[], regionales=regionales,
                grupos_centros=actas.agrupar_centros(regionales, centros),
                fichas=[], puede_equipo=False, meses=actas.MESES,
            )

    def select_centro(self, html):
        return re.search(r'<select id="centro_id".*?</select>', html, re.S).group(0)

    def ayuda(self, html):
        return re.search(r'<small class="([^"]*)" id="ayuda-centro" aria-live="polite">(.*?)</small>',
                         html, re.S).groups()

    def test_centros_en_optgroup_por_regional(self):
        select = self.select_centro(self.pintar())
        self.assertIn('<optgroup label="Valle" data-regional="1">', select)
        self.assertIn('<optgroup label="Antioquia" data-regional="2">', select)
        self.assertEqual(select.count("<optgroup"), 2)  # Amazonas no tiene centros
        self.assertEqual(select.count('<option value="'), len(CENTROS) + 1)

    def test_select_de_centro_habilitado_sin_javascript(self):
        apertura = re.search(r'<select id="centro_id"[^>]*>', self.pintar()).group(0)
        self.assertNotIn("disabled", apertura)
        self.assertIn('aria-describedby="ayuda-centro"', apertura)
        self.assertIn("required", apertura)

    def test_label_asociado(self):
        html = self.pintar()
        self.assertIn('<label for="centro_id">', html)
        self.assertIn('<label for="regional_id">', html)

    def test_conserva_regional_y_centro(self):
        html = self.pintar("1", "3")
        self.assertRegex(html, r'<option value="1" selected>Valle</option>')
        self.assertRegex(html, r'<option value="3" selected>Centro de Gestión Tecnológica de Servicios</option>')

    def test_ayuda_con_cantidad_de_centros(self):
        self.assertEqual(self.ayuda(self.pintar("1"))[1].strip(), "3 centros en Valle")
        self.assertEqual(self.ayuda(self.pintar("2"))[1].strip(), "1 centro en Antioquia")

    def test_ayuda_regional_sin_centros(self):
        clases, texto = self.ayuda(self.pintar("4"))
        self.assertIn("ayuda-aviso", clases)
        self.assertIn("Amazonas no tiene centros de formación registrados", texto)

    def test_escapa_los_nombres_del_catalogo(self):
        regionales = [{"id": 1, "nombre": '<script>alert(1)</script>"'}]
        centros = [{"id": 1, "regional_id": 1, "nombre": "<b>Centro</b>"}]
        html = self.pintar("1", regionales=regionales, centros=centros)
        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn("<b>Centro</b>", html)
        self.assertIn("&lt;b&gt;Centro&lt;/b&gt;", html)


if __name__ == "__main__":
    unittest.main()
