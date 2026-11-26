import os

import psycopg2
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from actas import actas_bp
from seguridad import creacion_requerida, login_requerido
from db import buscar_usuario_por_correo, transaccion
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
    """Panel conectado al esquema legado real: actas.creado_por y compromisos JSONB."""
    from datetime import date, datetime

    usuario_id = session["usuario_id"]
    try:
        with transaccion() as cur:
            cur.execute(
                "SELECT tipo_vinculacion FROM public.usuarios WHERE id = %s AND activo = TRUE",
                (usuario_id,),
            )
            usuario = cur.fetchone() or {}

            # Esta instalación almacena el creador en creado_por, no en lider_id.
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE LOWER(COALESCE(estado, '')) = 'abierta') AS abiertas,
                       COUNT(*) FILTER (WHERE LOWER(COALESCE(estado, '')) = 'cerrada') AS cerradas
                FROM public.actas
                WHERE creado_por = %s
                """,
                (usuario_id,),
            )
            resumen_bd = cur.fetchone()

            # Últimas actas: en este esquema no existen numero_acta, ficha_id ni fecha_reunion.
            cur.execute(
                """
                SELECT id, nombre_comite, fecha, ciudad, estado
                FROM public.actas
                WHERE creado_por = %s
                ORDER BY fecha DESC NULLS LAST, id DESC
                LIMIT 5
                """,
                (usuario_id,),
            )
            ultimas_actas = cur.fetchall()

            # Los compromisos están guardados dentro de actas.compromisos (JSONB).
            cur.execute(
                """
                SELECT a.id AS acta_id,
                       c->>'actividad' AS actividad,
                       NULLIF(BTRIM(c->>'fecha'), '') AS fecha,
                       NULLIF(BTRIM(c->>'responsable'), '') AS responsable
                FROM public.actas AS a
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(a.compromisos) = 'array' THEN a.compromisos
                        ELSE '[]'::jsonb
                    END
                ) AS c
                WHERE a.creado_por = %s
                  AND NULLIF(BTRIM(c->>'actividad'), '') IS NOT NULL
                """,
                (usuario_id,),
            )
            filas_compromisos = cur.fetchall()

    except (psycopg2.Error, UnicodeDecodeError):
        app.logger.exception("No se pudieron cargar los datos del panel de inicio")
        return "No fue posible cargar el panel. Revisa la conexión y las columnas de PostgreSQL.", 503

    resumen = [
        {"titulo": "Total de actas", "valor": resumen_bd["total"], "icono": "file-text", "color": "verde"},
        {"titulo": "Actas abiertas", "valor": resumen_bd["abiertas"], "icono": "eye", "color": "azul"},
        {"titulo": "Actas cerradas", "valor": resumen_bd["cerradas"], "icono": "check-circle", "color": "verde"},
        {"titulo": "Compromisos registrados", "valor": len(filas_compromisos), "icono": "clock", "color": "rojo"},
    ]

    for acta in ultimas_actas:
        acta["num"] = str(acta["id"]).zfill(3)
        acta["fecha"] = acta["fecha"].strftime("%d/%m/%Y") if acta["fecha"] else "—"
        acta["programa"] = acta["nombre_comite"] or "Sin nombre"
        acta["ficha"] = "—"
        estado = (acta["estado"] or "abierta").strip().lower()
        acta["clase"] = "verde" if estado == "cerrada" else "azul"
        acta["estado_texto"] = estado.capitalize()

    # El JSONB actual no tiene campo completado. Por eso no se etiqueta como
    # completado/pending algo que la base no permite distinguir: se muestran
    # los compromisos con fecha futura como próximos.
    hoy = date.today()
    proximos_compromisos = []
    for fila in filas_compromisos:
        fecha_texto = fila["fecha"]
        try:
            fecha_obj = date.fromisoformat(fecha_texto) if fecha_texto else None
        except (TypeError, ValueError):
            fecha_obj = None
        if fecha_obj and fecha_obj >= hoy:
            proximos_compromisos.append({
                "titulo": fila["actividad"],
                "fecha": fecha_obj.strftime("%d/%m/%Y"),
                "estado": "Próximo",
                "clase": "amarillo",
                "color": "amarillo",
                "icono": "clock",
                "responsable": fila["responsable"] or "Sin asignar",
            })
    proximos_compromisos.sort(key=lambda c: datetime.strptime(c["fecha"], "%d/%m/%Y"))
    proximos_compromisos = proximos_compromisos[:3]

    return render_template(
        "inicio.html",
        nombre=session["nombre"],
        rol=session["rol"],
        tipo_vinculacion=usuario.get("tipo_vinculacion"),
        resumen=resumen,
        actas=ultimas_actas,
        compromisos=proximos_compromisos,
    )

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