from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for)

from ..extensions import db, limiter
from ..models import Evaluacion, Pregunta, TestBorrador
from ..security import consentimiento_requerido, login_required
from ..services.preguntas import i18n_preguntas
from ..services.scoring import calcular_y_guardar_bat12, nivel_riesgo

bp = Blueprint("test", __name__)

DIMENSIONES_COLS = (("agotamiento", "dim_agotamiento"), ("distanciamiento", "dim_distanciamiento"),
                    ("cognitivo", "dim_cognitivo"), ("emocional", "dim_emocional"))


def _borrador():
    b = db.session.get(TestBorrador, session["user_id"])
    return {int(k): v for k, v in (b.respuestas if b else {}).items()}


def _paso(n=None):
    """Contexto de la pantalla del test: pregunta n (1..total), o el envío si está todo respondido."""
    preguntas = Pregunta.query.filter_by(es_activo=True).order_by(Pregunta.id).all()
    total, borrador = len(preguntas), _borrador()
    respondidas = sum(1 for p in preguntas if p.id in borrador)
    if n is None:  # reanudar: primera sin responder
        n = next((i for i, p in enumerate(preguntas, 1) if p.id not in borrador), total + 1)
    if not 1 <= n <= total + 1:
        abort(404)
    ctx = dict(n=n, total=total, respondidas=respondidas, listo=n > total)
    if n <= total:
        ctx.update(pregunta=preguntas[n - 1], valor_actual=borrador.get(preguntas[n - 1].id))
    return ctx


@bp.route("/test")
@consentimiento_requerido
def realizar_test():
    return render_template("test.html", i18n_preguntas=i18n_preguntas(), **_paso())


@bp.route("/test/pregunta/<int:n>")
@consentimiento_requerido
def pregunta(n):
    return render_template("_test_paso.html", **_paso(n))


@bp.route("/test/responder", methods=["POST"])
@consentimiento_requerido
def responder():
    preguntas = Pregunta.query.filter_by(es_activo=True).order_by(Pregunta.id).all()
    try:
        n, valor = int(request.form["n"]), int(request.form["valor"])
        if not (1 <= n <= len(preguntas) and 1 <= valor <= 5):
            raise ValueError
    except (KeyError, ValueError):
        abort(400)

    b = db.session.get(TestBorrador, session["user_id"])
    if not b:
        b = TestBorrador(usuario_id=session["user_id"], respuestas={})
        db.session.add(b)
    b.respuestas = {**b.respuestas, str(preguntas[n - 1].id): valor}  # reasignar: JSON no detecta mutaciones
    db.session.commit()

    borrador = _borrador()
    siguiente = n + 1 if n < len(preguntas) else next(
        (i for i, p in enumerate(preguntas, 1) if p.id not in borrador), len(preguntas) + 1
    )
    return render_template("_test_paso.html", **_paso(siguiente))


@bp.route("/procesar_test", methods=["POST"])
@consentimiento_requerido
@limiter.limit("10 per hour")  # cada envío puede llamar a Gemini
def procesar_test():
    datos = {f"pregunta_{k}": v for k, v in _borrador().items()} | request.form.to_dict()
    try:
        exito, resultado = calcular_y_guardar_bat12(session["user_id"], datos, request.form.get("lang"))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al guardar el test")
        flash("Error inesperado al procesar tu test. Inténtalo de nuevo.", "error")
        return redirect(url_for("test.realizar_test"))

    if not exito:
        flash(f"Error al procesar: {resultado}", "error")
        return redirect(url_for("test.realizar_test"))
    TestBorrador.query.filter_by(usuario_id=session["user_id"]).delete()
    db.session.commit()
    return redirect(url_for("test.resultado", evaluacion_id=resultado.id))


@bp.route("/resultado/<int:evaluacion_id>")
@login_required
def resultado(evaluacion_id):
    ev = db.session.get(Evaluacion, evaluacion_id)
    if not ev or ev.usuario_id != session["user_id"]:
        abort(404)
    todas = Evaluacion.query.filter_by(usuario_id=ev.usuario_id).order_by(Evaluacion.fecha, Evaluacion.id).all()
    previa = next((e for e in reversed(todas) if (e.fecha, e.id) < (ev.fecha, ev.id)), None)
    dims = []
    for clave, col in DIMENSIONES_COLS:
        valor = float(getattr(ev, col))
        dims.append({"clave": clave, "valor": valor,
                     "delta": round(valor - float(getattr(previa, col)), 2) if previa else None})
    return render_template(
        "resultado.html", ev=ev, previa=previa, tendencia=todas, dims=dims,
        mayor=max(dims, key=lambda d: d["valor"])["clave"], nivel=nivel_riesgo(float(ev.puntuacion_total)),
        delta=round(float(ev.puntuacion_total) - float(previa.puntuacion_total), 2) if previa else None,
    )


@bp.route("/historial")
@login_required
def historial():
    textos = {p.id: p.texto for p in Pregunta.query.filter_by(es_activo=True)}  # es; en/ca vía i18n_preguntas
    evaluaciones = (
        Evaluacion.query.filter_by(usuario_id=session["user_id"]).order_by(Evaluacion.fecha.desc()).all()
    )
    for ev in evaluaciones:
        ev.detalles = [
            {"pregunta_id": r.pregunta_id, "texto": textos.get(r.pregunta_id, f"Pregunta {r.pregunta_id}"), "valor": r.valor}
            for r in sorted(ev.respuestas, key=lambda r: r.pregunta_id)
        ]
    return render_template("historial.html", evaluaciones=evaluaciones, i18n_preguntas=i18n_preguntas())
