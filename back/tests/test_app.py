import json
import re
from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from resilio.extensions import db, limiter, mail
from resilio.models import Departamento, Empresa, Evaluacion, Usuario
from resilio.services.scoring import calcular_y_guardar_bat12

from .conftest import crear, necesita_pg

PASS = "password123"
RESPUESTAS = {f"pregunta_{i}": "3" for i in range(1, 13)}


def usuario(rol=3, email="u@x.com", empresa_id=None, consentimiento=True, **kw):
    u = Usuario(rol_id=rol, nombre=kw.pop("nombre", "Ana"), email=email, empresa_id=empresa_id,
                password=generate_password_hash(PASS),
                consentimiento_fecha=datetime.now() if consentimiento else None, **kw)
    db.session.add(u)
    db.session.commit()
    return u


def login(client, email="u@x.com", password=PASS):
    return client.post("/login", data={"email": email, "password": password})


# ── Auth ───────────────────────────────────────────────────────────────────────
def test_login_correcto_e_incorrecto(client):
    usuario()
    assert login(client, password="mala").headers["Location"] == "/login"
    assert login(client).headers["Location"] == "/dashboard"


def test_registro_personal_y_empresa(client):
    db.session.add(Empresa(nombre="Acme", codigo_registro="ACME"))
    db.session.commit()
    datos = {"nombre": "A", "email": "a@x.com", "password": PASS}
    client.post("/register", data=datos)
    client.post("/register", data={**datos, "email": "b@x.com", "codigo_empresa": "ACME"})
    assert Usuario.query.filter_by(email="a@x.com").one().rol_id == 3
    assert Usuario.query.filter_by(email="b@x.com").one().rol_id == 4


def test_registro_rechaza_password_corta_y_codigo_falso(client):
    client.post("/register", data={"nombre": "A", "email": "a@x.com", "password": "corta"})
    client.post("/register", data={"nombre": "A", "email": "a@x.com", "password": PASS, "codigo_empresa": "NOPE"})
    assert Usuario.query.count() == 0


def test_logout_solo_por_post(client):
    usuario()
    login(client)
    assert client.get("/logout").status_code == 405
    client.post("/logout")
    assert client.get("/dashboard").headers["Location"].endswith("/login")


def test_csrf_activo_rechaza_post_sin_token():
    app = crear(WTF_CSRF_ENABLED=True)
    assert app.test_client().post("/login", data={"email": "a", "password": "b"}).status_code == 400


def test_rate_limit_login():
    app = crear(RATELIMIT_ENABLED=True)
    limiter.reset()
    c = app.test_client()
    codigos = [c.post("/login", data={"email": "a", "password": "b"}).status_code for _ in range(11)]
    limiter.reset()
    assert codigos[:10] == [302] * 10 and codigos[10] == 429


def _enlace_reset(app, client, email):
    with mail.record_messages() as enviados:
        client.post("/forgot_password", data={"email": email})
    return re.search(r"/reset_password/\S+", enviados[0].body).group(0) if enviados else None


def test_reset_password_un_solo_uso(app, client):
    usuario()
    enlace = _enlace_reset(app, client, "u@x.com")
    assert client.get(enlace).status_code == 200
    client.post(enlace, data={"password": "nueva-clave-1", "confirm_password": "nueva-clave-1"})
    assert login(client, password="nueva-clave-1").headers["Location"] == "/dashboard"
    assert client.get(enlace).status_code == 302  # el hash cambió → el token ya no vale


def test_reset_password_token_manipulado_y_email_inexistente(app, client):
    usuario()
    enlace = _enlace_reset(app, client, "u@x.com")
    assert client.get(enlace[:-3] + "xxx").status_code == 302
    assert _enlace_reset(app, client, "nadie@x.com") is None


def test_reset_password_rechaza_clave_corta(app, client):
    usuario()
    enlace = _enlace_reset(app, client, "u@x.com")
    client.post(enlace, data={"password": "corta", "confirm_password": "corta"})
    assert login(client).headers["Location"] == "/dashboard"  # sigue valiendo la antigua


# ── Admin ──────────────────────────────────────────────────────────────────────
def test_admin_requiere_rol_1(client):
    usuario(rol=3)
    login(client)
    client.post("/admin/nueva_empresa", data={"nombre": "X", "codigo_registro": "X1"})
    assert Empresa.query.count() == 0


