"""Test de caracterización de calcular_y_guardar_bat12: fija el contrato BAT-12
antes del rework (medias por dimensión, global = suma/12, validación de 12 ítems).
Sin BD ni Gemini: db falso y ia_service stubbeado.
"""
import sys
import types

# google-genai no hace falta para probar el cálculo
sys.modules.setdefault(
    "servicios.ia_service",
    types.SimpleNamespace(generar_consejos_ia=lambda *a, **k: "<p>consejos</p>"),
)

from servicios.test_service import calcular_y_guardar_bat12  # noqa: E402

# 12 preguntas, 3 por dimensión: ids 1-3 → dim 1, 4-6 → dim 2, ...
MAPA = {i: (i - 1) // 3 + 1 for i in range(1, 13)}


class FakeCursor:
    def __init__(self):
        self.inserts, self.many, self.lastrowid = [], [], 42

    def execute(self, query, params=None):
        if query.lstrip().upper().startswith("INSERT"):
            self.inserts.append(params)

    def fetchall(self):
        return [{"id": p, "dimension_id": d} for p, d in MAPA.items()]

    def executemany(self, query, data):
        self.many.extend(data)

    def close(self):
        pass


class FakeDB:
    def __init__(self):
        self.cur, self.committed, self.rolled_back = FakeCursor(), False, False

    def cursor(self, dictionary=False):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def form(valores):
    return {f"pregunta_{i}": str(v) for i, v in enumerate(valores, start=1)}


def test_medias_por_dimension_y_global():
    db = FakeDB()
    # dim1: 1,2,3 → 2.0 | dim2: 4,4,4 → 4.0 | dim3: 5,5,2 → 4.0 | dim4: 1,1,2 → 1.33
    ok, media = calcular_y_guardar_bat12(1, form([1, 2, 3, 4, 4, 4, 5, 5, 2, 1, 1, 2]), db)
    assert ok and media == round(34 / 12, 2) == 2.83
    # (usuario, total, agot, distanc, cogn, emoc, consejos)
    assert db.cur.inserts[0][:6] == (1, 2.83, 2.0, 4.0, 4.0, 1.33)
    assert len(db.cur.many) == 12 and db.committed


def test_menos_de_12_respuestas_falla_sin_guardar():
    db = FakeDB()
    ok, msg = calcular_y_guardar_bat12(1, form([3] * 11), db)
    assert not ok and "todas" in msg
    assert not db.cur.inserts and not db.committed


def test_ignora_campos_ajenos_al_test():
    db = FakeDB()
    datos = form([3] * 12) | {"csrf_token": "x"}
    ok, media = calcular_y_guardar_bat12(1, datos, db)
    assert ok and media == 3.0
