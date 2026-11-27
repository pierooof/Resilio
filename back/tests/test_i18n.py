from werkzeug.security import generate_password_hash

from resilio.extensions import db
from resilio.models import Usuario

PASS = "password123"


def test_cambiar_idioma_pone_cookie_y_recuerda_destino(client):
    r = client.get("/idioma/en?next=/login")
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert "lang=en" in r.headers["Set-Cookie"] and "SameSite=Lax" in r.headers["Set-Cookie"]
    assert '<html lang="en">' in client.get("/login").get_data(as_text=True)


def test_idioma_desconocido_o_destino_externo_se_ignoran(client):
    r = client.get("/idioma/klingon?next=/login")
    assert "Set-Cookie" not in r.headers and r.headers["Location"] == "/login"
    assert client.get("/idioma/en?next=//evil.com").headers["Location"] == "/"
    assert client.get("/idioma/en?next=https://evil.com").headers["Location"] == "/"


def test_accept_language_si_no_hay_cookie(client):
    html = client.get("/login", headers={"Accept-Language": "ca-ES,ca;q=0.9"}).get_data(as_text=True)
    assert '<html lang="ca">' in html
    assert '<html lang="es">' in client.get("/login", headers={"Accept-Language": "fr"}).get_data(as_text=True)
    client.set_cookie("lang", "en")  # la elección explícita manda
    assert '<html lang="en">' in client.get("/login", headers={"Accept-Language": "ca"}).get_data(as_text=True)


def test_login_traducido_y_selector_marca_el_activo(client):
    es = client.get("/login").get_data(as_text=True)
    en = client.get("/idioma/en").headers and client.get("/login").get_data(as_text=True)
    assert "Iniciar" in es or "Inicia" in es
    assert 'class="language-btn active"' in en and 'hreflang="en"' in en and "Equilibrio entre mente y código" not in en


def test_cambiar_idioma_logueado_actualiza_el_usuario_y_login_lo_restaura(client):
    u = Usuario(rol_id=3, nombre="A", email="u@x.com", password=generate_password_hash(PASS), idioma="ca")
    db.session.add(u)
    db.session.commit()
    r = client.post("/login", data={"email": "u@x.com", "password": PASS})
    assert "lang=ca" in r.headers["Set-Cookie"]  # sin cookie previa: usa el idioma guardado
    client.get("/idioma/en?next=/dashboard")
    assert db.session.get(Usuario, u.id).idioma == "en"


def test_flashes_en_el_idioma_elegido(client):
    client.set_cookie("lang", "en")
    client.post("/login", data={"email": "no@x.com", "password": "mala"})
    assert "Incorrect email or password" in client.get("/login").get_data(as_text=True)


def test_fechas_y_meses_siguen_el_idioma(app):
    from datetime import date

    from resilio.utils import mes_corto

    with app.test_request_context("/", headers={"Accept-Language": "en"}):
        assert mes_corto(date(2026, 11, 1)) == "Nov 2026"
    with app.test_request_context("/", headers={"Accept-Language": "es"}):
        assert mes_corto(date(2026, 11, 1)).lower().startswith("nov")
