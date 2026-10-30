from flask import Flask, request, jsonify, render_template, session,url_for,redirect, flash# Importa Flask para crear la app web, manejar peticiones y usar plantillas HTML
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import secrets, hashlib
import psycopg2  # Permite conectarse y trabajar con bases de datos PostgreSQL
from psycopg2.extras import RealDictCursor  # Devuelve los resultados de las consultas como diccionarios (clave: valor)
import os  # Permite acceder a variables del sistema y manejar rutas de archivos
from datetime import datetime , timedelta
# Sirve para trabajar con fechas y horas
import vt
import time
import requests #sirve para el API
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from functools import wraps

load_dotenv()

app = Flask(__name__)


#***********Base de datos configuracion***********
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),       # ← 'localhost' para local
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": int(os.getenv("DB_PORT", 5432)),
    # 'database': os.getenv(''),
    # 'user': os.getenv(''),
    # 'password': os.getenv(''),
    # 'port': int(os.getenv())
    
}
#***********concexion a la base de datos***********
def conectar_bd():
    """Crea y devuelve una conexión a la base de datos PostgreSQL usando `DB_CONFIG`."""
    try:
        conexion = psycopg2.connect(**DB_CONFIG)
        return conexion
    except psycopg2.Error as e:
        print(f"Error al conectar a la base de datos: {e}")
        return None

 
def obtener_tipos_documento():
    """Trae las opciones del desplegable desde la base de datos."""
    with conectar_bd() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, nombre FROM tipos_documento ORDER BY nombre;")
        return cur.fetchall()
 
 
def validar_usuario(tipo_documento_id, numero_documento, password):
    """Devuelve el usuario si las credenciales son correctas; si no, None."""
    with conectar_bd() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, numero_documento, password_hash
            FROM usuarios
            WHERE tipo_documento_id = %s AND numero_documento = %s;
            """,
            (tipo_documento_id, numero_documento),
        )
        usuario = cur.fetchone()
 
    if usuario and check_password_hash(usuario["password_hash"], password):
        return usuario
    return None
 
 
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
    if request.method == "POST":
        tipo_documento_id = request.form.get("tipo_documento", "").strip()
        numero_documento = request.form.get("numero_documento", "").strip()
        password = request.form.get("password", "")
 
        if not (tipo_documento_id and numero_documento and password):
            flash("Por favor completa todos los campos.")
        else:
            usuario = validar_usuario(tipo_documento_id, numero_documento, password)
            if usuario:
                session.clear()
                session["usuario_id"] = usuario["id"]
                return redirect(url_for("inicio"))
            # Mensaje genérico: no revela cuál dato falló
            flash("Documento o contraseña incorrectos.")
 
    return render_template("login.html", tipos_documento=obtener_tipos_documento())
 
 
@app.route("/inicio")
@login_requerido
def inicio():
    return render_template("inicio.html")
 
 
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
 



#***********RUTAS DE VISTAS***********
@app.route('/')
def inicio():
    return render_template('index.html')

#************INICIO DE SESION***********


#************INICIO DEL SERVIDOR***********

if __name__ == '__main__':
    print("Iniciando servidor ROKO con MongoDB...")
    app.run(debug=True, host='0.0.0.0', port=5000)