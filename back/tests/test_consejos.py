import json

import pytest

from resilio.services import consejos
from resilio.services.consejos import FALLBACK, generar_consejos

DIMS = {"agotamiento": 3.0, "distanciamiento": 2.0, "cognitivo": 2.0, "emocional": 2.0}
VALIDO = {"intro": "Hola", "consejos": [{"titulo": f"T{i}", "texto": f"x{i}"} for i in range(3)]}


def test_sin_clave_usa_fallback_en_el_idioma():
    for lang in ("es", "en", "ca"):
        r = generar_consejos(2.0, DIMS, "agotamiento", lang)
        assert r["ia"] is False and r["lang"] == lang and len(r["consejos"]) == 3
        assert r["intro"] == FALLBACK[lang]["intro"]["Bajo"]


def test_nivel_alto_recomienda_profesional():
    assert "profesional" in generar_consejos(3.4, DIMS, "agotamiento", "es")["intro"]


def test_respuesta_valida_de_gemini(monkeypatch):
    monkeypatch.setattr(consejos, "_llamar_gemini", lambda prompt, key: json.dumps(VALIDO))
    r = generar_consejos(3.0, DIMS, "agotamiento", "en", api_key="k")
    assert r["ia"] is True and r["lang"] == "en" and r["consejos"][1] == {"titulo": "T1", "texto": "x1"}


def test_prompt_pide_el_idioma_y_el_tono(monkeypatch):
    vistos = []
    monkeypatch.setattr(consejos, "_llamar_gemini", lambda prompt, key: vistos.append(prompt) or json.dumps(VALIDO))
    generar_consejos(3.4, DIMS, "agotamiento", "ca", api_key="k")
    assert "Write in Catalan" in vistos[0] and "health professional" in vistos[0]


@pytest.mark.parametrize("salida", [
    "no es json",
    json.dumps({"intro": "x", "consejos": VALIDO["consejos"][:2]}),                      # faltan consejos
    json.dumps({"intro": "x", "consejos": [{"titulo": "a"}] * 3}),                        # falta texto
    json.dumps({"intro": "", "consejos": VALIDO["consejos"]}),                            # intro vacía
    json.dumps({"intro": "x", "consejos": [{"titulo": 1, "texto": 2}] * 3}),              # tipos
])
def test_respuesta_invalida_cae_al_fallback(monkeypatch, salida):
    monkeypatch.setattr(consejos, "_llamar_gemini", lambda prompt, key: salida)
    assert generar_consejos(2.0, DIMS, "agotamiento", "es", api_key="k")["ia"] is False


def test_error_de_gemini_no_propaga(monkeypatch):
    def boom(prompt, key):
        raise RuntimeError("red caída")

    monkeypatch.setattr(consejos, "_llamar_gemini", boom)
    assert generar_consejos(2.0, DIMS, "agotamiento", "es", api_key="k")["ia"] is False


def test_textos_se_recortan(monkeypatch):
    largo = {"intro": "i" * 900, "consejos": [{"titulo": "t" * 200, "texto": "x" * 900}] * 3}
    monkeypatch.setattr(consejos, "_llamar_gemini", lambda prompt, key: json.dumps(largo))
    r = generar_consejos(2.0, DIMS, "agotamiento", "es", api_key="k")
    assert len(r["intro"]) == 500 and len(r["consejos"][0]["titulo"]) == 60 and len(r["consejos"][0]["texto"]) == 220
