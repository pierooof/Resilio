import os
from datetime import datetime

import click
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Dimension, Pregunta, PreguntaTraduccion, Rol, Usuario

ROLES = {1: "admin", 2: "hr", 3: "user_personal", 4: "user_empresa"}

DIMENSIONES = {
    1: ("Agotamiento", "Fatiga física y mental severa."),
    2: ("Distanciamiento Mental", "Cinismo y evitación del trabajo."),
    3: ("Deterioro Cognitivo", "Problemas de concentración, memoria y atención."),
    4: ("Deterioro Emocional", "Falta de control sobre las emociones en el trabajo."),
}

# (id, dimension_id, texto oficial en español): los ids son el contrato con el formulario (pregunta_<id>)
PREGUNTAS = [
    (1, 1, "En mi trabajo, me siento agotado/a mentalmente"),
    (2, 1, "Al final del día de trabajo, me resulta difícil recuperar mi energía"),
    (3, 1, "Me siento físicamente agotado/a en mi trabajo"),
    (4, 2, "Me esfuerzo por encontrar entusiasmo en mi trabajo"),
    (5, 2, "Siento una fuerte aversión hacia mi trabajo"),
    (6, 2, "Soy cínico sobre lo que mi trabajo significa para los demás"),
    (7, 3, "Tengo problemas para mantenerme enfocado en mi trabajo"),
    (8, 3, "Cuando estoy trabajando, tengo dificultades para concentrarme"),
    (9, 3, "Cometo errores en mi trabajo, porque tengo mi mente en otras cosas"),
    (10, 4, "En mi trabajo, me siento incapaz de controlar mis emociones"),
    (11, 4, "No me reconozco en la forma que reacciono en el trabajo"),
    (12, 4, "Puedo reaccionar exageradamente sin querer"),
]

# Textos oficiales del BAT-12 (https://burnoutassessmenttool.be, cuestionario "Versión corta (BAT-12)" en
# español y marcados con * en la versión inglesa de 23 ítems). El instrumento no debe modificarse y hay que
# citar a Schaufeli, Desart & De Witte (2020). NO existe versión oficial en catalán: la de abajo es una
# traducción propia, no validada, y la interfaz lo avisa.
TRADUCCIONES = {
    "en": [
        "At work, I feel mentally exhausted",
        "After a day at work, I find it hard to recover my energy",
        "At work, I feel physically exhausted",
        "I struggle to find any enthusiasm for my work",
        "I feel a strong aversion towards my job",
        "I'm cynical about what my work means to others",
        "At work, I have trouble staying focused",
        "When I'm working, I have trouble concentrating",
        "I make mistakes in my work because I have my mind on other things",
        "At work, I feel unable to control my emotions",
        "I do not recognize myself in the way I react emotionally at work",
        "At work I may overreact unintentionally",
    ],
    "ca": [
        "A la feina, em sento esgotat/ada mentalment",
        "Al final del dia de feina, em costa recuperar l'energia",
        "Em sento físicament esgotat/ada a la feina",
        "Em costa trobar entusiasme per la meva feina",
        "Sento una forta aversió envers la meva feina",
        "Sóc cínic/a sobre el que significa la meva feina per als altres",
        "Tinc problemes per mantenir-me concentrat/ada a la feina",
        "Quan estic treballant, tinc dificultats per concentrar-me",
        "Cometo errors a la feina perquè tinc la ment en altres coses",
        "A la feina, em sento incapaç de controlar les meves emocions",
        "No em reconec en la manera com reacciono a la feina",
        "Puc reaccionar exageradament sense voler",
    ],
}


def sembrar():
    """Roles, dimensiones y las 12 preguntas BAT-12. Idempotente."""
    for id_, nombre in ROLES.items():
        db.session.merge(Rol(id=id_, nombre=nombre))
    for id_, (nombre, desc) in DIMENSIONES.items():
        db.session.merge(Dimension(id=id_, nombre=nombre, descripcion=desc))
    db.session.flush()  # las preguntas referencian dimensiones
    for id_, dim, texto in PREGUNTAS:
        db.session.merge(Pregunta(id=id_, dimension_id=dim, texto=texto))
    db.session.flush()
    for idioma, textos in TRADUCCIONES.items():
        for (id_, _, _), texto in zip(PREGUNTAS, textos):
            db.session.merge(PreguntaTraduccion(pregunta_id=id_, idioma=idioma, texto=texto))
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

    @app.cli.command("enviar-recordatorios")
    def enviar_recordatorios_cmd():
        """Envía los recordatorios de test pendientes (programar a diario)."""
        from .services.recordatorios import enviar_recordatorios

        click.echo(f"{enviar_recordatorios()} recordatorios enviados.")

    @app.cli.command("crear-admin-env")
    def crear_admin_env():
        """Crea el primer admin desde ADMIN_EMAIL / ADMIN_PASSWORD si no existe (idempotente, sin prompt).

        Pensado para el arranque en Railway: tras el primer despliegue se puede borrar ADMIN_PASSWORD.
        """
        email, password = os.getenv("ADMIN_EMAIL", "").strip(), os.getenv("ADMIN_PASSWORD", "")
        if not email or not password:
            click.echo("ADMIN_EMAIL/ADMIN_PASSWORD sin definir: no se crea ningún admin.")
            return
        if len(password) < 8:
            raise click.ClickException("ADMIN_PASSWORD debe tener al menos 8 caracteres.")
        if Usuario.query.filter_by(email=email).first():
            click.echo("El admin ya existe.")
            return
        db.session.add(Usuario(rol_id=1, nombre="Admin", email=email, password=generate_password_hash(password),
                               consentimiento_fecha=datetime.now()))
        db.session.commit()
        click.echo(f"Admin {email} creado.")

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
