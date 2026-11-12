"""
Secciones del menú lateral: Mis actas, Asistentes, Compromisos, Usuarios,
Reportes y Configuración (cambiar contraseña).

Las plantillas llaman a estas rutas sin prefijo (url_for('mis_actas'), etc.),
por eso se registran con `secciones.registrar(app)` y no como blueprint.

Alcance de los datos:
- Mis actas, Asistentes y Compromisos: solo las actas que la persona lidera o
  en las que participa.
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

from actas import MESES, ROLES_TODAS_LAS_FICHAS, login_requerido, transaccion

ROL_ADMIN = "Administrador"
ESTADOS_ACTA = ("abierta", "cerrada")
FILTROS_COMPROMISO = ("todos", "pendiente", "completado")
MIN_PASSWORD = 8

# Actas a las que la persona tiene acceso: las que lidera o en las que participa
ACTAS_DE_LA_PERSONA = """
    SELECT id FROM actas WHERE lider_id = %(u)s
    UNION
    SELECT acta_id FROM acta_participantes WHERE usuario_id = %(u)s
"""


# ----------------------------------------------------------------- utilidades
@contextmanager
def consulta():
    """Cursor de solo uso interno: si la base falla, responde 503 y deja el error en el log."""
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
    estado = request.args.get("estado", "")
    if estado not in ESTADOS_ACTA:
        estado = ""

    condiciones = [f"a.id IN ({ACTAS_DE_LA_PERSONA})"]
    params = {"u": session["usuario_id"]}
    if q:
        condiciones.append("(a.nombre_reunion ILIKE %(pat)s OR a.numero_acta ILIKE %(pat)s)")
        params["pat"] = _patron(q)
    if estado:
        condiciones.append("a.estado = %(estado)s")
        params["estado"] = estado

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT a.id, a.numero_acta, a.nombre_reunion, a.fecha_reunion,
                   a.tipo_acta, a.estado, f.numero AS ficha
            FROM actas a
            LEFT JOIN fichas f ON f.id = a.ficha_id
            WHERE {' AND '.join(condiciones)}
            ORDER BY a.fecha_reunion DESC, a.id DESC
            LIMIT 200
            """,
            params,
        )
        actas = cur.fetchall()
    return render_template("mis_actas.html", actas=actas, q=q, estado=estado)


# ----------------------------------------------------------------- Asistentes
def asistentes():
    q = _texto_busqueda()
    filtro = ""
    params = {"u": session["usuario_id"]}
    if q:
        filtro = ("AND (u.nombre ILIKE %(pat)s OR u.apellido ILIKE %(pat)s "
                  "OR u.correo ILIKE %(pat)s OR (u.nombre || ' ' || u.apellido) ILIKE %(pat)s)")
        params["pat"] = _patron(q)

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT u.id, u.nombre, u.apellido, u.correo, r.nombre AS rol,
                   COUNT(*) AS total_actas,
                   COUNT(*) FILTER (WHERE p.desarrollo IS NOT NULL
                                       OR p.conclusiones IS NOT NULL) AS aportes
            FROM acta_participantes p
            JOIN usuarios u ON u.id = p.usuario_id
            JOIN roles r ON r.id = u.rol_id
            WHERE p.acta_id IN ({ACTAS_DE_LA_PERSONA}) {filtro}
            GROUP BY u.id, r.nombre
            ORDER BY u.apellido, u.nombre
            """,
            params,
        )
        lista = cur.fetchall()

    con_aporte = sum(1 for p in lista if p["aportes"] == p["total_actas"])
    return render_template("asistentes.html", asistentes=lista, con_aporte=con_aporte, q=q)


# ---------------------------------------------------------------- Compromisos
def _compromiso_para_plantilla(fila):
    hecho = fila["completado"]
    return {
        "titulo": fila["actividad"],
        "acta": fila["consecutivo"],
        "responsable": fila["responsable"] or "Sin asignar",
        "fecha": fila["fecha_entrega"].strftime("%d/%m/%Y"),
        "estado": "Completado" if hecho else "Pendiente",
        "clase": "verde" if hecho else "amarillo",
        "icono": "check-circle" if hecho else "clock",
        "color": "verde" if hecho else "amarillo",
        "hecho": hecho,
    }


def compromisos():
    filtro = request.args.get("estado", "todos")
    if filtro not in FILTROS_COMPROMISO:
        filtro = "todos"

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT c.actividad, c.fecha_entrega, c.completado, a.consecutivo,
                   COALESCE(ur.nombre || ' ' || ur.apellido, c.responsable_texto) AS responsable
            FROM acta_compromisos c
            JOIN actas a ON a.id = c.acta_id
            LEFT JOIN usuarios ur ON ur.id = c.responsable_id
            WHERE c.acta_id IN ({ACTAS_DE_LA_PERSONA})
            ORDER BY c.completado, c.fecha_entrega
            """,
            {"u": session["usuario_id"]},
        )
        todos = [_compromiso_para_plantilla(f) for f in cur.fetchall()]

    conteos = {
        "todos": len(todos),
        "pendiente": sum(1 for c in todos if not c["hecho"]),
        "completado": sum(1 for c in todos if c["hecho"]),
    }
    if filtro == "pendiente":
        todos = [c for c in todos if not c["hecho"]]
    elif filtro == "completado":
        todos = [c for c in todos if c["hecho"]]
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
    todo_el_sistema = session.get("rol") in ROLES_TODAS_LAS_FICHAS
    alcance = "TRUE" if todo_el_sistema else f"a.id IN ({ACTAS_DE_LA_PERSONA})"

    with consulta() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE a.estado = 'abierta') AS abiertas
            FROM actas a WHERE {alcance}
            """,
            params,
        )
        resumen = cur.fetchone()

        cur.execute(
            f"""
            SELECT COUNT(DISTINCT p.usuario_id) AS n
            FROM acta_participantes p
            JOIN actas a ON a.id = p.acta_id
            WHERE {alcance}
            """,
            params,
        )
        participantes = cur.fetchone()["n"]

        cur.execute(
            f"""
            SELECT EXTRACT(MONTH FROM a.fecha_reunion)::int AS mes, COUNT(*) AS n
            FROM actas a
            WHERE {alcance} AND a.anio = %(anio)s
            GROUP BY 1
            """,
            params,
        )
        por_mes_bd = {fila["mes"]: fila["n"] for fila in cur.fetchall()}

        cur.execute(
            f"""
            SELECT c.nombre AS centro, COUNT(*) AS n
            FROM actas a
            JOIN centros_formacion c ON c.id = a.centro_id
            WHERE {alcance}
            GROUP BY c.nombre
            ORDER BY n DESC, c.nombre
            LIMIT 10
            """,
            params,
        )
        por_centro = cur.fetchall()

    por_mes = [{"mes": nombre[:3], "n": por_mes_bd.get(i, 0)} for i, nombre in enumerate(MESES, start=1)]
    return render_template(
        "reportes.html",
        total=resumen["total"], abiertas=resumen["abiertas"], participantes=participantes,
        anio=anio, por_mes=por_mes, maximo=max(1, *(m["n"] for m in por_mes)),
        por_centro=por_centro,
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
    def inyectar_rol():
        # Para mostrar "Usuarios" en el menú solo a quien puede entrar
        return {"es_admin": session.get("rol") == ROL_ADMIN}