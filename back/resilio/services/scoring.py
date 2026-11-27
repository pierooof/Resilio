"""Test BAT-12: cálculo (función pura) y guardado.

12 preguntas, 4 dimensiones × 3, escala 1-5, media simple.
"""
import os

from ..extensions import db
from ..models import Evaluacion, Pregunta, RespuestaEvaluacion
from .ia_service import generar_consejos_ia

N_PREGUNTAS = 12
DIMENSIONES = {1: "agotamiento", 2: "distanciamiento", 3: "cognitivo", 4: "emocional"}

# Umbrales de riesgo: bajo < MEDIO <= medio < ALTO <= alto. Único sitio donde viven.
UMBRAL_MEDIO = 2.5
UMBRAL_ALTO = 3.5
RIESGO = {"medio": UMBRAL_MEDIO, "alto": UMBRAL_ALTO}  # parámetros para las consultas SQL


def nivel_riesgo(puntuacion):
    if puntuacion >= UMBRAL_ALTO:
        return "Alto"
    return "Medio" if puntuacion >= UMBRAL_MEDIO else "Bajo"


def parsear_respuestas(form_data):
    """{'pregunta_5': '3', ...} -> {5: 3}. ValueError si algún valor no es 1-5."""
    respuestas = {}
    for key, value in form_data.items():
        if not key.startswith("pregunta_"):
            continue
        try:
            pid, valor = int(key.split("_", 1)[1]), int(value)
        except ValueError:
            raise ValueError("Respuesta no válida.") from None
        if not 1 <= valor <= 5:
            raise ValueError("Respuesta no válida.")
        respuestas[pid] = valor
    return respuestas


def calcular_bat12(respuestas, mapa_preguntas):
    """respuestas {pregunta_id: valor}, mapa_preguntas {pregunta_id: dimension_id}.

    Devuelve dict con media_total, dims (por nombre) y dimension_maxima.
    ValueError si no hay exactamente 12 respuestas a preguntas conocidas.
    """
    validas = {p: v for p, v in respuestas.items() if mapa_preguntas.get(p) in DIMENSIONES}
    if len(validas) != N_PREGUNTAS:
        raise ValueError("Debes responder a todas las preguntas.")

    valores = {d: [] for d in DIMENSIONES}
    for pid, valor in validas.items():
        valores[mapa_preguntas[pid]].append(valor)
    if not all(valores.values()):
        raise ValueError("Debes responder a todas las preguntas.")

    dims = {DIMENSIONES[d]: round(sum(v) / len(v), 2) for d, v in valores.items()}
    return {
        "media_total": round(sum(validas.values()) / N_PREGUNTAS, 2),
        "dims": dims,
        "dimension_maxima": max(dims, key=dims.get),
        "respuestas": validas,
    }


def calcular_y_guardar_bat12(user_id, form_data):
    """Procesa el formulario, genera consejos y guarda la evaluación.

    Devuelve (True, media_total) o (False, mensaje_de_error).
    """
    try:
        mapa = {p.id: p.dimension_id for p in Pregunta.query.all()}
        r = calcular_bat12(parsear_respuestas(form_data), mapa)
    except ValueError as e:
        return False, str(e)

    consejos = "No se han generado consejos. Configura la API de Gemini para obtener recomendaciones personalizadas."
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        consejos = generar_consejos_ia(r["media_total"], r["dimension_maxima"], api_key)

    d = r["dims"]
    db.session.add(
        Evaluacion(
            usuario_id=user_id,
            puntuacion_total=r["media_total"],
            dim_agotamiento=d["agotamiento"],
            dim_distanciamiento=d["distanciamiento"],
            dim_cognitivo=d["cognitivo"],
            dim_emocional=d["emocional"],
            consejos=consejos,
            respuestas=[RespuestaEvaluacion(pregunta_id=p, valor=v) for p, v in r["respuestas"].items()],
        )
    )
    db.session.commit()
    return True, r["media_total"]
