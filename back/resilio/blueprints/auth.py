import hashlib
import hmac
from datetime import datetime

from flask_babel import gettext as _
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import get_locale
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, limiter, mail
from ..i18n import COOKIE, IDIOMAS, poner_cookie
from ..models import Usuario
from ..services.codigos import CodigoInvalido, resolver_codigo

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 8
RESET_MAX_AGE = 3600


def _huella(usuario):
    """Parte del hash de la contraseña: el token deja de valer al cambiarla."""
    return hashlib.sha256(usuario.password.encode()).hexdigest()[:16]


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="reset-password")


def _usuario_de_token(token):
    try:
        datos = _serializer().loads(token, max_age=RESET_MAX_AGE)
        usuario = db.session.get(Usuario, int(datos["u"]))
    except Exception:  # firma inválida, caducado o payload raro
        return None
    if usuario and hmac.compare_digest(datos["f"], _huella(usuario)):
        return usuario
    return None


@bp.route("/")
def index():
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and check_password_hash(usuario.password, request.form.get("password", "")):
            session["user_id"] = usuario.id
            session["nombre"] = usuario.nombre
            session["rol"] = usuario.rol_id
            session["empresa_id"] = usuario.empresa_id
            session["departamento_id"] = usuario.departamento_id
            session["nombre_empresa"] = usuario.empresa.nombre if usuario.empresa else None
            session["nombre_dept"] = usuario.departamento.nombre if usuario.departamento else None
            respuesta = redirect(url_for("dashboard.dashboard"))
            if request.cookies.get(COOKIE) not in IDIOMAS:  # sin elección explícita: su idioma guardado
                poner_cookie(respuesta, usuario.idioma)
            return respuesta
        flash(_("Email o contraseña incorrectos"), "error")
        return redirect(url_for("auth.login"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard"))

    if request.method == "POST":
        f = request.form
        email = f.get("email", "").strip()
        nombre = f.get("nombre", "").strip()
        if not nombre or "@" not in email:
            flash(_("Nombre y email válidos son obligatorios."), "error")
            return redirect(url_for("auth.register"))
        if len(f.get("password", "")) < MIN_PASSWORD:
            flash(_("La contraseña debe tener al menos %(n)s caracteres.", n=MIN_PASSWORD), "error")
            return redirect(url_for("auth.register"))
        if Usuario.query.filter_by(email=email).first():
            flash(_("Este email ya está registrado. Por favor, inicia sesión."), "error")
            return redirect(url_for("auth.register"))

        rol_id, empresa_id, departamento_id = 3, None, None
        codigo = f.get("codigo_empresa", "").strip()
        if codigo:
            try:
                empresa_id, departamento_id = resolver_codigo(codigo)
            except CodigoInvalido as e:
                flash(str(e), "error")
                return redirect(url_for("auth.register"))
            rol_id = 4

        db.session.add(
            Usuario(
                rol_id=rol_id,
                empresa_id=empresa_id,
                departamento_id=departamento_id,
                nombre=nombre,
                apellidos=f.get("apellidos", "").strip() or None,
                email=email,
                password=generate_password_hash(f["password"]),
                idioma=str(get_locale()),
                consentimiento_fecha=datetime.now() if f.get("acepto") else None,
            )
        )
        try:
            db.session.commit()
        except IntegrityError:  # carrera con otro registro del mismo email
            db.session.rollback()
            flash(_("Este email ya está registrado. Por favor, inicia sesión."), "error")
            return redirect(url_for("auth.register"))
        flash(_("¡Cuenta creada con éxito! Ya puedes iniciar sesión."), "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@bp.route("/forgot_password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            token = _serializer().dumps({"u": usuario.id, "f": _huella(usuario)})
            reset_url = url_for("auth.reset_password", token=token, _external=True)
            msg = Message("Restablecer Contraseña - Resilio", recipients=[email])
            msg.body = (
                f"Hola {usuario.nombre},\n\n"
                f"Para restablecer tu contraseña, visita el siguiente enlace:\n{reset_url}\n\n"
                "Si no realizaste esta solicitud, simplemente ignora este correo.\n\n"
                "Saludos,\nEl equipo de Resilio\n"
            )
            try:
                mail.send(msg)
            except Exception:
                current_app.logger.exception("No se pudo enviar el correo de recuperación")
        # Misma respuesta exista o no el email (evita enumerar usuarios)
        flash(_("Si el correo existe en nuestro sistema, recibirás un enlace de recuperación."), "success")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.html")


@bp.route("/reset_password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    usuario = _usuario_de_token(token)
    if not usuario:
        flash(_("El enlace es inválido o ha expirado."), "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if password != request.form.get("confirm_password"):
            flash(_("Las contraseñas no coinciden."), "error")
        elif len(password) < MIN_PASSWORD:
            flash(_("La contraseña debe tener al menos %(n)s caracteres.", n=MIN_PASSWORD), "error")
        else:
            usuario.password = generate_password_hash(password)
            db.session.commit()
            flash(_("Tu contraseña ha sido actualizada exitosamente."), "success")
            return redirect(url_for("auth.login"))
    return render_template("reset_password.html", token=token)
