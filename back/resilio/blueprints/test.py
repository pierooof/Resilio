from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from ..extensions import db, limiter
from ..models import Evaluacion, Pregunta
from ..security import login_required
from ..services.scoring import calcular_y_guardar_bat12

bp = Blueprint("test", __name__)


@bp.route("/test")
@login_required
def realizar_test():
    preguntas = Pregunta.query.filter_by(es_activo=True).order_by(Pregunta.id).all()
    return render_template("test.html", preguntas=preguntas)


@bp.route("/procesar_test", methods=["POST"])
@login_required
@limiter.limit("10 per hour")  # cada envío puede llamar a Gemini
def procesar_test():
    try:
        exito, resultado = calcular_y_guardar_bat12(session["user_id"], request.form)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al guardar el test")
        flash("Error inesperado al procesar tu test. Inténtalo de nuevo.", "error")
    else:
        if exito:
            flash(f"Test procesado con éxito! Tu puntuación global es: {resultado}/5", "success")
        else:
            flash(f"Error al procesar: {resultado}", "error")
    return redirect(url_for("dashboard.dashboard"))


@bp.route("/historial")
@login_required
def historial():
    textos = {p.id: p.texto for p in Pregunta.query.filter_by(es_activo=True)}
    evaluaciones = (
        Evaluacion.query.filter_by(usuario_id=session["user_id"]).order_by(Evaluacion.fecha.desc()).all()
    )
    for ev in evaluaciones:
        ev.detalles = [
            {"pregunta_id": r.pregunta_id, "texto": textos.get(r.pregunta_id, f"Pregunta {r.pregunta_id}"), "valor": r.valor}
            for r in sorted(ev.respuestas, key=lambda r: r.pregunta_id)
        ]
    return render_template("historial.html", evaluaciones=evaluaciones)


@bp.route("/configuracion")
@login_required
def configuracion():
    return render_template("configuracion.html")
