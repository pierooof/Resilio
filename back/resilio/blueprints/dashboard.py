from flask import Blueprint, current_app, flash, redirect, render_template, session, url_for

from ..extensions import db
from ..models import Evaluacion
from ..security import login_required
from ..services.scoring import RIESGO
from ..utils import fila, filas, tiempo_relativo, ultimos_meses

bp = Blueprint("dashboard", __name__)

# Última evaluación de cada usuario (opcionalmente filtrada por un WHERE sobre usuarios u)
ULTIMA = """
    SELECT DISTINCT ON (ev.usuario_id) ev.usuario_id, ev.puntuacion_total
    FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id
    {where}
    ORDER BY ev.usuario_id, ev.fecha DESC
"""
SOLO_EMPLEADOS = "WHERE u.empresa_id = :empresa_id AND u.rol_id = 4"


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
        return _hr()
    ultima = Evaluacion.query.filter_by(usuario_id=session["user_id"]).order_by(Evaluacion.fecha.desc()).first()
    template = "dashboards/personal.html" if rol == 3 else "dashboards/empleado.html"
    return render_template(template, evaluacion=ultima)


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


def _hr():
    empresa_id = session.get("empresa_id")
    if not empresa_id:
        flash("Tu usuario HR no tiene una empresa asignada.", "error")
        session.clear()
        return redirect(url_for("auth.login"))

    p = dict(empresa_id=empresa_id, **RIESGO)
    ultima = ULTIMA.format(where=SOLO_EMPLEADOS)
    try:
        total_empleados = fila("SELECT COUNT(*) AS t FROM usuarios WHERE empresa_id = :empresa_id AND rol_id = 4", **p)["t"]
        alto = fila(f"SELECT COUNT(*) AS t FROM ({ultima}) x WHERE puntuacion_total >= :alto", **p)["t"]
        stats = dict(
            total_empleados=total_empleados,
            total_evaluaciones=fila(
                f"SELECT COUNT(*) AS t FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id {SOLO_EMPLEADOS}", **p
            )["t"],
            empleados_riesgo_alto=alto,
            pct_riesgo_alto=round(alto / total_empleados * 100, 1) if total_empleados else 0,
        )
        medias = fila(
            f"""
            SELECT ROUND(AVG(ev.puntuacion_total), 2) AS media_global,
                   ROUND(AVG(ev.dim_agotamiento), 2) AS agotamiento,
                   ROUND(AVG(ev.dim_distanciamiento), 2) AS distanciamiento,
                   ROUND(AVG(ev.dim_cognitivo), 2) AS cognitivo,
                   ROUND(AVG(ev.dim_emocional), 2) AS emocional
            FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id {SOLO_EMPLEADOS}
        """,
            **p,
        )
        riesgo = fila(
            f"""
            SELECT COALESCE(SUM(CASE WHEN puntuacion_total < :medio THEN 1 ELSE 0 END), 0) AS bajo,
                   COALESCE(SUM(CASE WHEN puntuacion_total >= :medio AND puntuacion_total < :alto THEN 1 ELSE 0 END), 0) AS medio,
                   COALESCE(SUM(CASE WHEN puntuacion_total >= :alto THEN 1 ELSE 0 END), 0) AS alto
            FROM ({ultima}) t
        """,
            **p,
        )
        departamentos = filas(
            """
            SELECT COALESCE(d.nombre, 'Sin departamento') AS departamento,
                   COUNT(DISTINCT u.id) AS empleados, COUNT(ev.id) AS evaluaciones,
                   ROUND(AVG(ev.puntuacion_total), 2) AS media_global
            FROM usuarios u
            LEFT JOIN departamentos d ON d.id = u.departamento_id
            LEFT JOIN evaluaciones ev ON ev.usuario_id = u.id
            WHERE u.empresa_id = :empresa_id AND u.rol_id = 4
            GROUP BY d.id, d.nombre
            ORDER BY media_global DESC NULLS LAST
        """,
            **p,
        )
        tendencia_mensual = _tendencia(filas(
            """
            SELECT to_char(date_trunc('month', ev.fecha), 'Mon YYYY') AS mes, COUNT(*) AS total,
                   SUM(CASE WHEN ev.puntuacion_total >= :alto THEN 1 ELSE 0 END) AS riesgo_alto
            FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id
            WHERE u.empresa_id = :empresa_id AND u.rol_id = 4 AND ev.fecha >= now() - interval '6 months'
            GROUP BY date_trunc('month', ev.fecha) ORDER BY date_trunc('month', ev.fecha)
        """,
            **p,
        ))
        # Alias anónimos: HR nunca ve nombres de empleados
        evaluaciones_recientes = filas(
            """
            WITH ult AS (
                SELECT DISTINCT ON (ev.usuario_id) ev.usuario_id, ev.fecha, ev.puntuacion_total
                FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id
                WHERE u.empresa_id = :empresa_id AND u.rol_id = 4
                ORDER BY ev.usuario_id, ev.fecha DESC
            )
            SELECT to_char(fecha, 'DD/MM/YYYY') AS fecha,
                   'Empleado ' || LPAD(CAST(ROW_NUMBER() OVER (ORDER BY fecha DESC, usuario_id) AS text), 2, '0') AS alias,
                   ROUND(puntuacion_total, 2) AS puntuacion_total
            FROM ult ORDER BY fecha DESC LIMIT 10
        """,
            **p,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al cargar el panel HR")
        flash("Error al cargar el panel HR.", "error")
        stats = dict(total_empleados=0, total_evaluaciones=0, empleados_riesgo_alto=0, pct_riesgo_alto=0)
        medias = dict(media_global=0, agotamiento=0, distanciamiento=0, cognitivo=0, emocional=0)
        riesgo = dict(bajo=0, medio=0, alto=0)
        departamentos = tendencia_mensual = evaluaciones_recientes = []

    return render_template(
        "dashboards/hr.html", stats=stats, medias=medias, riesgo=riesgo, departamentos=departamentos,
        tendencia_mensual=tendencia_mensual, evaluaciones_recientes=evaluaciones_recientes,
    )
