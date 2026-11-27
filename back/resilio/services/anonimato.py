"""Anonimato de los datos agregados para RR. HH. (k-anonimato).

Ningún agregado se muestra si lo forman menos de K empleados distintos con evaluaciones.
"""
K_ANONIMATO = 5

OTROS = "Otros grupos"


def agrupar_k(grupos, k=K_ANONIMATO):
    """grupos: dicts {departamento, empleados, evaluados, evaluaciones, suma}.

    Los grupos con menos de k empleados evaluados se funden en uno ("Otros grupos"); si el fundido
    sigue sin llegar a k, se muestra sin puntuación. Devuelve dicts {departamento, empleados,
    evaluaciones, media_global}.
    # ponytail: si queda un solo grupo oculto, restar los totales de la empresa lo desvelaría;
    # añadir supresión complementaria si algún cliente lo exige.
    """
    visibles, pequenos = [], []
    for g in grupos:
        (visibles if g["evaluados"] >= k else pequenos).append(g)

    filas = [
        {"departamento": g["departamento"], "empleados": g["empleados"], "evaluaciones": g["evaluaciones"],
         "media_global": round(float(g["suma"]) / g["evaluaciones"], 2)}
        for g in visibles
    ]
    if pequenos:
        evaluados = sum(g["evaluados"] for g in pequenos)
        evaluaciones = sum(g["evaluaciones"] for g in pequenos)
        mostrable = evaluados >= k
        filas.append({
            "departamento": OTROS,
            "empleados": sum(g["empleados"] for g in pequenos),
            "evaluaciones": evaluaciones if mostrable else None,
            "media_global": round(float(sum(g["suma"] or 0 for g in pequenos)) / evaluaciones, 2) if mostrable else None,
        })
    return sorted(filas, key=lambda f: (f["media_global"] is None, -(f["media_global"] or 0)))
