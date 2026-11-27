import secrets
from datetime import date

from flask_babel import gettext as _

from ..models import Departamento, Empresa


class CodigoInvalido(Exception):
    pass


def generar_codigo():
    return secrets.token_hex(5).upper()  # 40 bits; el registro además tiene rate-limit


def resolver_codigo(codigo, hoy=None):
    """Código de registro -> (empresa_id, departamento_id|None). CodigoInvalido si no existe o caducó."""
    hoy = hoy or date.today()
    dep = Departamento.query.filter_by(codigo_registro=codigo).first()
    if dep:
        origen, empresa_id, dep_id = dep, dep.empresa_id, dep.id
    else:
        origen = Empresa.query.filter_by(codigo_registro=codigo).first()
        if not origen:
            raise CodigoInvalido(_("El código de empresa no es válido."))
        empresa_id, dep_id = origen.id, None
    if origen.codigo_expira and origen.codigo_expira < hoy:
        raise CodigoInvalido(_("El código ha caducado. Pide uno nuevo a tu equipo de RR. HH."))
    return empresa_id, dep_id
