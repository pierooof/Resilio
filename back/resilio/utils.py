from datetime import date, datetime

from babel.dates import format_date, format_timedelta
from flask_babel import get_locale, gettext as _
from sqlalchemy import text

from .extensions import db


def filas(sql, **params):
    """Ejecuta SQL con parámetros con nombre y devuelve una lista de dicts."""
    return [dict(r) for r in db.session.execute(text(sql), params).mappings()]


def fila(sql, **params):
    r = filas(sql, **params)
    return r[0] if r else None


def mes_corto(fecha):
    """Fecha -> 'nov 2026' / 'Nov 2026' / 'de nov. 2026' según el idioma del servidor."""
    return format_date(fecha, "MMM yyyy", locale=str(get_locale()))


def tiempo_relativo(fecha):
    """'hace 5 minutos', 'hace 2 horas'... en el idioma del servidor."""
    if not fecha:
        return "—"
    diff = datetime.now() - fecha.replace(tzinfo=None)
    if diff.total_seconds() < 60:
        return _("ahora mismo")
    return format_timedelta(-diff, add_direction=True, locale=str(get_locale()))


def ultimos_meses(**vacio):
    """Últimos 6 meses con valores a cero, para gráficos sin datos."""
    hoy, meses = date.today(), []
    for i in range(5, -1, -1):
        m, y = hoy.month - i, hoy.year
        while m <= 0:
            m, y = m + 12, y - 1
        meses.append({"mes": mes_corto(date(y, m, 1)), **vacio})
    return meses


# Última evaluación de cada usuario (opcionalmente filtrada por un WHERE sobre usuarios u)
ULTIMA = """
    SELECT DISTINCT ON (ev.usuario_id) ev.usuario_id, ev.puntuacion_total
    FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id
    {where}
    ORDER BY ev.usuario_id, ev.fecha DESC
"""
SOLO_EMPLEADOS = "WHERE u.empresa_id = :empresa_id AND u.rol_id = 4"
