from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

from resilio.extensions import db
from resilio.models import Departamento, Empresa, Evaluacion, Usuario
from resilio.services.anonimato import K_ANONIMATO, OTROS, agrupar_k

from .conftest import necesita_pg

PASS = "password123"


def login(client, email):
    return client.post("/login", data={"email": email, "password": PASS})


def hr_con_empresa(nombre="Acme", email="hr@x.com", codigo="ACME"):
    empresa = Empresa(nombre=nombre, codigo_registro=codigo)
    db.session.add(empresa)
    db.session.commit()
    hr = Usuario(rol_id=2, nombre="Hilda", email=email, empresa_id=empresa.id, password=generate_password_hash(PASS))
    db.session.add(hr)
    db.session.commit()
    return empresa, hr


def empleados(empresa, n, valor=3.0, dep=None, prefijo="e", hace_dias=1):
    """n empleados con una evaluación de la puntuación dada."""
    for i in range(n):
        u = Usuario(rol_id=4, nombre=f"Nombre{prefijo}{i}", email=f"{prefijo}{i}@x.com", empresa_id=empresa.id,
                    departamento_id=dep.id if dep else None, password="x")
        db.session.add(u)
        db.session.flush()
        db.session.add(Evaluacion(usuario_id=u.id, fecha=datetime.now() - timedelta(days=hace_dias),
                                  puntuacion_total=valor, dim_agotamiento=valor, dim_distanciamiento=valor,
                                  dim_cognitivo=valor, dim_emocional=valor))
    db.session.commit()


# ── k-anonimato (función pura) ─────────────────────────────────────────────────
def g(nombre, evaluados, suma_por_eval=3.0):
    return {"departamento": nombre, "empleados": evaluados, "evaluados": evaluados, "evaluaciones": evaluados,
            "suma": evaluados * suma_por_eval}


def test_agrupar_k_oculta_grupos_pequenos_y_los_funde():
    filas = agrupar_k([g("Grande", 6, 4.0), g("A", 2), g("B", 3)])
    assert [f["departamento"] for f in filas] == ["Grande", OTROS]
    assert filas[0]["media_global"] == 4.0
    assert filas[1]["empleados"] == 5 and filas[1]["media_global"] == 3.0  # A+B suman 5: ya se puede mostrar


def test_agrupar_k_fundido_aun_pequeno_va_sin_puntuacion():
    filas = agrupar_k([g("Grande", 6), g("A", 1), g("B", 2)])
    otros = filas[-1]
    assert otros["departamento"] == OTROS and otros["media_global"] is None and otros["evaluaciones"] is None
    assert "A" not in [f["departamento"] for f in filas]


def test_agrupar_k_sin_pequenos_no_crea_otros():
    assert [f["departamento"] for f in agrupar_k([g("X", 5), g("Y", 7, 2.0)])] == ["X", "Y"]  # orden por media desc


# ── Códigos de registro ────────────────────────────────────────────────────────
def datos_registro(codigo):
    return {"nombre": "N", "email": "n@x.com", "password": PASS, "codigo_empresa": codigo}


def test_codigo_de_departamento_asigna_empresa_y_departamento(client):
    empresa, _ = hr_con_empresa()
    dep = Departamento(empresa_id=empresa.id, nombre="IT", codigo_registro="DEP123")
    db.session.add(dep)
    db.session.commit()
    client.post("/register", data=datos_registro("DEP123"))
    u = Usuario.query.filter_by(email="n@x.com").one()
    assert (u.rol_id, u.empresa_id, u.departamento_id) == (4, empresa.id, dep.id)


def test_codigo_caducado_o_revocado_no_registra(client):
    empresa, _ = hr_con_empresa()
    empresa.codigo_expira = date.today() - timedelta(days=1)
    db.session.add(Departamento(empresa_id=empresa.id, nombre="IT", codigo_registro="OLD",
                                codigo_expira=date.today() - timedelta(days=1)))
    db.session.commit()
    client.post("/register", data=datos_registro("ACME"))   # general caducado
    client.post("/register", data=datos_registro("OLD"))    # departamento caducado
    client.post("/register", data=datos_registro("NOPE"))   # inexistente
    assert Usuario.query.filter_by(email="n@x.com").count() == 0
    empresa.codigo_expira = date.today()  # hoy todavía vale
    db.session.commit()
    client.post("/register", data=datos_registro("ACME"))
    assert Usuario.query.filter_by(email="n@x.com").one().empresa_id == empresa.id


# ── Gestión HR (sin SQL de Postgres) ───────────────────────────────────────────
def test_hr_crea_departamento_y_gestiona_su_codigo(client):
    empresa, _ = hr_con_empresa()
    login(client, "hr@x.com")
    client.post("/hr/departamentos", data={"nombre": "Ventas"})
    client.post("/hr/departamentos", data={"nombre": "Ventas"})  # duplicado
    dep = Departamento.query.one()
    assert dep.empresa_id == empresa.id and dep.codigo_registro and dep.codigo_expira is None
    viejo = dep.codigo_registro
    client.post(f"/hr/departamentos/{dep.id}/codigo", data={"dias": "30"})
    assert dep.codigo_registro != viejo and dep.codigo_expira == date.today() + timedelta(days=30)
    client.post(f"/hr/departamentos/{dep.id}/codigo", data={"dias": "999"})  # fuera de rango: no cambia
    assert dep.codigo_expira == date.today() + timedelta(days=30)
    client.post(f"/hr/departamentos/{dep.id}/codigo/revocar")
    assert dep.codigo_registro is None and dep.codigo_expira is None


