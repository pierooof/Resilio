import csv
import io
from datetime import datetime

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import Departamento, Empresa, Rol, Usuario
from ..security import solo_admin
from ..services.scoring import RIESGO
from ..utils import ULTIMA, fila, filas, ultimos_meses
from .auth import MIN_PASSWORD

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _volver():
    return redirect(url_for("dashboard.dashboard"))


@bp.route("/nueva_empresa", methods=["POST"])
@solo_admin
def nueva_empresa():
    nombre = request.form.get("nombre", "").strip()
    sector = request.form.get("sector", "").strip()
    codigo = request.form.get("codigo_registro", "").strip()
    if not nombre or not codigo:
        flash("El nombre y el código de registro son obligatorios.", "error")
        return _volver()
    if Empresa.query.filter_by(codigo_registro=codigo).first():
        flash(f"El código '{codigo}' ya está en uso. Elige otro.", "error")
        return _volver()

    db.session.add(Empresa(nombre=nombre, sector=sector or None, codigo_registro=codigo))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"El código '{codigo}' ya está en uso. Elige otro.", "error")
    else:
        flash(f"✓ Empresa '{nombre}' creada con código {codigo}.", "success")
    return _volver()


@bp.route("/nuevo_usuario", methods=["POST"])
@solo_admin
def nuevo_usuario():
    f = request.form
    nombre, email, password = f.get("nombre", "").strip(), f.get("email", "").strip(), f.get("password", "")
    try:
        rol_id = int(f.get("rol_id") or 3)
        empresa_id = int(f["empresa_id"]) if f.get("empresa_id") else None
        departamento_id = int(f["departamento_id"]) if f.get("departamento_id") else None
    except ValueError:
        flash("Datos no válidos.", "error")
        return _volver()

    if not nombre or "@" not in email or len(password) < MIN_PASSWORD:
        flash(f"Nombre, email válido y contraseña de al menos {MIN_PASSWORD} caracteres son obligatorios.", "error")
        return _volver()
    if not db.session.get(Rol, rol_id):
        flash("Rol no válido.", "error")
        return _volver()
    if empresa_id and not db.session.get(Empresa, empresa_id):
        flash("Empresa no válida.", "error")
        return _volver()
    if rol_id in (2, 4) and not empresa_id:
        flash("HR y empleados necesitan una empresa.", "error")
        return _volver()
    if departamento_id:
        dep = db.session.get(Departamento, departamento_id)
        if not dep or dep.empresa_id != empresa_id:
            flash("El departamento no pertenece a esa empresa.", "error")
            return _volver()
    if Usuario.query.filter_by(email=email).first():
        flash(f"El email '{email}' ya está registrado.", "error")
        return _volver()

    db.session.add(
        Usuario(
            rol_id=rol_id, empresa_id=empresa_id, departamento_id=departamento_id, nombre=nombre,
            apellidos=f.get("apellidos", "").strip() or None, email=email,
            password=generate_password_hash(password),
        )
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"El email '{email}' ya está registrado.", "error")
    else:
        flash(f"✓ Usuario '{nombre}' creado correctamente.", "success")
    return _volver()


@bp.route("/exportar_csv")
@solo_admin
def exportar_csv():
    try:
        rows = filas(
            """
            SELECT ev.id AS evaluacion_id, ev.fecha, u.nombre, u.apellidos, u.email, r.nombre AS rol,
                   COALESCE(e.nombre, 'Personal') AS empresa, COALESCE(d.nombre, '—') AS departamento,
                   ev.puntuacion_total, ev.dim_agotamiento, ev.dim_distanciamiento,
                   ev.dim_cognitivo, ev.dim_emocional,
                   CASE WHEN ev.puntuacion_total >= :alto THEN 'Alto'
                        WHEN ev.puntuacion_total >= :medio THEN 'Medio'
                        ELSE 'Bajo' END AS nivel_riesgo
            FROM evaluaciones ev
            JOIN usuarios u ON u.id = ev.usuario_id
            JOIN roles r ON r.id = u.rol_id
            LEFT JOIN empresas e ON e.id = u.empresa_id
            LEFT JOIN departamentos d ON d.id = u.departamento_id
            ORDER BY ev.fecha DESC
        """,
            **RIESGO,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al generar el CSV")
        flash("Error al generar el CSV.", "error")
        return _volver()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID Evaluación", "Fecha", "Nombre", "Apellidos", "Email", "Rol", "Empresa", "Departamento",
        "Puntuación Total", "Agotamiento", "Distanciamiento", "Deterioro Cognitivo", "Deterioro Emocional",
        "Nivel de Riesgo",
    ])
    for r in rows:
        writer.writerow([
            r["evaluacion_id"], r["fecha"].strftime("%d/%m/%Y %H:%M") if r["fecha"] else "",
            r["nombre"], r["apellidos"] or "", r["email"], r["rol"], r["empresa"], r["departamento"],
            r["puntuacion_total"], r["dim_agotamiento"], r["dim_distanciamiento"], r["dim_cognitivo"],
            r["dim_emocional"], r["nivel_riesgo"],
        ])
    nombre = f"resilio_evaluaciones_{datetime.now():%Y%m%d_%H%M}.csv"
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nombre}"})