def test_admin_crea_empresa_y_usuarios_validados(client):
    usuario(rol=1, email="admin@x.com")
    login(client, "admin@x.com")
    client.post("/admin/nueva_empresa", data={"nombre": "Acme", "codigo_registro": "A1"})
    client.post("/admin/nueva_empresa", data={"nombre": "Otra", "codigo_registro": "A1"})  # código repetido
    acme = Empresa.query.one()
    otra = Empresa(nombre="Otra", codigo_registro="O1")
    db.session.add(otra)
    db.session.commit()
    dep = Departamento(empresa_id=otra.id, nombre="IT")
    db.session.add(dep)
    db.session.commit()
    base = {"nombre": "N", "password": PASS}

    client.post("/admin/nuevo_usuario", data={**base, "email": "mal@x.com", "rol_id": "abc"})
    client.post("/admin/nuevo_usuario", data={**base, "email": "mal@x.com", "rol_id": "99"})
    client.post("/admin/nuevo_usuario", data={**base, "email": "mal@x.com", "rol_id": "2"})  # HR sin empresa
    client.post("/admin/nuevo_usuario", data={**base, "email": "mal@x.com", "rol_id": "4",
                                              "empresa_id": acme.id, "departamento_id": dep.id})  # dep ajeno
    assert Usuario.query.filter_by(email="mal@x.com").count() == 0

    client.post("/admin/nuevo_usuario", data={**base, "email": "hr@x.com", "rol_id": "2", "empresa_id": acme.id})
    assert Usuario.query.filter_by(email="hr@x.com").one().rol_id == 2


# ── Test BAT-12 e historial ────────────────────────────────────────────────────
def test_test_requiere_login(client):
    assert client.get("/test").headers["Location"].endswith("/login")
    assert client.post("/procesar_test", data=RESPUESTAS).headers["Location"].endswith("/login")


def test_procesar_test_guarda_y_historial_muestra_preguntas(client):
    usuario()
    login(client)
    assert "agotado/a mentalmente" in client.get("/test").get_data(as_text=True)
    r = client.post("/procesar_test", data=RESPUESTAS)
    assert r.headers["Location"].startswith("/resultado/")
    client.post("/procesar_test", data={"pregunta_1": "3"})  # incompleto: no guarda
    assert Evaluacion.query.count() == 1
    assert "agotado/a en mi trabajo" in client.get("/historial").get_data(as_text=True)


# ── Consentimiento y test por pasos (HTMX) ─────────────────────────────────────
def test_sin_consentimiento_no_hay_test_y_el_next_es_interno(client):
    u = usuario(consentimiento=False)
    login(client)
    assert client.get("/test").headers["Location"] == "/consentimiento?next=/test"
    assert client.post("/test/responder", data={"n": 1, "valor": 3}).status_code == 302
    client.post("/consentimiento?next=//evil.com", data={})  # sin marcar: nada
    assert db.session.get(Usuario, u.id).consentimiento_fecha is None
    r = client.post("/consentimiento?next=//evil.com", data={"acepto": "1"})
    assert r.headers["Location"] == "/test"  # //evil.com descartado
    assert db.session.get(Usuario, u.id).consentimiento_fecha is not None


def test_test_por_pasos_guarda_borrador_y_reanuda(client):
    u = usuario()
    login(client)
    assert "agotado/a mentalmente" in client.get("/test/pregunta/1").get_data(as_text=True)
    sig = client.post("/test/responder", data={"n": 1, "valor": 4}).get_data(as_text=True)
    assert "recuperar mi energía" in sig and 'name="n" value="2"' in sig
    for n, valor in ((2, 5), (3, 2), (4, 1), (5, 3)):
        client.post("/test/responder", data={"n": n, "valor": valor})
    assert 'name="n" value="6"' in client.get("/test").get_data(as_text=True)  # reanuda en la 6
    assert 'value="3" checked' in client.get("/test/pregunta/5").get_data(as_text=True)  # recuerda lo marcado
    assert client.post("/test/responder", data={"n": 1, "valor": 6}).status_code == 400
    assert client.post("/test/responder", data={"n": 13, "valor": 3}).status_code == 400
    assert client.post("/test/responder", data={"n": "x", "valor": 3}).status_code == 400
    assert client.get("/test/pregunta/99").status_code == 404
    assert Evaluacion.query.count() == 0


