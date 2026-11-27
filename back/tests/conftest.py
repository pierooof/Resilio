import os

import pytest
from flask import g

from resilio import create_app
from resilio.cli import sembrar
from resilio.extensions import db

# TEST_DATABASE_URL=postgresql+psycopg://... para los tests que ejecutan SQL de Postgres
PG_URL = os.getenv("TEST_DATABASE_URL")
necesita_pg = pytest.mark.skipif(not PG_URL, reason="requiere TEST_DATABASE_URL (PostgreSQL)")

BASE = {
    "TESTING": True,
    "SECRET_KEY": "test",
    "SQLALCHEMY_DATABASE_URI": PG_URL or "sqlite://",
    "WTF_CSRF_ENABLED": False,
    "RATELIMIT_ENABLED": False,
    "SESSION_COOKIE_SECURE": False,
    "MAIL_SUPPRESS_SEND": True,
    "MAIL_DEFAULT_SENDER": "noreply@test.local",
}


def crear(**config):
    app = create_app({**BASE, **config})

    @app.before_request
    def _olvidar_idioma():
        # Flask-Babel cachea el idioma en `g`; en producción cada petición tiene su contexto, pero
        # aquí el fixture mantiene uno abierto y las peticiones del test lo comparten.
        g.pop("_flask_babel", None)

    with app.app_context():
        db.drop_all()
        db.create_all()
        sembrar()
    return app


@pytest.fixture
def app():
    app = crear()
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
