"""Idioma en servidor (Flask-Babel): es (por defecto), en y ca.

Orden de elección: cookie `lang` (botones ES/EN/CA) > Accept-Language > es. Quien inicia sesión
recibe la cookie con su idioma guardado, y cambiarlo actualiza usuarios.idioma (recordatorios, consejos).
"""
import os

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from flask import Blueprint, current_app, has_request_context, redirect, request, session
from flask_babel import Babel, get_locale  # noqa: F401  (get_locale se re-exporta)

from .extensions import db

IDIOMAS = ("es", "en", "ca")
COOKIE = "lang"
DIRECTORIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "translations")

babel = Babel()
bp = Blueprint("idioma", __name__)


def seleccionar_idioma():
    if not has_request_context():  # CLI, tareas programadas, tests de servicios
        return "es"
    elegido = request.cookies.get(COOKIE)
    if elegido in IDIOMAS:
        return elegido
    return request.accept_languages.best_match(IDIOMAS) or "es"


def compilar_traducciones():
    """.po -> .mo (los .mo no se versionan). Se llama al arrancar la app.

    Se escribe a un temporal y se renombra: con varios workers de gunicorn nadie lee un .mo a medias.
    """
    for idioma in IDIOMAS:
        po = os.path.join(DIRECTORIO, idioma, "LC_MESSAGES", "messages.po")
        if not os.path.exists(po):
            continue
        with open(po, "rb") as f:
            catalogo = read_po(f, locale=idioma)
        tmp = f"{po[:-2]}mo.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            write_mo(f, catalogo)
        os.replace(tmp, po[:-2] + "mo")


def poner_cookie(respuesta, idioma):
    respuesta.set_cookie(COOKIE, idioma, max_age=365 * 24 * 3600, samesite="Lax", httponly=True,
                         secure=current_app.config["SESSION_COOKIE_SECURE"])
    return respuesta


@bp.route("/idioma/<idioma>")
def cambiar(idioma):
    destino = request.args.get("next", "/")
    if not destino.startswith("/") or destino.startswith("//"):  # solo rutas internas
        destino = "/"
    if idioma not in IDIOMAS:
        return redirect(destino)
    if "user_id" in session:
        from .models import Usuario
        usuario = db.session.get(Usuario, session["user_id"])
        if usuario:
            usuario.idioma = idioma
            db.session.commit()
    return poner_cookie(redirect(destino), idioma)