def test_completar_por_pasos_y_enviar_desde_el_borrador(client):
    u = usuario()
    login(client)
    ultimo = None
    for n in range(1, 13):
        ultimo = client.post("/test/responder", data={"n": n, "valor": 3}).get_data(as_text=True)
    assert "/procesar_test" in ultimo and "Enviar Respuestas" in ultimo
    client.set_cookie("lang", "ca")
    r = client.post("/procesar_test")  # las respuestas vienen del borrador
    ev = Evaluacion.query.one()
    assert r.headers["Location"] == f"/resultado/{ev.id}" and float(ev.puntuacion_total) == 3.0
    assert ev.consejos_data["lang"] == "ca"
    assert client.get("/test").get_data(as_text=True).count('name="n" value="1"') == 1  # borrador borrado


def test_resultado_solo_del_dueno_y_compara_con_la_anterior(client):
    a, b = usuario(email="a@x.com"), usuario(email="b@x.com")
    login(client, "a@x.com")
    client.post("/procesar_test", data={f"pregunta_{i}": "4" for i in range(1, 13)})
    client.post("/procesar_test", data={f"pregunta_{i}": "2" for i in range(1, 13)})
    ultima = Evaluacion.query.order_by(Evaluacion.id.desc()).first()
    html = client.get(f"/resultado/{ultima.id}").get_data(as_text=True)
    assert "2.00" in html and "-2.00" in html and "Has bajado respecto" in html and "tendenciaChart" in html
    login(client, "b@x.com")
    assert client.get(f"/resultado/{ultima.id}").status_code == 404
    assert client.get("/resultado/9999").status_code == 404


# ── Cuenta: recordatorios, exportar, eliminar ──────────────────────────────────
def test_recordatorio_valida_cadencia(client):
    u = usuario()
    login(client)
    client.post("/configuracion/recordatorio", data={"semanas": "4"})
    assert db.session.get(Usuario, u.id).recordatorio_semanas == 4
    client.post("/configuracion/recordatorio", data={"semanas": "5"})  # no permitida
    assert db.session.get(Usuario, u.id).recordatorio_semanas == 4
    client.post("/configuracion/recordatorio", data={"semanas": "0"})
    assert db.session.get(Usuario, u.id).recordatorio_semanas is None


def test_exportar_mis_datos(client):
    usuario()
    login(client)
    client.post("/procesar_test", data=RESPUESTAS)
    r = client.get("/configuracion/exportar")
    datos = json.loads(r.get_data(as_text=True))
    assert "attachment" in r.headers["Content-Disposition"] and datos["usuario"]["email"] == "u@x.com"
    assert len(datos["evaluaciones"][0]["respuestas"]) == 12 and "password" not in json.dumps(datos)


def test_eliminar_cuenta_pide_contrasena_y_borra_todo(client):
    u = usuario()
    login(client)
    client.post("/procesar_test", data=RESPUESTAS)
    client.post("/configuracion/eliminar", data={"password": "mala"})
    assert Usuario.query.count() == 1
    client.post("/configuracion/eliminar", data={"password": PASS})
    assert Usuario.query.count() == 0 and Evaluacion.query.count() == 0
    assert client.get("/dashboard").headers["Location"].endswith("/login")


def test_admin_no_se_elimina_desde_configuracion(client):
    usuario(rol=1, email="admin@x.com")
    login(client, "admin@x.com")
    client.post("/configuracion/eliminar", data={"password": PASS})
    assert Usuario.query.count() == 1


def test_recordatorios_se_envian_a_quien_toca_y_una_sola_vez(app):
    app.config["APP_URL"] = "https://resilio.test"
    ahora = datetime.now()
    toca = usuario(email="toca@x.com", recordatorio_semanas=4, idioma="en")
    reciente = usuario(email="reciente@x.com", recordatorio_semanas=4)
    sin_optin = usuario(email="no@x.com")
    for u, hace in ((toca, 5), (reciente, 1), (sin_optin, 10)):
        db.session.add(Evaluacion(usuario_id=u.id, fecha=ahora - timedelta(weeks=hace), puntuacion_total=3,
                                  dim_agotamiento=3, dim_distanciamiento=3, dim_cognitivo=3, dim_emocional=3))
    db.session.commit()

    from resilio.services.recordatorios import enviar_recordatorios

    with mail.record_messages() as enviados:
        assert enviar_recordatorios(ahora) == 1
        assert enviar_recordatorios(ahora) == 0  # ya avisado: no se repite hasta pasada otra cadencia
    assert [m.recipients for m in enviados] == [["toca@x.com"]]
    assert "https://resilio.test/test" in enviados[0].body and "repeat your BAT-12" in enviados[0].subject


