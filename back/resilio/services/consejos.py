"""Consejos de bienestar tras el test: Gemini devuelve JSON estructurado (nunca HTML) y la
plantilla lo pinta con autoescape. Si no hay clave, Gemini falla o responde algo inválido, se usan
consejos fijos en el idioma del usuario. generar_consejos nunca lanza.
"""
import json
import logging
import os

log = logging.getLogger(__name__)

IDIOMAS = ("es", "en", "ca")
NOMBRE_IDIOMA = {"es": "Spanish", "en": "English", "ca": "Catalan"}
MODELO = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# Consejos fijos. Traducciones en/ca propias, no revisadas por hablantes nativos.
FALLBACK = {
    "es": {
        "intro": {
            "Bajo": "Tu resultado indica un buen nivel de bienestar en el trabajo. Mantén los hábitos que te están funcionando.",
            "Medio": "Tu resultado sugiere cierto nivel de desgaste. Es una buena señal que te hayas parado a observarlo: pequeños cambios ayudan.",
            "Alto": "Tu resultado indica un desgaste importante. No es un diagnóstico, pero te recomendamos hablarlo con un profesional de la salud o con alguien de confianza.",
        },
        "consejos": [
            ("Descansa de verdad", "Protege tu sueño y desconecta del trabajo al acabar la jornada."),
            ("Haz pausas breves", "Pequeños descansos durante el día reducen la carga mental."),
            ("Habla con alguien", "Comparte cómo te sientes con una persona de confianza."),
        ],
    },
    "en": {
        "intro": {
            "Bajo": "Your result points to a good level of wellbeing at work. Keep up the habits that are working for you.",
            "Medio": "Your result suggests some level of strain. Taking a moment to notice it is a good sign: small changes help.",
            "Alto": "Your result points to significant strain. This is not a diagnosis, but we recommend talking to a health professional or someone you trust.",
        },
        "consejos": [
            ("Truly rest", "Protect your sleep and switch off from work when the day ends."),
            ("Take short breaks", "Brief pauses during the day reduce mental load."),
            ("Talk to someone", "Share how you feel with someone you trust."),
        ],
    },
    "ca": {
        "intro": {
            "Bajo": "El teu resultat indica un bon nivell de benestar a la feina. Mantén els hàbits que et funcionen.",
            "Medio": "El teu resultat suggereix cert nivell de desgast. És un bon senyal que t'hagis aturat a observar-ho: els petits canvis ajuden.",
            "Alto": "El teu resultat indica un desgast important. No és un diagnòstic, però et recomanem parlar-ne amb un professional de la salut o amb algú de confiança.",
        },
        "consejos": [
            ("Descansa de debò", "Protegeix el teu son i desconnecta de la feina en acabar la jornada."),
            ("Fes pauses breus", "Petits descansos durant el dia redueixen la càrrega mental."),
            ("Parla amb algú", "Comparteix com et sents amb una persona de confiança."),
        ],
    },
}

MAX_TITULO, MAX_TEXTO, MAX_INTRO = 60, 220, 500


def normalizar_idioma(valor):
    return valor if valor in IDIOMAS else "es"


def _fallback(nivel, idioma):
    f = FALLBACK[idioma]
    return {
        "intro": f["intro"][nivel],
        "consejos": [{"titulo": t, "texto": x} for t, x in f["consejos"]],
        "ia": False,
        "lang": idioma,
    }


def _prompt(media_total, dims, dimension_maxima, nivel, idioma):
    tono = {
        "Bajo": "The user is doing well: congratulate them and focus the tips on MAINTAINING their wellbeing.",
        "Medio": "The user shows some strain: be empathetic and supportive, focus the tips on reducing load and disconnecting.",
        "Alto": "The user shows high strain: be very empathetic and supportive, focus on reducing load and recommend, "
                "gently, talking to a health professional or someone they trust.",
    }[nivel]
    return (
        f"A user scored {media_total}/5 on the BAT-12 workplace burnout questionnaire "
        f"(1 = never, 5 = always; higher means more burnout symptoms). "
        f"Subscale means: {json.dumps(dims)}. Their highest subscale is: {dimension_maxima}.\n"
        f"{tono}\n"
        f"Write in {NOMBRE_IDIOMA[idioma]}. Return a short empathetic message (2-3 sentences, 'intro') and EXACTLY 3 "
        f"actionable tips, each with a short title (max 5 words) and a text (max 20 words)."
    )


SISTEMA = (
    "You are a workplace-wellbeing assistant for the Resilio platform. Be empathetic but professional. "
    "Give actionable, concrete tips. Never diagnose; only suggest habits. Reply only with the requested JSON."
)


def _llamar_gemini(prompt, api_key):
    """Devuelve el texto JSON de Gemini. Import perezoso: el SDK solo hace falta si hay clave."""
    import google.genai as genai
    from google.genai import types
    from pydantic import BaseModel

    class Consejo(BaseModel):
        titulo: str
        texto: str

    class Respuesta(BaseModel):
        intro: str
        consejos: list[Consejo]

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=MODELO,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SISTEMA,
            response_mime_type="application/json",
            response_schema=Respuesta,
        ),
    )
    return resp.text


def _validar(texto, idioma):
    """JSON de la IA -> dict limpio, o None si no cumple el formato (3 consejos de texto)."""
    data = json.loads(texto)
    intro = data["intro"]
    items = data["consejos"]
    if not isinstance(intro, str) or not isinstance(items, list) or len(items) != 3:
        return None
    consejos = []
    for c in items:
        if not isinstance(c["titulo"], str) or not isinstance(c["texto"], str):
            return None
        consejos.append({"titulo": c["titulo"].strip()[:MAX_TITULO], "texto": c["texto"].strip()[:MAX_TEXTO]})
    if not intro.strip() or not all(c["titulo"] and c["texto"] for c in consejos):
        return None
    return {"intro": intro.strip()[:MAX_INTRO], "consejos": consejos, "ia": True, "lang": idioma}


def generar_consejos(media_total, dims, dimension_maxima, idioma, api_key=None):
    from .scoring import nivel_riesgo  # import tardío: scoring importa este módulo

    idioma = normalizar_idioma(idioma)
    nivel = nivel_riesgo(media_total)
    if not api_key:
        return _fallback(nivel, idioma)
    try:
        texto = _llamar_gemini(_prompt(media_total, dims, dimension_maxima, nivel, idioma), api_key)
        return _validar(texto, idioma) or _fallback(nivel, idioma)
    except Exception:
        log.exception("Gemini no devolvió consejos válidos; se usan los fijos")
        return _fallback(nivel, idioma)
