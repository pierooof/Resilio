"""Contrato BAT-12: medias por dimensión, global = suma/12, validación de 12 ítems."""
import pytest

from resilio.extensions import db
from resilio.models import Evaluacion, RespuestaEvaluacion, Usuario
from resilio.services.scoring import (
    calcular_bat12, calcular_y_guardar_bat12, nivel_riesgo, parsear_respuestas,
)

# 12 preguntas, 3 por dimensión: ids 1-3 → dim 1, 4-6 → dim 2, ...
MAPA = {i: (i - 1) // 3 + 1 for i in range(1, 13)}


def form(valores):
    return {f"pregunta_{i}": str(v) for i, v in enumerate(valores, start=1)}


def test_medias_por_dimension_y_global():
    # dim1: 1,2,3 → 2.0 | dim2: 4,4,4 → 4.0 | dim3: 5,5,2 → 4.0 | dim4: 1,1,2 → 1.33
    r = calcular_bat12(parsear_respuestas(form([1, 2, 3, 4, 4, 4, 5, 5, 2, 1, 1, 2])), MAPA)
    assert r["media_total"] == round(34 / 12, 2) == 2.83
    assert r["dims"] == {"agotamiento": 2.0, "distanciamiento": 4.0, "cognitivo": 4.0, "emocional": 1.33}
    assert r["dimension_maxima"] == "distanciamiento"  # empate: gana la primera


def test_menos_de_12_respuestas_falla():
    with pytest.raises(ValueError, match="todas"):
        calcular_bat12(parsear_respuestas(form([3] * 11)), MAPA)


@pytest.mark.parametrize("malo", ["0", "6", "abc", "", "2.5"])
def test_valor_fuera_de_escala_o_no_numerico(malo):
    with pytest.raises(ValueError):
        parsear_respuestas({"pregunta_1": malo})


def test_ignora_campos_ajenos_al_test():
    assert parsear_respuestas(form([3] * 12) | {"csrf_token": "x"}) == {i: 3 for i in range(1, 13)}


def test_umbrales_de_riesgo():
    assert [nivel_riesgo(x) for x in (1, 2.49, 2.5, 3.49, 3.5, 5)] == ["Bajo", "Bajo", "Medio", "Medio", "Alto", "Alto"]


def test_guardar_crea_evaluacion_y_12_respuestas(app, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    u = Usuario(rol_id=3, nombre="A", email="a@x.com", password="x")
    db.session.add(u)
    db.session.commit()

    ok, media = calcular_y_guardar_bat12(u.id, form([1, 2, 3, 4, 4, 4, 5, 5, 2, 1, 1, 2]))

    ev = Evaluacion.query.one()
    assert ok and media == 2.83
    assert (float(ev.puntuacion_total), float(ev.dim_agotamiento), float(ev.dim_emocional)) == (2.83, 2.0, 1.33)
    assert RespuestaEvaluacion.query.count() == 12 and "Gemini" in ev.consejos


def test_guardar_incompleto_no_escribe(app):
    ok, msg = calcular_y_guardar_bat12(1, form([3] * 11))
    assert not ok and "todas" in msg and Evaluacion.query.count() == 0
