import re

from werkzeug.security import generate_password_hash

from resilio.extensions import db, limiter, mail
from resilio.models import Departamento, Empresa, Evaluacion, Usuario
from resilio.services.scoring import calcular_y_guardar_bat12

from .conftest import crear, necesita_pg

PASS = "password123"
RESPUESTAS = {f"pregunta_{i}": "3" for i in range(1, 13)}


def usuario(rol=3, email="u@x.com", empresa_id=None, **kw):
    u = Usuario(rol_id=rol, nombre=kw.pop("nombre", "Ana"), email=email, empresa_id=empresa_id,
                password=generate_password_hash(PASS), **kw)
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
    assert b"pregunta_12" in client.get("/test").data
    client.post("/procesar_test", data=RESPUESTAS)
    client.post("/procesar_test", data={"pregunta_1": "3"})  # incompleto: no guarda
    assert Evaluacion.query.count() == 1
    assert "agotado/a en el trabajo" in client.get("/historial").get_data(as_text=True)


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

    for email, esperado in (("admin@x.com", "Acme"), ("hr@x.com", "Empleado 01"),
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