def test_recordatorio_fallido_no_se_marca_y_exige_app_url(app, monkeypatch):
    from resilio.services.recordatorios import enviar_recordatorios

    with pytest.raises(RuntimeError, match="APP_URL"):
        enviar_recordatorios()
    app.config["APP_URL"] = "https://resilio.test"
    u = usuario(recordatorio_semanas=2, fecha_registro=datetime.now() - timedelta(weeks=3))
    monkeypatch.setattr(mail, "send", lambda m: (_ for _ in ()).throw(RuntimeError("smtp caído")))
    assert enviar_recordatorios() == 0 and db.session.get(Usuario, u.id).ultimo_recordatorio is None


def test_preguntas_en_los_tres_idiomas(client):
    usuario()
    login(client)
    es = client.get("/test").get_data(as_text=True)
    assert "agotado/a mentalmente" in es and "traducción no oficial" not in es
    assert "Indique con qué frecuencia cada frase se aplica a usted." in es and "burnoutassessmenttool.be" in es
    client.set_cookie("lang", "en")
    en = client.get("/test").get_data(as_text=True)
    assert "At work, I feel mentally exhausted" in en and "agotado/a mentalmente" not in en
    assert "unofficial" not in en  # el inglés es el texto oficial: sin aviso
    assert "Please state how often each statement applies to you." in en
    assert 'htmx.min.js' in en and 'X-CSRFToken' in en
    client.set_cookie("lang", "ca")
    ca = client.get("/test").get_data(as_text=True)
    assert "A la feina, em sento esgotat/ada mentalment" in ca and "traducció no oficial i no validada" in ca
    assert "Atrás" not in client.get("/test/pregunta/2").get_data(as_text=True)  # el botón también se traduce


def test_test_envia_idioma_y_consejos_estructurados(client):
    u = usuario()
    login(client)
    client.set_cookie("lang", "en")
    client.post("/procesar_test", data=RESPUESTAS)
    assert Evaluacion.query.one().consejos_data["lang"] == "en" and db.session.get(Usuario, u.id).idioma == "en"


def test_consejos_se_escapan_sin_safe(client):
    u = usuario()
    malo = {"intro": "<script>alert(1)</script>", "ia": True, "lang": "es",
            "consejos": [{"titulo": "<img src=x onerror=alert(2)>", "texto": "ok"}] * 3}
    db.session.add(Evaluacion(usuario_id=u.id, puntuacion_total=3, dim_agotamiento=3, dim_distanciamiento=3,
                              dim_cognitivo=3, dim_emocional=3, consejos=json.dumps(malo)))
    db.session.commit()
    login(client)
    for url in ("/dashboard", "/historial"):
        html = client.get(url).get_data(as_text=True)
        assert "<script>alert(1)" not in html and "<img src=x" not in html and "&lt;script&gt;alert(1)" in html, url


# ── Dashboards (SQL de Postgres) ───────────────────────────────────────────────
@necesita_pg
def test_dashboards_por_rol_y_exports(client):
    empresa = Empresa(nombre="Acme", codigo_registro="A1")
    db.session.add(empresa)
    db.session.commit()
    usuario(rol=1, email="admin@x.com")
    usuario(rol=2, email="hr@x.com", empresa_id=empresa.id, nombre="Hilda")
    emp = usuario(rol=4, email="emp@x.com", empresa_id=empresa.id, nombre="Secretisimo")
    usuario(rol=3, email="per@x.com")
    calcular_y_guardar_bat12(emp.id, RESPUESTAS)

    for email, esperado in (("admin@x.com", "Acme"), ("hr@x.com", "Aún no hay datos suficientes"),
                            ("emp@x.com", "3.0"), ("per@x.com", "")):
        c = client.application.test_client()
        login(c, email)
        r = c.get("/dashboard")
        assert r.status_code == 200 and esperado in r.get_data(as_text=True), email
        assert "Error al" not in r.get_data(as_text=True), email
        if email == "hr@x.com":
            assert "Secretisimo" not in r.get_data(as_text=True)  # HR no ve nombres

    c = client.application.test_client()
    login(c, "admin@x.com")
    csv_ = c.get("/admin/exportar_csv")
    assert csv_.mimetype == "text/csv" and "emp@x.com" in csv_.get_data(as_text=True)
    informe = c.get("/admin/informe_global")
    assert informe.status_code == 200 and "Error al" not in informe.get_data(as_text=True)
