from ..models import Pregunta, PreguntaTraduccion


def i18n_preguntas():
    """{'es': {'q_1': ...}, 'en': {...}, 'ca': {...}} para el motor i18n del navegador."""
    d = {"es": {}, "en": {}, "ca": {}}
    for p in Pregunta.query.filter_by(es_activo=True):
        d["es"][f"q_{p.id}"] = p.texto
    for t in PreguntaTraduccion.query:
        d.setdefault(t.idioma, {})[f"q_{t.pregunta_id}"] = t.texto
    return d
