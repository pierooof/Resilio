"""Recordatorios por email para repetir el test. Se lanzan con `flask enviar-recordatorios`
(Railway cron, p. ej. una vez al día). Solo a quien lo activó en Configuración."""
import logging
from datetime import datetime, timedelta

from flask import current_app
from flask_mail import Message
from sqlalchemy import func

from ..extensions import db, mail
from ..models import Evaluacion, Usuario

log = logging.getLogger(__name__)

# Textos en es/en/ca (en/ca propios, sin revisión nativa)
TEXTOS = {
    "es": ("Es un buen momento para repetir tu test BAT-12",
           "Hola {nombre},\n\nHan pasado unas semanas desde tu último test. Repetirlo te ayuda a ver cómo evolucionas:\n{url}\n\n"
           "Puedes cambiar o desactivar estos recordatorios en Configuración.\n\nEl equipo de Resilio\n"),
    "en": ("It is a good time to repeat your BAT-12 test",
           "Hi {nombre},\n\nA few weeks have passed since your last test. Repeating it helps you see how you are doing:\n{url}\n\n"
           "You can change or turn off these reminders in Settings.\n\nThe Resilio team\n"),
    "ca": ("És un bon moment per repetir el teu test BAT-12",
           "Hola {nombre},\n\nHan passat unes setmanes des del teu últim test. Repetir-lo t'ajuda a veure com evoluciones:\n{url}\n\n"
           "Pots canviar o desactivar aquests recordatoris a Configuració.\n\nL'equip de Resilio\n"),
}


def enviar_recordatorios(ahora=None):
    """Envía los recordatorios pendientes y devuelve cuántos. Un fallo de correo no frena al resto."""
    ahora = ahora or datetime.now()
    base = current_app.config.get("APP_URL")
    if not base:
        raise RuntimeError("Define APP_URL (p. ej. https://tu-app.up.railway.app) para los enlaces del correo.")

    ultimos = dict(db.session.query(Evaluacion.usuario_id, func.max(Evaluacion.fecha)).group_by(Evaluacion.usuario_id))
    enviados = 0
    for u in Usuario.query.filter(Usuario.recordatorio_semanas.isnot(None)):
        limite = ahora - timedelta(weeks=u.recordatorio_semanas)
        ultima_actividad = ultimos.get(u.id) or u.fecha_registro or ahora
        if ultima_actividad > limite or (u.ultimo_recordatorio and u.ultimo_recordatorio > limite):
            continue
        asunto, cuerpo = TEXTOS.get(u.idioma, TEXTOS["es"])
        try:
            mail.send(Message(asunto, recipients=[u.email],
                              body=cuerpo.format(nombre=u.nombre, url=base.rstrip("/") + "/test")))
        except Exception:
            log.exception("No se pudo enviar el recordatorio al usuario %s", u.id)
            continue
        u.ultimo_recordatorio = ahora
        enviados += 1
    db.session.commit()
    return enviados