def test_hr_no_toca_departamentos_de_otra_empresa(client):
    hr_con_empresa()
    otra, _ = hr_con_empresa("Otra", "otro@x.com", "OTRA")
    dep = Departamento(empresa_id=otra.id, nombre="X", codigo_registro="OTRO1")
    db.session.add(dep)
    db.session.commit()
    login(client, "hr@x.com")
    assert client.post(f"/hr/departamentos/{dep.id}/codigo", data={"dias": "1"}).status_code == 404
    assert client.post(f"/hr/departamentos/{dep.id}/codigo/revocar").status_code == 404
    assert dep.codigo_registro == "OTRO1"


def test_solo_hr_puede_gestionar(client):
    db.session.add(Usuario(rol_id=3, nombre="P", email="p@x.com", password=generate_password_hash(PASS)))
    db.session.commit()
    login(client, "p@x.com")
    assert client.post("/hr/departamentos", data={"nombre": "X"}).status_code == 302
    assert Departamento.query.count() == 0
    assert client.get("/hr/exportar_csv").status_code == 302


def test_umbral_y_caducidad_general(client):
    empresa, _ = hr_con_empresa()
    login(client, "hr@x.com")
    client.post("/hr/umbral", data={"pct": "35"})
    client.post("/hr/umbral", data={"pct": "0"})
    client.post("/hr/umbral", data={"pct": "x"})
    assert empresa.umbral_alerta_pct == 35
    client.post("/hr/codigo_empresa", data={"dias": "10"})
    assert empresa.codigo_expira == date.today() + timedelta(days=10)


# ── Panel HR: anonimato (SQL de Postgres) ──────────────────────────────────────
@necesita_pg
def test_panel_hr_con_menos_de_k_no_muestra_nada(client):
    empresa, _ = hr_con_empresa()
    empleados(empresa, K_ANONIMATO - 1, valor=4.5)
    login(client, "hr@x.com")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Aún no hay datos suficientes" in html and "Promedios BAT-12" not in html
    assert "4.5" not in html and "Empleado 0" not in html and "Nombree" not in html
    csv_ = client.get("/hr/exportar_csv").get_data(as_text=True)
    assert "aviso" in csv_ and "4.5" not in csv_


@necesita_pg
def test_panel_hr_con_k_muestra_agregados_sin_nombres_ni_alias(client):
    empresa, hr = hr_con_empresa()
    empleados(empresa, K_ANONIMATO, valor=4.0)
    login(client, "hr@x.com")
    r = client.get("/dashboard")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Error al" not in html
    assert "Promedios BAT-12" in html and "100.0%" in html          # todos en riesgo alto
    assert "Dimensión más afectada" in html and "Otros grupos" in html  # 5 sin departamento: "Sin departamento" visible
    assert "Nombree" not in html and "Evaluaciones recientes" not in html and "Empleado 0" not in html
    csv_ = client.get("/hr/exportar_csv?periodo=12").get_data(as_text=True)
    assert csv_.splitlines()[1].startswith("resumen,") and "Nombree" not in csv_ and "@x.com" not in csv_


@necesita_pg
def test_panel_hr_departamentos_pequenos_se_agrupan(client):
    empresa, _ = hr_con_empresa()
    grande, chico = Departamento(empresa_id=empresa.id, nombre="Grande"), Departamento(empresa_id=empresa.id, nombre="Chico")
    db.session.add_all([grande, chico])
    db.session.commit()
    empleados(empresa, 6, 2.0, grande, "g")
    empleados(empresa, 2, 4.9, chico, "c")
    login(client, "hr@x.com")
    html = client.get("/dashboard").get_data(as_text=True)
    datos = html.split("Acceso y avisos")[0]  # la gestión de códigos sí lista todos los departamentos
    assert "Grande" in datos and "Chico" not in datos and "4.9" not in datos and "Otros grupos" in datos


@necesita_pg
def test_panel_hr_meses_con_pocas_personas_se_omiten_y_periodo(client):
    empresa, _ = hr_con_empresa()
    empleados(empresa, 5, 3.0, prefijo="a", hace_dias=2)        # mes actual: 5 personas
    empleados(empresa, 2, 3.0, prefijo="b", hace_dias=70)       # hace ~2 meses: 2 personas (se omite)
    login(client, "hr@x.com")
    html6 = client.get("/dashboard?periodo=6").get_data(as_text=True)
    assert "const trendData = [{" in html6 and html6.count('"mes"') == 1
    assert client.get("/dashboard?periodo=zzz").status_code == 200   # periodo inválido -> 6
    assert client.get("/dashboard?periodo=99").status_code == 200


@necesita_pg
def test_panel_hr_alerta_cuando_se_supera_el_umbral(client):
    empresa, _ = hr_con_empresa()
    empleados(empresa, 4, 4.0, prefijo="a")   # alto
    empleados(empresa, 6, 1.5, prefijo="b")   # bajo -> 40 % alto
    login(client, "hr@x.com")
    assert "umbral de alerta (20%)" in client.get("/dashboard").get_data(as_text=True)
    client.post("/hr/umbral", data={"pct": "50"})
    assert "umbral de alerta" not in client.get("/dashboard").get_data(as_text=True)


@necesita_pg
def test_hr_solo_ve_su_empresa(client):
    mia, _ = hr_con_empresa()
    ajena, _ = hr_con_empresa("Ajena", "otro@x.com", "AJENA")
    empleados(mia, 5, 1.0, prefijo="m")
    empleados(ajena, 5, 5.0, prefijo="z")
    login(client, "hr@x.com")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Ajena" not in html and "0.0%" in html  # solo veo los míos (ninguno en riesgo alto)
