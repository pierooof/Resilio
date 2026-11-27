"""Panel de RR. HH.: datos agregados y anónimos de la empresa (k-anonimato) y gestión de códigos."""
import csv
import io
from datetime import date, datetime, timedelta

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Departamento, Empresa, Usuario
from ..security import solo_hr
from ..services.anonimato import K_ANONIMATO, agrupar_k
from ..services.codigos import generar_codigo
from ..services.scoring import RIESGO
from ..utils import SOLO_EMPLEADOS, ULTIMA, fila, filas

bp = Blueprint("hr", __name__, url_prefix="/hr")

PERIODOS = (3, 6, 12, 0)  # meses; 0 = todo el histórico
DIMENSIONES = (("agotamiento", "Agotamiento"), ("distanciamiento", "Distanciamiento mental"),
               ("cognitivo", "Deterioro cognitivo"), ("emocional", "Deterioro emocional"))


def _periodo():
    try:
        meses = int(request.args.get("periodo", 6))
    except ValueError:
        meses = 6
    return meses if meses in PERIODOS else 6


def _datos(empresa_id, meses):
    """Agregados de la empresa en el periodo. Si hay menos de K empleados evaluados, solo se devuelve eso."""
    p = dict(empresa_id=empresa_id, meses=meses, meses_grafico=meses or 24, **RIESGO)
    periodo = "AND ev.fecha >= now() - make_interval(months => :meses)" if meses else ""
    base = f"FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id {SOLO_EMPLEADOS} {periodo}"

    total_empleados = fila("SELECT COUNT(*) AS t FROM usuarios WHERE empresa_id = :empresa_id AND rol_id = 4", **p)["t"]
    n = fila(f"SELECT COUNT(DISTINCT ev.usuario_id) AS n, COUNT(*) AS evals {base}", **p)
    datos = {"total_empleados": total_empleados, "n_evaluados": n["n"], "suficiente": n["n"] >= K_ANONIMATO}
    if not datos["suficiente"]:
        return datos

    ultima = ULTIMA.format(where=f"{SOLO_EMPLEADOS} {periodo}")
    riesgo = fila(
        f"""
        SELECT COALESCE(SUM(CASE WHEN puntuacion_total < :medio THEN 1 ELSE 0 END), 0) AS bajo,
               COALESCE(SUM(CASE WHEN puntuacion_total >= :medio AND puntuacion_total < :alto THEN 1 ELSE 0 END), 0) AS medio,
               COALESCE(SUM(CASE WHEN puntuacion_total >= :alto THEN 1 ELSE 0 END), 0) AS alto
        FROM ({ultima}) t
    """,
        **p,
    )
    medias = fila(
        f"""
        SELECT ROUND(AVG(ev.puntuacion_total), 2) AS media_global, ROUND(AVG(ev.dim_agotamiento), 2) AS agotamiento,
               ROUND(AVG(ev.dim_distanciamiento), 2) AS distanciamiento, ROUND(AVG(ev.dim_cognitivo), 2) AS cognitivo,
               ROUND(AVG(ev.dim_emocional), 2) AS emocional
        {base}
    """,
        **p,
    )
    grupos = filas(
        f"""
        SELECT COALESCE(d.nombre, 'Sin departamento') AS departamento, COUNT(DISTINCT u.id) AS empleados,
               COUNT(DISTINCT ev.usuario_id) AS evaluados, COUNT(ev.id) AS evaluaciones,
               COALESCE(SUM(ev.puntuacion_total), 0) AS suma
        FROM usuarios u
        LEFT JOIN departamentos d ON d.id = u.departamento_id
        LEFT JOIN evaluaciones ev ON ev.usuario_id = u.id {periodo}
        WHERE u.empresa_id = :empresa_id AND u.rol_id = 4
        GROUP BY d.id, d.nombre
    """,
        **p,
    )
    meses_pts = filas(
        """
        SELECT to_char(date_trunc('month', ev.fecha), 'Mon YYYY') AS mes, COUNT(*) AS total,
               COUNT(DISTINCT ev.usuario_id) AS personas,
               SUM(CASE WHEN ev.puntuacion_total >= :alto THEN 1 ELSE 0 END) AS riesgo_alto
        FROM evaluaciones ev JOIN usuarios u ON u.id = ev.usuario_id
        WHERE u.empresa_id = :empresa_id AND u.rol_id = 4 AND ev.fecha >= now() - make_interval(months => :meses_grafico)
        GROUP BY date_trunc('month', ev.fecha) ORDER BY date_trunc('month', ev.fecha)
    """,
        **p,
    )
    riesgo = {k: int(v) for k, v in riesgo.items()}
    dim_max = max(DIMENSIONES, key=lambda d: float(medias[d[0]]))
    datos.update(
        riesgo=riesgo,
        empleados_riesgo_alto=riesgo["alto"],
        pct_riesgo_alto=round(riesgo["alto"] / n["n"] * 100, 1),
        medias=medias,
        dim_max={"nombre": dim_max[1], "valor": medias[dim_max[0]]},
        total_evaluaciones=n["evals"],
        departamentos=agrupar_k(grupos),
        # los meses con menos de K personas se omiten: un punto de 1-2 personas las identificaría
        tendencia_mensual=[{"mes": m["mes"], "total": int(m["total"]), "riesgo_alto": int(m["riesgo_alto"])}
                           for m in meses_pts if m["personas"] >= K_ANONIMATO],
    )
    return datos


