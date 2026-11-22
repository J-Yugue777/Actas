import os

import psycopg2
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from actas import actas_bp
from seguridad import creacion_requerida, login_requerido
from db import buscar_usuario_por_correo
import secciones

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=50 * 1024 * 1024,  # tope de la petición (las imágenes viajan en base64)
    # SESSION_COOKIE_SECURE=True,  # actívalo cuando uses HTTPS en producción
)
app.register_blueprint(actas_bp)
secciones.registrar(app)


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
            return render_template("Login.html", correo=correo)

        try:
            usuario = buscar_usuario_por_correo(correo)
        except (psycopg2.Error, UnicodeDecodeError) as error:
            # UnicodeDecodeError: en Windows, PostgreSQL en español rechaza la conexión
            # (clave o base equivocada) con un mensaje que psycopg2 no puede leer.
            app.logger.error("Error de base de datos: %s", error)
            flash("No pudimos conectar con el servidor. Intenta de nuevo en unos minutos.")
            return render_template("Login.html", correo=correo)

        credenciales_validas = (
            usuario is not None
            and usuario["password_hash"]
            and check_password_hash(usuario["password_hash"], password)
        )

        if not credenciales_validas:
            # Mensaje genérico: no revela si el correo existe o no
            flash("Correo o contraseña incorrectos.")
            return render_template("Login.html", correo=correo)

        if not usuario["activo"]:
            flash("Tu cuenta está desactivada. Contacta al administrador.")
            return render_template("Login.html", correo=correo)

        session.clear()
        session["usuario_id"] = usuario["id"]
        session["nombre"] = f'{usuario["nombre"]} {usuario["apellido"]}'
        session["rol"] = usuario["rol"]
        return redirect(url_for("inicio"))

    return render_template("Login.html", correo="")


@app.route("/inicio")
@login_requerido
def inicio():
    return render_template("inicio.html", nombre=session["nombre"], rol=session["rol"])


@app.route("/actas/nueva")
@creacion_requerida
def crear_acta():
    """Formulario del acta GOR-F084 V2 (acta.html envía el JSON a /api/actas)."""
    return render_template("acta.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ************ INICIO DEL SERVIDOR ***********
if __name__ == "__main__":
    print("Iniciando servidor ...")
    app.run(debug=True, host="0.0.0.0", port=5000)