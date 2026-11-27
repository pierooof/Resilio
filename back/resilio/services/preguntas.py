from flask_babel import get_locale

from ..models import Pregunta, PreguntaTraduccion


def textos_preguntas():
    """{pregunta_id: texto} en el idioma del servidor (es = Pregunta.texto; en/ca con respaldo en es)."""
    textos = {p.id: p.texto for p in Pregunta.query.filter_by(es_activo=True)}
    idioma = str(get_locale())
    if idioma != "es":
        for t in PreguntaTraduccion.query.filter_by(idioma=idioma):
            if t.pregunta_id in textos:
                textos[t.pregunta_id] = t.texto
    return textos
