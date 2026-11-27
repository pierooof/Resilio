import os

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import csrf, db, limiter, mail, migrate


def _database_url():
    """DATABASE_URL (Railway la da como postgres://...) -> driver psycopg 3."""
    url = os.getenv("DATABASE_URL", "")
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url or None


def _flag(nombre, defecto):
    return os.getenv(nombre, defecto).lower() in ("1", "true", "t", "yes")


def create_app(config=None):
    load_dotenv()
    # plantillas y estáticos viven en back/templates y back/static
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_flag("COOKIE_SECURE", "1"),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
        MAIL_USE_TLS=_flag("MAIL_USE_TLS", "1"),
        MAIL_USE_SSL=_flag("MAIL_USE_SSL", "0"),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER", os.getenv("MAIL_USERNAME")),
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY es obligatoria (sin ella las sesiones y tokens no son fiables).")

    # Detrás del proxy de Railway: sin esto el rate-limit vería una sola IP para todos
    hops = int(os.getenv("PROXY_HOPS", 1))
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    from .blueprints import admin, auth, dashboard, test
    for modulo in (auth, dashboard, admin, test):
        app.register_blueprint(modulo.bp)

    from .cli import registrar
    registrar(app)
    return app
