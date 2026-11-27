import click
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Dimension, Pregunta, Rol, Usuario

ROLES = {1: "admin", 2: "hr", 3: "user_personal", 4: "user_empresa"}

DIMENSIONES = {
    1: ("Agotamiento", "Fatiga física y mental severa."),
    2: ("Distanciamiento Mental", "Cinismo y evitación del trabajo."),
    3: ("Deterioro Cognitivo", "Problemas de concentración, memoria y atención."),
    4: ("Deterioro Emocional", "Falta de control sobre las emociones en el trabajo."),
}

# (id, dimension_id, texto): los ids son el contrato con el formulario (pregunta_<id>)
PREGUNTAS = [
    (1, 1, "En el trabajo, me siento mentalmente agotado/a."),
    (2, 1, "Después de un día de trabajo, me resulta difícil recuperar mi energía."),
    (3, 1, "Me siento físicamente agotado/a en el trabajo."),
    (4, 2, "Me cuesta encontrar entusiasmo por mi trabajo."),
    (5, 2, "Siento una fuerte aversión hacia mi trabajo."),
    (6, 2, "Soy cínico/a sobre lo que significa mi trabajo para los demás."),
    (7, 3, "En el trabajo, me cuesta mantener la concentración."),
    (8, 3, "Cuando estoy trabajando, cometo errores porque estoy distraído/a."),
    (9, 3, "En el trabajo, me cuesta pensar con claridad."),
    (10, 4, "En el trabajo, me siento incapaz de controlar mis emociones."),
    (11, 4, "No reconozco mi propia forma de reaccionar emocionalmente en el trabajo."),
    (12, 4, "En mi trabajo me irrito con facilidad sin saber por qué."),
]


def sembrar():
    """Roles, dimensiones y las 12 preguntas BAT-12. Idempotente."""
    for id_, nombre in ROLES.items():
        db.session.merge(Rol(id=id_, nombre=nombre))
    for id_, (nombre, desc) in DIMENSIONES.items():
        db.session.merge(Dimension(id=id_, nombre=nombre, descripcion=desc))
    db.session.flush()  # las preguntas referencian dimensiones
    for id_, dim, texto in PREGUNTAS:
        db.session.merge(Pregunta(id=id_, dimension_id=dim, texto=texto))
    db.session.commit()
    if db.engine.dialect.name == "postgresql":  # los ids explícitos no avanzan las secuencias
        for tabla in ("roles", "dimensiones", "preguntas"):
            db.session.execute(text(f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), (SELECT MAX(id) FROM {tabla}))"))
        db.session.commit()


def registrar(app):
    @app.cli.command("seed")
    def seed():
        """Carga roles, dimensiones y preguntas BAT-12 (idempotente)."""
        sembrar()
        click.echo("Datos base cargados.")

    @app.cli.command("crear-admin")
    @click.argument("email")
    @click.option("--nombre", default="Admin")
    @click.password_option()
    def crear_admin(email, nombre, password):
        """Crea un usuario administrador."""
        if Usuario.query.filter_by(email=email).first():
            raise click.ClickException("Ese email ya existe.")
        db.session.add(Usuario(rol_id=1, nombre=nombre, email=email, password=generate_password_hash(password)))
        db.session.commit()
        click.echo(f"Admin {email} creado.")
