from functools import wraps
from flask import Blueprint, Flask, request, jsonify, render_template, session, url_for, redirect, flash, abort
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import secrets, hashlib, uuid
import threading
import os
from datetime import datetime, timedelta
import vt
import time
import requests
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from psycopg2.extras import RealDictCursor


from db import (
    buscar_usuario_por_correo,
    acta_del_lider, listar_items, agregar_item, eliminar_item,
    TIPOS_ITEM, MAX_LARGO_ITEM,
)
from actas import (actas_bp)
from aportes import aportes_bp
from pdf_acta import pdf_bp
import secciones

load_dotenv()
 
app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=50 * 1024 * 1024,  # tope de toda la petición (US-012: adjuntos)
    # SESSION_COOKIE_SECURE=True,  # actívalo cuando uses HTTPS en producción
)
app.register_blueprint(actas_bp)
app.register_blueprint(aportes_bp)
app.register_blueprint(pdf_bp)
secciones.registrar(app)
 
 
def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return vista(*args, **kwargs)
 
    return envoltura
 
 
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if "usuario_id" in session:
        return redirect(url_for("inicio"))
 
    if request.method == "POST":
        correo = request.form.get("correo", "").strip()
        password = request.form.get("password", "")
 
        if not correo or not password:
            flash("Escribe tu correo y tu contraseña.")
            return render_template("login.html", correo=correo)
 
        try:
            usuario = buscar_usuario_por_correo(correo)
        except psycopg2.Error as error:
            app.logger.error("Error de base de datos: %s", error)
            flash("No pudimos conectar con el servidor. Intenta de nuevo en unos minutos.")
            return render_template("login.html", correo=correo)
 
        credenciales_validas = (
            usuario is not None
            and usuario["password_hash"]
            and check_password_hash(usuario["password_hash"], password)
        )
 
        if not credenciales_validas:
            # Mensaje genérico: no revela si el correo existe o no
            flash("Correo o contraseña incorrectos.")
            return render_template("login.html", correo=correo)
 
        if not usuario["activo"]:
            flash("Tu cuenta está desactivada. Contacta al administrador.")
            return render_template("login.html", correo=correo)
 
        session.clear()
        session["usuario_id"] = usuario["id"]
        session["nombre"] = f'{usuario["nombre"]} {usuario["apellido"]}'
        session["rol"] = usuario["rol"]
        return redirect(url_for("inicio"))
 
    return render_template("login.html", correo="")
 
 
@app.route("/inicio")
@login_requerido
def inicio():
    return render_template("inicio.html", nombre=session["nombre"], rol=session["rol"])
 
 
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))



# ---------------------------------------------------------------------------
# Agenda y objetivos del acta (solo el líder del acta)
# ---------------------------------------------------------------------------
def _acta_propia_o_404(acta_id):
    if not acta_del_lider(acta_id, session["usuario_id"]):
        abort(404)  # no revela si el acta existe pero es de otro líder


@app.route("/actas/<int:acta_id>/agenda-objetivos")
@login_requerido
def agenda_objetivos(acta_id):
    _acta_propia_o_404(acta_id)
    return render_template(
        "agenda_objetivos.html",
        nombre=session["nombre"], rol=session["rol"],
        acta_id=acta_id, items=listar_items(acta_id), max_largo=MAX_LARGO_ITEM,
    )


@app.route("/actas/<int:acta_id>/items", methods=["POST"])
@login_requerido
def agregar_item_acta(acta_id):
    _acta_propia_o_404(acta_id)
    tipo = request.form.get("tipo", "")
    if tipo not in TIPOS_ITEM:
        abort(400)
    try:
        agregar_item(acta_id, tipo, request.form.get("descripcion", ""))
    except ValueError as error:
        flash(str(error))
    except psycopg2.Error as error:
        app.logger.error("Error de base de datos: %s", error)
        flash("No pudimos guardar el ítem. Intenta de nuevo.")
    return redirect(url_for("agenda_objetivos", acta_id=acta_id) + f"#{tipo}")


@app.route("/actas/<int:acta_id>/items/<int:item_id>/eliminar", methods=["POST"])
@login_requerido
def eliminar_item_acta(acta_id, item_id):
    _acta_propia_o_404(acta_id)
    try:
        if not eliminar_item(acta_id, item_id):
            flash("Ese ítem ya no existe.")
    except psycopg2.Error as error:
        app.logger.error("Error de base de datos: %s", error)
        flash("No pudimos quitar el ítem. Intenta de nuevo.")
    return redirect(url_for("agenda_objetivos", acta_id=acta_id))


#************INICIO DEL SERVIDOR***********


if __name__ == '__main__':
    print("Iniciando servidor ...")
    app.run(debug=True, host='0.0.0.0', port=5000)

