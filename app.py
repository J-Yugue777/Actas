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


#***********RUTAS DE VISTAS***********
@app.route('/')
def inicio():
    return render_template('index.html')

#************INICIO DE SESION***********


#************INICIO DEL SERVIDOR***********

if __name__ == '__main__':
    print("Iniciando servidor ROKO con MongoDB...")
    app.run(debug=True, host='0.0.0.0', port=5000)