def _num(v):
    return float(v) if v else None


@bp.route("/informe_global")
@solo_admin
def informe_global():
    try:
        stats = dict(
            total_usuarios=fila("SELECT COUNT(*) AS t FROM usuarios")["t"],
            total_evaluaciones=fila("SELECT COUNT(*) AS t FROM evaluaciones")["t"],
        )
        riesgo = fila(
            f"""
            SELECT COALESCE(SUM(CASE WHEN puntuacion_total < :medio THEN 1 ELSE 0 END), 0) AS bajo,
                   COALESCE(SUM(CASE WHEN puntuacion_total >= :medio AND puntuacion_total < :alto THEN 1 ELSE 0 END), 0) AS medio,
                   COALESCE(SUM(CASE WHEN puntuacion_total >= :alto THEN 1 ELSE 0 END), 0) AS alto
            FROM ({ULTIMA.format(where='')}) x
        """,
            **RIESGO,
        )
        riesgo = {k: int(v) for k, v in riesgo.items()}
        m = fila("""
            SELECT ROUND(AVG(dim_agotamiento), 2) AS agotamiento, ROUND(AVG(dim_distanciamiento), 2) AS distanciamiento,
                   ROUND(AVG(dim_cognitivo), 2) AS cognitivo, ROUND(AVG(dim_emocional), 2) AS emocional,
                   ROUND(AVG(puntuacion_total), 2) AS global
            FROM evaluaciones
        """)
        medias = {k: float(v) if v else 0 for k, v in m.items()} if m["global"] else None
        empresas_stats = [
            {**r, "media_global": _num(r["media_global"]), "media_agotamiento": _num(r["media_agotamiento"])}
            for r in filas("""
                SELECT e.nombre, COUNT(DISTINCT u.id) AS empleados, COUNT(ev.id) AS evaluaciones,
                       ROUND(AVG(ev.puntuacion_total), 2) AS media_global,
                       ROUND(AVG(ev.dim_agotamiento), 2) AS media_agotamiento
                FROM empresas e
                LEFT JOIN usuarios u ON u.empresa_id = e.id
                LEFT JOIN evaluaciones ev ON ev.usuario_id = u.id
                GROUP BY e.id, e.nombre
                ORDER BY media_global DESC NULLS LAST
            """)
        ]
        top_riesgo = filas(
            f"""
            SELECT u.nombre, u.apellidos, emp.nombre AS empresa_nombre, t.puntuacion_total
            FROM ({ULTIMA.format(where='')}) t
            JOIN usuarios u ON u.id = t.usuario_id
            LEFT JOIN empresas emp ON emp.id = u.empresa_id
            ORDER BY t.puntuacion_total DESC LIMIT 10
        """
        )
        evolucion_mensual = [
            {"mes": r["mes"], "media": float(r["media"])}
            for r in filas("""
                SELECT to_char(date_trunc('month', fecha), 'Mon YYYY') AS mes, ROUND(AVG(puntuacion_total), 2) AS media
                FROM evaluaciones WHERE fecha >= now() - interval '6 months'
                GROUP BY date_trunc('month', fecha) ORDER BY date_trunc('month', fecha)
            """)
        ] or ultimos_meses(media=0)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al generar el informe global")
        flash("Error al generar el informe.", "error")
        stats = medias = None
        riesgo = dict(bajo=0, medio=0, alto=0)
        empresas_stats = top_riesgo = evolucion_mensual = []

    return render_template(
        "dashboards/informe_global.html", stats=stats, riesgo=riesgo, medias=medias,
        empresas_stats=empresas_stats, top_riesgo=top_riesgo, evolucion_mensual=evolucion_mensual,
    )
