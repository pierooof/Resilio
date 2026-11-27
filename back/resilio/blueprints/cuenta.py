import json
from datetime import datetime

from flask_babel import gettext as _
from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, limiter
from ..models import Pregunta, TestBorrador, Usuario
from ..security import login_required
from .auth import MIN_PASSWORD

bp = Blueprint("cuenta", __name__)

CADENCIAS = (2, 4, 8)  # semanas entre recordatorios


def _usuario():
    return db.session.get(Usuario, session["user_id"])


@bp.route("/consentimiento", methods=["GET", "POST"])
@login_required
def consentimiento():
    destino = request.args.get("next", "")
    if not destino.startswith("/") or destino.startswith("//"):  # solo rutas internas
        destino = url_for("test.realizar_test")
    if request.method == "POST":
        if request.form.get("acepto"):
            _usuario().consentimiento_fecha = datetime.now()
            db.session.commit()
            return redirect(destino)
        flash(_("Para hacer el test tienes que aceptar el tratamiento de tus datos."), "error")
    return render_template("consentimiento.html", destino=destino)


@bp.route("/configuracion")
@login_required
def configuracion():
    return render_template("configuracion.html", usuario=_usuario(), cadencias=CADENCIAS)


@bp.route("/configuracion/recordatorio", methods=["POST"])
@login_required
def recordatorio():
    try:
        semanas = int(request.form.get("semanas") or 0)
    except ValueError:
        semanas = -1
    if semanas and semanas not in CADENCIAS:
        flash(_("Frecuencia no válida."), "error")
        return redirect(url_for("cuenta.configuracion"))
    u = _usuario()
    u.recordatorio_semanas = semanas or None
    db.session.commit()
    flash(_("Preferencia de recordatorios guardada."), "success")
    return redirect(url_for("cuenta.configuracion"))


@bp.route("/configuracion/password", methods=["POST"])
@login_required
@limiter.limit("5 per hour")  # evita adivinar la contraseña actual con una sesión abierta
def cambiar_password():
    u = _usuario()
    f = request.form
    nueva = f.get("nueva", "")
    if not check_password_hash(u.password, f.get("actual", "")):
        flash(_("La contraseña actual no es correcta."), "error")
    elif nueva != f.get("confirmar", ""):
        flash(_("Las contraseñas no coinciden."), "error")
    elif len(nueva) < MIN_PASSWORD:
        flash(_("La contraseña debe tener al menos %(n)s caracteres.", n=MIN_PASSWORD), "error")
    elif check_password_hash(u.password, nueva):
        flash(_("La nueva contraseña debe ser distinta de la actual."), "error")
    else:
        u.password = generate_password_hash(nueva)  # también invalida los enlaces de recuperación pendientes
        db.session.commit()
        flash(_("Contraseña actualizada correctamente."), "success")
    return redirect(url_for("cuenta.configuracion"))


@bp.route("/configuracion/exportar")
@login_required
def exportar():
    u = _usuario()
    textos = {p.id: p.texto for p in Pregunta.query}
    datos = {
        "usuario": {"nombre": u.nombre, "apellidos": u.apellidos, "email": u.email, "idioma": u.idioma,
                    "fecha_registro": u.fecha_registro, "consentimiento_fecha": u.consentimiento_fecha,
                    "recordatorio_semanas": u.recordatorio_semanas},
        "evaluaciones": [
            {"fecha": e.fecha, "puntuacion_total": float(e.puntuacion_total),
             "dimensiones": {"agotamiento": float(e.dim_agotamiento), "distanciamiento": float(e.dim_distanciamiento),
                             "cognitivo": float(e.dim_cognitivo), "emocional": float(e.dim_emocional)},
             "consejos": e.consejos_data,
             "respuestas": [{"pregunta_id": r.pregunta_id, "pregunta": textos.get(r.pregunta_id), "valor": r.valor}
                            for r in sorted(e.respuestas, key=lambda r: r.pregunta_id)]}
            for e in sorted(u.evaluaciones, key=lambda e: (e.fecha, e.id))
        ],
    }
    return Response(
        json.dumps(datos, ensure_ascii=False, indent=2, default=lambda o: o.isoformat()),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=resilio_mis_datos.json"},
    )


@bp.route("/configuracion/eliminar", methods=["POST"])
@login_required
def eliminar():
    u = _usuario()
    if u.rol_id == 1:
        flash(_("Una cuenta de administrador no se puede eliminar desde aquí."), "error")
        return redirect(url_for("cuenta.configuracion"))
    if not check_password_hash(u.password, request.form.get("password", "")):
        flash(_("Contraseña incorrecta: no se ha eliminado nada."), "error")
        return redirect(url_for("cuenta.configuracion"))
    TestBorrador.query.filter_by(usuario_id=u.id).delete()
    db.session.delete(u)  # las evaluaciones y respuestas caen en cascada
    db.session.commit()
    session.clear()
    flash(_("Tu cuenta y todos tus datos se han eliminado."), "success")
    return redirect(url_for("auth.login"))
