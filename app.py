from functools import wraps
from flask import Flask, request, jsonify, render_template, session, url_for, redirect, flash
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


from db import buscar_usuario_por_correo
 
load_dotenv()
 
app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # SESSION_COOKIE_SECURE=True,  # actívalo cuando uses HTTPS en producción
)
 
 
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




       
#************INICIO DEL SERVIDOR***********


if __name__ == '__main__':
    print("Iniciando servidor ...")
    app.run(debug=True, host='0.0.0.0', port=5000)


 

crear_usuarios.py
"""
Crea un usuario de prueba con la contraseña ya cifrada.


Uso:
    python crear_usuario.py
"""
from datetime import date
from getpass import getpass


from werkzeug.security import generate_password_hash


from db import get_connection


nombre = input("Nombre: ").strip()
apellido = input("Apellido: ").strip()
tipo_documento = input("Tipo de documento (ej. CC): ").strip()
fecha_nacimiento = date.fromisoformat(input("Fecha de nacimiento (AAAA-MM-DD): ").strip())
correo = input("Correo: ").strip()
password = getpass("Contraseña: ")
nombre_rol = input("Nombre del rol (ej. Administrador): ").strip()
tipo_vinculacion = input("Tipo de vinculación (ej. Carrera administrativa, Provisional, Contratista): ").strip()


with get_connection() as conn:
    with conn.cursor() as cur:
        # Reutiliza el rol si ya existe; si no, lo crea
        cur.execute("SELECT id FROM roles WHERE nombre = %s", (nombre_rol,))
        fila = cur.fetchone()
        if fila:
            rol_id = fila["id"]
        else:
            cur.execute("INSERT INTO roles (nombre) VALUES (%s) RETURNING id", (nombre_rol,))
            rol_id = cur.fetchone()["id"]


        cur.execute(
            """
            INSERT INTO usuarios
                (nombre, apellido, tipo_documento, fecha_nacimiento,
                 correo, password_hash, tipo_vinculacion, rol_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (nombre, apellido, tipo_documento, fecha_nacimiento,
             correo, generate_password_hash(password), tipo_vinculacion, rol_id),
        )


print("Usuario creado correctamente.")
