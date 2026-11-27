from functools import wraps

from flask import flash, redirect, request, session, url_for


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated


def solo_admin(f):
    """Solo rol 1 (admin)."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if session.get("rol") != 1:
            flash("Acceso restringido a administradores.", "error")
            return redirect(url_for("dashboard.dashboard"))
        return f(*args, **kwargs)

    return decorated


def consentimiento_requerido(f):
    """Antes de recoger respuestas del test hace falta haber aceptado el tratamiento de datos."""
    from .extensions import db
    from .models import Usuario

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        usuario = db.session.get(Usuario, session["user_id"])
        if not usuario or not usuario.consentimiento_fecha:
            return redirect(url_for("cuenta.consentimiento", next=request.path))
        return f(*args, **kwargs)

    return decorated
