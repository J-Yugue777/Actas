"""
Secciones del menú lateral: Mis actas, Asistentes, Compromisos, Usuarios,
Reportes y Configuración (cambiar contraseña).

Leen la tabla `actas` del modelo GOR-F084 V2 (actas.py): cada acta es una fila y sus
asistentes y compromisos viven como arreglos JSON dentro de ella.

Alcance de los datos:
- Mis actas, Asistentes y Compromisos: solo las actas que creó la persona.
- Reportes: todo el sistema para Administrador y Coordinador académico;
  para los demás, solo sus propias actas.
- Usuarios: solo Administrador.
"""
from contextlib import contextmanager
from datetime import date

import psycopg2
from flask import (abort, current_app, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from seguridad import ROLES_ACCESO_GLOBAL, login_requerido, puede_crear_acta
from db import transaccion

ROL_ADMIN = "Administrador"
FILTROS_COMPROMISO = ("todos", "vigente", "vencido")
MIN_PASSWORD = 8
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _arreglo(columna):
    """Expresión SQL que devuelve la columna JSON como arreglo (o [] si no lo es)."""
    return (f"(CASE WHEN jsonb_typeof(a.{columna}) = 'array' "
            f"THEN a.{columna} ELSE '[]'::jsonb END)")


# ----------------------------------------------------------------- utilidades
@contextmanager
def consulta():
    """Cursor de uso interno: si la base falla, responde 503 y deja el error en el log."""
    try:
        with transaccion() as cur:
            yield cur
    except psycopg2.Error:
        current_app.logger.exception("Error de base de datos")
        abort(503)


def _patron(texto):
    """Convierte lo que escribe la persona en un patrón ILIKE sin comodines propios."""
    texto = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{texto}%"


def _texto_busqueda():
    return request.args.get("q", "").strip()[:100]


# ------------------------------------------------------------------ Mis actas
def mis_actas():
    q = _texto_busqueda()
    condiciones = ["a.creado_por = %(u)s"]
    params = {"u": session["usuario_id"]}
    if q:
        condiciones.append("(a.nombre_comite ILIKE %(pat)s OR a.ciudad ILIKE %(pat)s)")
        params["pat"] = _patron(q)

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT a.id, a.nombre_comite, a.ciudad, a.fecha, a.direccion_regional
            FROM actas a
            WHERE {' AND '.join(condiciones)}
            ORDER BY a.fecha DESC NULLS LAST, a.id DESC
            LIMIT 200
            """,
            params,
        )
        actas = cur.fetchall()
    return render_template("mis_actas.html", actas=actas, q=q)


# ----------------------------------------------------------------- Asistentes
def asistentes():
    q = _texto_busqueda()
    filtro = ""
    params = {"u": session["usuario_id"]}
    if q:
        filtro = "AND ((x->>'nombre') ILIKE %(pat)s OR (x->>'dependencia') ILIKE %(pat)s)"
        params["pat"] = _patron(q)

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT MIN(TRIM(x->>'nombre')) AS nombre,
                   MAX(NULLIF(TRIM(x->>'dependencia'), '')) AS dependencia,
                   COUNT(DISTINCT a.id) AS total_actas,
                   COUNT(DISTINCT a.id) FILTER (WHERE x->>'aprueba' = 'si') AS aprobadas
            FROM actas a, jsonb_array_elements({_arreglo('asistentes')}) x
            WHERE a.creado_por = %(u)s
              AND TRIM(COALESCE(x->>'nombre', '')) <> '' {filtro}
            GROUP BY LOWER(TRIM(x->>'nombre'))
            ORDER BY 1
            """,
            params,
        )
        lista = cur.fetchall()

    aprueban_todo = sum(1 for p in lista if p["aprobadas"] == p["total_actas"])
    return render_template("asistentes.html", asistentes=lista, aprueban_todo=aprueban_todo, q=q)


