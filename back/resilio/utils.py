import calendar
from datetime import date, datetime

from sqlalchemy import text

from .extensions import db


def filas(sql, **params):
    """Ejecuta SQL con parámetros con nombre y devuelve una lista de dicts."""
    return [dict(r) for r in db.session.execute(text(sql), params).mappings()]


def fila(sql, **params):
    r = filas(sql, **params)
    return r[0] if r else None


def tiempo_relativo(fecha):
    """'hace 5 min', 'hace 2h', etc."""
    if not fecha:
        return "—"
    sec = int((datetime.now() - fecha.replace(tzinfo=None)).total_seconds())
    if sec < 60:
        return "ahora mismo"
    if sec < 3600:
        return f"hace {sec // 60} min"
    if sec < 86400:
        return f"hace {sec // 3600}h"
    return f"hace {sec // 86400}d"


def ultimos_meses(**vacio):
    """Últimos 6 meses con valores a cero, para gráficos sin datos."""
    hoy, meses = date.today(), []
    for i in range(5, -1, -1):
        m, y = hoy.month - i, hoy.year
        while m <= 0:
            m, y = m + 12, y - 1
        meses.append({"mes": f"{calendar.month_abbr[m]} {y}", **vacio})
    return meses