def panel():
    """Pantalla de /dashboard para el rol HR (la ruta y el control de rol viven en dashboard)."""
    u = db.session.get(Usuario, session["user_id"])
    if not u.empresa_id:
        flash("Tu usuario HR no tiene una empresa asignada.", "error")
        session.clear()
        return redirect(url_for("auth.login"))
    empresa = db.session.get(Empresa, u.empresa_id)
    meses = _periodo()
    try:
        datos = _datos(empresa.id, meses)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al cargar el panel HR")
        flash("Error al cargar el panel HR.", "error")
        datos = {"total_empleados": 0, "n_evaluados": 0, "suficiente": False}

    alerta = datos["suficiente"] and datos["pct_riesgo_alto"] >= empresa.umbral_alerta_pct
    departamentos = Departamento.query.filter_by(empresa_id=empresa.id).order_by(Departamento.nombre).all()
    return render_template(
        "dashboards/hr.html", d=datos, K=K_ANONIMATO, periodo=meses, periodos=PERIODOS, empresa=empresa,
        alerta=alerta, gestion=departamentos, hoy=date.today(),
        riesgo=datos.get("riesgo", {}), tendencia_mensual=datos.get("tendencia_mensual", []),
    )


def _volver():
    return redirect(url_for("dashboard.dashboard"))


def _caducidad(valor):
    """'dias' del formulario -> fecha de caducidad (None = no caduca). ValueError si no es válido."""
    dias = int(valor or 0)
    if not 0 <= dias <= 365:
        raise ValueError
    return date.today() + timedelta(days=dias) if dias else None


@bp.route("/departamentos", methods=["POST"])
@solo_hr
def nuevo_departamento():
    nombre = request.form.get("nombre", "").strip()[:100]
    if not nombre:
        flash("El departamento necesita un nombre.", "error")
        return _volver()
    if Departamento.query.filter_by(empresa_id=g.hr.empresa_id, nombre=nombre).first():
        flash("Ya existe un departamento con ese nombre.", "error")
        return _volver()
    db.session.add(Departamento(empresa_id=g.hr.empresa_id, nombre=nombre, codigo_registro=generar_codigo()))
    db.session.commit()
    flash(f"Departamento '{nombre}' creado con su código de registro.", "success")
    return _volver()


def _departamento(dep_id):
    dep = db.session.get(Departamento, dep_id)
    if not dep or dep.empresa_id != g.hr.empresa_id:  # nunca departamentos de otra empresa
        abort(404)
    return dep


@bp.route("/departamentos/<int:dep_id>/codigo", methods=["POST"])
@solo_hr
def regenerar_codigo(dep_id):
    dep = _departamento(dep_id)
    try:
        caduca = _caducidad(request.form.get("dias"))
    except ValueError:
        flash("La caducidad debe estar entre 0 y 365 días.", "error")
        return _volver()
    dep.codigo_registro, dep.codigo_expira = generar_codigo(), caduca
    try:
        db.session.commit()
    except IntegrityError:  # colisión de código (muy improbable)
        db.session.rollback()
        flash("No se pudo generar el código; inténtalo de nuevo.", "error")
    else:
        flash(f"Nuevo código para '{dep.nombre}'. El anterior ya no sirve.", "success")
    return _volver()


@bp.route("/departamentos/<int:dep_id>/codigo/revocar", methods=["POST"])
@solo_hr
def revocar_codigo(dep_id):
    dep = _departamento(dep_id)
    dep.codigo_registro = dep.codigo_expira = None
    db.session.commit()
    flash(f"Código de '{dep.nombre}' revocado.", "success")
    return _volver()


@bp.route("/codigo_empresa", methods=["POST"])
@solo_hr
def caducidad_codigo_empresa():
    try:
        caduca = _caducidad(request.form.get("dias"))
    except ValueError:
        flash("La caducidad debe estar entre 0 y 365 días.", "error")
        return _volver()
    db.session.get(Empresa, g.hr.empresa_id).codigo_expira = caduca
    db.session.commit()
    flash("Caducidad del código general actualizada.", "success")
    return _volver()


@bp.route("/umbral", methods=["POST"])
@solo_hr
def umbral_alerta():
    try:
        pct = int(request.form.get("pct", ""))
        if not 1 <= pct <= 100:
            raise ValueError
    except ValueError:
        flash("El umbral debe ser un porcentaje entre 1 y 100.", "error")
        return _volver()
    db.session.get(Empresa, g.hr.empresa_id).umbral_alerta_pct = pct
    db.session.commit()
    flash("Umbral de alerta actualizado.", "success")
    return _volver()


@bp.route("/exportar_csv")
@solo_hr
def exportar_csv():
    meses = _periodo()
    datos = _datos(g.hr.empresa_id, meses)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["tipo", "nombre", "empleados", "evaluaciones", "media_global", "pct_riesgo_alto"])
    if datos["suficiente"]:
        w.writerow(["resumen", f"últimos {meses} meses" if meses else "todo el histórico", datos["n_evaluados"],
                    datos["total_evaluaciones"], datos["medias"]["media_global"], datos["pct_riesgo_alto"]])
        for dep in datos["departamentos"]:
            w.writerow(["departamento", dep["departamento"], dep["empleados"], dep["evaluaciones"] or "",
                        dep["media_global"] if dep["media_global"] is not None else "", ""])
        for m in datos["tendencia_mensual"]:
            w.writerow(["mes", m["mes"], "", m["total"], "", round(m["riesgo_alto"] / m["total"] * 100, 1)])
    else:  # sin datos suficientes solo se explica por qué
        w.writerow(["aviso", f"menos de {K_ANONIMATO} empleados evaluados: no se muestran datos agregados", "", "", "", ""])
    nombre = f"resilio_hr_{datetime.now():%Y%m%d_%H%M}.csv"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nombre}"})