# ---------------------------------------------------------------- Compromisos
def _compromiso_para_plantilla(fila, hoy):
    try:
        limite = date.fromisoformat(fila["fecha"]) if fila["fecha"] else None
    except ValueError:
        limite = None

    if limite is None:
        estado, clase, icono, color, vencido = "Sin fecha", "gris", "clipboard", "amarillo", False
    elif limite < hoy:
        estado, clase, icono, color, vencido = "Vencido", "rojo", "clock", "rojo", True
    else:
        estado, clase, icono, color, vencido = "Vigente", "azul", "clock", "azul", False

    return {
        "titulo": fila["actividad"],
        "acta": fila["acta_id"],
        "responsable": fila["responsable"] or "Sin asignar",
        "fecha": limite.strftime("%d/%m/%Y") if limite else "—",
        "estado": estado, "clase": clase, "icono": icono, "color": color,
        "vencido": vencido,
    }


def compromisos():
    filtro = request.args.get("estado", "todos")
    if filtro not in FILTROS_COMPROMISO:
        filtro = "todos"

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT a.id AS acta_id,
                   TRIM(c->>'actividad') AS actividad,
                   NULLIF(TRIM(c->>'fecha'), '') AS fecha,
                   NULLIF(TRIM(c->>'responsable'), '') AS responsable
            FROM actas a, jsonb_array_elements({_arreglo('compromisos')}) c
            WHERE a.creado_por = %(u)s
              AND TRIM(COALESCE(c->>'actividad', '')) <> ''
            ORDER BY fecha NULLS LAST, a.id
            """,
            {"u": session["usuario_id"]},
        )
        hoy = date.today()
        todos = [_compromiso_para_plantilla(f, hoy) for f in cur.fetchall()]

    conteos = {
        "todos": len(todos),
        "vigente": sum(1 for c in todos if not c["vencido"]),
        "vencido": sum(1 for c in todos if c["vencido"]),
    }
    if filtro == "vigente":
        todos = [c for c in todos if not c["vencido"]]
    elif filtro == "vencido":
        todos = [c for c in todos if c["vencido"]]
    return render_template("compromisos.html", compromisos=todos, conteos=conteos, filtro=filtro)


# ------------------------------------------------------------------- Usuarios
def usuarios():
    if session.get("rol") != ROL_ADMIN:
        abort(403)

    q = _texto_busqueda()
    rol_filtro = request.args.get("rol", "").strip()

    condiciones, params = ["TRUE"], {}
    if q:
        condiciones.append("(u.nombre ILIKE %(pat)s OR u.apellido ILIKE %(pat)s "
                           "OR u.correo ILIKE %(pat)s OR (u.nombre || ' ' || u.apellido) ILIKE %(pat)s)")
        params["pat"] = _patron(q)
    if rol_filtro:
        condiciones.append("r.nombre = %(rol)s")
        params["rol"] = rol_filtro

    with consulta() as cur:
        cur.execute("SELECT nombre FROM roles ORDER BY nombre")
        roles = cur.fetchall()
        cur.execute(
            f"""
            SELECT u.nombre, u.apellido, u.correo, u.tipo_vinculacion,
                   u.telefono, u.activo, r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id = u.rol_id
            WHERE {' AND '.join(condiciones)}
            ORDER BY u.apellido, u.nombre
            LIMIT 500
            """,
            params,
        )
        lista = cur.fetchall()
    return render_template("usuarios.html", usuarios=lista, roles=roles, q=q, rol_filtro=rol_filtro)


# -------------------------------------------------------------------- Reportes
def reportes():
    anio = date.today().year
    params = {"u": session["usuario_id"], "anio": anio}
    todo_el_sistema = session.get("rol") in ROLES_ACCESO_GLOBAL
    alcance = "TRUE" if todo_el_sistema else "a.creado_por = %(u)s"

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM a.fecha) = %(anio)s) AS este_anio,
                   COALESCE(SUM(jsonb_array_length({_arreglo('asistentes')})), 0) AS asistentes,
                   COALESCE(SUM(jsonb_array_length({_arreglo('compromisos')})), 0) AS compromisos
            FROM actas a WHERE {alcance}
            """,
            params,
        )
        resumen = cur.fetchone()

        cur.execute(
            f"""
            SELECT EXTRACT(MONTH FROM a.fecha)::int AS mes, COUNT(*) AS n
            FROM actas a
            WHERE {alcance} AND EXTRACT(YEAR FROM a.fecha) = %(anio)s
            GROUP BY 1
            """,
            params,
        )
        por_mes_bd = {fila["mes"]: fila["n"] for fila in cur.fetchall()}

        cur.execute(
            f"""
            SELECT COALESCE(NULLIF(TRIM(a.direccion_regional), ''), 'Sin regional') AS regional,
                   COUNT(*) AS n
            FROM actas a
            WHERE {alcance}
            GROUP BY 1
            ORDER BY n DESC, 1
            LIMIT 10
            """,
            params,
        )
        por_regional = cur.fetchall()

    por_mes = [{"mes": nombre[:3], "n": por_mes_bd.get(i, 0)} for i, nombre in enumerate(MESES, start=1)]
    return render_template(
        "reportes.html",
        total=resumen["total"], este_anio=resumen["este_anio"],
        asistentes=resumen["asistentes"], compromisos=resumen["compromisos"],
        anio=anio, por_mes=por_mes, maximo=max(1, *(m["n"] for m in por_mes)),
        por_regional=por_regional,
    )


