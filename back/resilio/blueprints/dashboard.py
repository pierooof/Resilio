from flask import Blueprint, current_app, flash, redirect, render_template, session, url_for

from ..extensions import db
from ..models import Evaluacion
from ..security import login_required
from . import hr
from ..services.scoring import RIESGO
from ..utils import SOLO_EMPLEADOS, ULTIMA, fila, filas, tiempo_relativo, ultimos_meses

bp = Blueprint("dashboard", __name__)

def _tendencia(rows):
    rows = [{"mes": r["mes"], "total": int(r["total"]), "riesgo_alto": int(r["riesgo_alto"])} for r in rows]
    return rows or ultimos_meses(total=0, riesgo_alto=0)


@bp.route("/dashboard")
@login_required
def dashboard():
    rol = session["rol"]
    if rol == 1:
        return _admin()
    if rol == 2:
        return hr.panel()
    todas = Evaluacion.query.filter_by(usuario_id=session["user_id"]).order_by(Evaluacion.fecha, Evaluacion.id).all()
    template = "dashboards/personal.html" if rol == 3 else "dashboards/empleado.html"
    return render_template(template, evaluacion=todas[-1] if todas else None, tendencia=todas)


def _admin():
    try:
        total_usuarios = fila("SELECT COUNT(*) AS t FROM usuarios")["t"]
        riesgo_alto = fila(
            f"SELECT COUNT(*) AS t FROM ({ULTIMA.format(where='')}) x WHERE puntuacion_total >= :alto", **RIESGO
        )["t"]
        stats = dict(
            total_usuarios=total_usuarios,
            total_empresas=fila("SELECT COUNT(*) AS t FROM empresas")["t"],
            total_evaluaciones=fila("SELECT COUNT(*) AS t FROM evaluaciones")["t"],
            nuevos_usuarios_mes=fila(
                "SELECT COUNT(*) AS t FROM usuarios WHERE date_trunc('month', fecha_registro) = date_trunc('month', now())"
            )["t"],
            evaluaciones_mes=fila(
                "SELECT COUNT(*) AS t FROM evaluaciones WHERE date_trunc('month', fecha) = date_trunc('month', now())"
            )["t"],
            usuarios_riesgo_alto=riesgo_alto,
            pct_riesgo_alto=round(riesgo_alto / total_usuarios * 100, 1) if total_usuarios else 0,
        )
        usuarios = filas("""
            SELECT u.id, u.nombre, u.apellidos, u.email, u.rol_id, u.fecha_registro,
                   e.nombre AS empresa_nombre, COUNT(ev.id) AS total_evaluaciones
            FROM usuarios u
            LEFT JOIN empresas e ON u.empresa_id = e.id
            LEFT JOIN evaluaciones ev ON ev.usuario_id = u.id
            GROUP BY u.id, u.nombre, u.apellidos, u.email, u.rol_id, u.fecha_registro, e.nombre
            ORDER BY u.fecha_registro DESC LIMIT 10
        """)
        empresas = filas("""
            SELECT e.id, e.nombre, e.sector, e.codigo_registro, COUNT(u.id) AS total_empleados
            FROM empresas e LEFT JOIN usuarios u ON u.empresa_id = e.id
            GROUP BY e.id, e.nombre, e.sector, e.codigo_registro
            ORDER BY e.id DESC
        """)
        usuarios_riesgo = filas(
            f"""
            SELECT u.nombre, u.apellidos, emp.nombre AS empresa_nombre, t.puntuacion_total AS ultima_puntuacion
            FROM ({ULTIMA.format(where='')}) t
            JOIN usuarios u ON u.id = t.usuario_id
            LEFT JOIN empresas emp ON emp.id = u.empresa_id
            WHERE t.puntuacion_total >= :medio
            ORDER BY t.puntuacion_total DESC LIMIT 8
        """,
            **RIESGO,
        )
        actividad = []
        for item in filas("""
            (SELECT 'registro' AS tipo, u.nombre, u.apellidos, NULL AS puntuacion, u.fecha_registro AS fecha
             FROM usuarios u ORDER BY fecha_registro DESC LIMIT 5)
            UNION ALL
            (SELECT 'evaluacion', u.nombre, u.apellidos, ev.puntuacion_total, ev.fecha
             FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id ORDER BY ev.fecha DESC LIMIT 5)
            ORDER BY fecha DESC LIMIT 8
        """):
            if item["tipo"] == "registro":
                actividad.append(dict(
                    titulo="Nuevo usuario registrado",
                    descripcion=f"{item['nombre']} {item['apellidos'] or ''}".strip(),
                    tiempo=tiempo_relativo(item["fecha"]), icon="user-plus", color="green",
                ))
            else:
                p = float(item["puntuacion"] or 0)
                actividad.append(dict(
                    titulo="Evaluación completada",
                    descripcion=f"{item['nombre']} — {p:.2f}/5",
                    tiempo=tiempo_relativo(item["fecha"]), icon="clipboard-check",
                    color="red" if p >= RIESGO["alto"] else ("yellow" if p >= RIESGO["medio"] else "green"),
                ))
        tendencia_mensual = _tendencia(filas(
            """
            SELECT to_char(date_trunc('month', fecha), 'Mon YYYY') AS mes, COUNT(*) AS total,
                   SUM(CASE WHEN puntuacion_total >= :alto THEN 1 ELSE 0 END) AS riesgo_alto
            FROM evaluaciones
            WHERE fecha >= now() - interval '6 months'
            GROUP BY date_trunc('month', fecha) ORDER BY date_trunc('month', fecha)
        """,
            **RIESGO,
        ))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al cargar el panel de admin")
        flash("Error al cargar el panel.", "error")
        stats = {k: 0 for k in ["total_usuarios", "total_empresas", "total_evaluaciones", "nuevos_usuarios_mes",
                                "evaluaciones_mes", "usuarios_riesgo_alto", "pct_riesgo_alto"]}
        usuarios = empresas = usuarios_riesgo = actividad = tendencia_mensual = []

    return render_template(
        "dashboards/admin.html", stats=stats, usuarios=usuarios, empresas=empresas,
        usuarios_riesgo=usuarios_riesgo, actividad=actividad, tendencia_mensual=tendencia_mensual,
    )
