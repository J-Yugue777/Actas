"""
Sesión y permisos compartidos por app.py, actas.py y secciones.py.
(Antes vivían dentro del actas.py viejo y estaban duplicados en app.py.)
"""
from functools import wraps

import psycopg2
from flask import abort, current_app, redirect, session, url_for

from db import transaccion

ROLES_ACCESO_GLOBAL = ("Administrador", "Coordinador académico")


def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return vista(*args, **kwargs)

    return envoltura


def puede_crear_acta(usuario_id):
    """True si su rol tiene puede_crear_acta, o si es Administrador / Coordinador académico."""
    try:
        with transaccion() as cur:
            cur.execute(
                "SELECT r.nombre, r.puede_crear_acta FROM usuarios u "
                "JOIN roles r ON r.id = u.rol_id WHERE u.id = %s AND u.activo",
                (usuario_id,),
            )
            fila = cur.fetchone()
    except psycopg2.Error:
        current_app.logger.exception("No se pudo comprobar el permiso de crear actas")
        return False
    return bool(fila and (fila["puede_crear_acta"] or fila["nombre"] in ROLES_ACCESO_GLOBAL))


def creacion_requerida(vista):
    """Exige sesión iniciada y permiso para crear actas."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        if not puede_crear_acta(session["usuario_id"]):
            abort(403)
        return vista(*args, **kwargs)

    return envoltura