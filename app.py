from flask import Flask, request, jsonify, render_template, session, url_for, redirect, flash
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

load_dotenv()

app = Flask(__name__)

#***********RUTAS DE VISTAS***********
@app.route('/')
def inicio():
    return render_template('index.html')

#************INICIO DE SESION***********


#************INICIO DEL SERVIDOR***********

if __name__ == '__main__':
    print("Iniciando servidor ROKO con MongoDB...")
    app.run(debug=True, host='0.0.0.0', port=5000)