# --------------------------------------------------------------- Configuración
def configuracion():
    with consulta() as cur:
        cur.execute(
            """
            SELECT u.nombre, u.apellido, u.correo, u.tipo_vinculacion,
                   u.telefono, u.direccion, r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id = u.rol_id
            WHERE u.id = %s
            """,
            (session["usuario_id"],),
        )
        perfil = cur.fetchone()
    if perfil is None:
        session.clear()
        return redirect(url_for("login"))
    return render_template("configuracion.html", perfil=perfil)


def cambiar_password():
    actual = request.form.get("actual", "")
    nueva = request.form.get("nueva", "")
    confirmar = request.form.get("confirmar", "")

    def error(mensaje):
        flash(mensaje, "error")
        return redirect(url_for("configuracion"))

    if not actual or not nueva or not confirmar:
        return error("Completa los tres campos.")
    if len(nueva) < MIN_PASSWORD:
        return error(f"La contraseña nueva debe tener al menos {MIN_PASSWORD} caracteres.")
    if nueva != confirmar:
        return error("La confirmación no coincide con la contraseña nueva.")
    if nueva == actual:
        return error("La contraseña nueva debe ser distinta de la actual.")

    with consulta() as cur:
        cur.execute("SELECT password_hash FROM usuarios WHERE id = %s", (session["usuario_id"],))
        fila = cur.fetchone()
        if not fila or not fila["password_hash"] or not check_password_hash(fila["password_hash"], actual):
            return error("La contraseña actual no es correcta.")
        cur.execute(
            "UPDATE usuarios SET password_hash = %s WHERE id = %s",
            (generate_password_hash(nueva), session["usuario_id"]),
        )

    flash("Tu contraseña se actualizó correctamente.", "ok")
    return redirect(url_for("configuracion"))


# ------------------------------------------------------------------- Registro
def registrar(app):
    """Conecta las rutas a la app con los nombres que usan las plantillas."""
    reglas = [
        ("/mis-actas", mis_actas, ["GET"]),
        ("/asistentes", asistentes, ["GET"]),
        ("/compromisos", compromisos, ["GET"]),
        ("/usuarios", usuarios, ["GET"]),
        ("/reportes", reportes, ["GET"]),
        ("/configuracion", configuracion, ["GET"]),
        ("/configuracion/password", cambiar_password, ["POST"]),
    ]
    for ruta, vista, metodos in reglas:
        app.add_url_rule(ruta, endpoint=vista.__name__,
                         view_func=login_requerido(vista), methods=metodos)

    @app.context_processor
    def inyectar_menu():
        # Para mostrar "Usuarios" y "Crear acta" en el menú solo a quien puede usarlos
        if "usuario_id" not in session:
            return {}
        return {
            "es_admin": session.get("rol") == ROL_ADMIN,
            "puede_crear_acta": puede_crear_acta(session["usuario_id"]),
        }