import json

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, func

from .extensions import db


class Rol(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)


class Empresa(db.Model):
    __tablename__ = "empresas"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    sector = db.Column(db.String(100))
    codigo_registro = db.Column(db.String(50), unique=True)


class Departamento(db.Model):
    __tablename__ = "departamentos"
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)


class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    rol_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    empresa_id = db.Column(db.Integer, db.ForeignKey("empresas.id", ondelete="SET NULL"))
    departamento_id = db.Column(db.Integer, db.ForeignKey("departamentos.id", ondelete="SET NULL"))
    nombre = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100))
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, server_default=func.now())
    idioma = db.Column(db.String(2), nullable=False, default="es", server_default="es")

    empresa = db.relationship("Empresa")
    departamento = db.relationship("Departamento")


class Dimension(db.Model):
    __tablename__ = "dimensiones"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)


class Pregunta(db.Model):
    __tablename__ = "preguntas"
    id = db.Column(db.Integer, primary_key=True)
    dimension_id = db.Column(db.Integer, db.ForeignKey("dimensiones.id"), nullable=False)
    texto = db.Column(db.String(255), nullable=False)
    es_activo = db.Column(db.Boolean, nullable=False, default=True, server_default="true")


class PreguntaTraduccion(db.Model):
    """Texto de una pregunta en otro idioma (en/ca). El español vive en Pregunta.texto."""

    __tablename__ = "pregunta_traducciones"
    pregunta_id = db.Column(db.Integer, db.ForeignKey("preguntas.id", ondelete="CASCADE"), primary_key=True)
    idioma = db.Column(db.String(2), primary_key=True)
    texto = db.Column(db.String(255), nullable=False)


class Evaluacion(db.Model):
    __tablename__ = "evaluaciones"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    fecha = db.Column(db.DateTime, server_default=func.now())
    puntuacion_total = db.Column(db.Numeric(4, 2), nullable=False)
    dim_agotamiento = db.Column(db.Numeric(4, 2), nullable=False)
    dim_distanciamiento = db.Column(db.Numeric(4, 2), nullable=False)
    dim_cognitivo = db.Column(db.Numeric(4, 2), nullable=False)
    dim_emocional = db.Column(db.Numeric(4, 2), nullable=False)
    consejos = db.Column(db.Text)

    respuestas = db.relationship("RespuestaEvaluacion", cascade="all, delete-orphan")

    @property
    def consejos_data(self):
        """Consejos estructurados (dict) o None. `consejos` guarda JSON, nunca HTML."""
        try:
            data = json.loads(self.consejos or "")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    __table_args__ = (Index("ix_evaluaciones_usuario_fecha", "usuario_id", "fecha"),)


class RespuestaEvaluacion(db.Model):
    __tablename__ = "respuestas_evaluacion"
    id = db.Column(db.Integer, primary_key=True)
    evaluacion_id = db.Column(db.Integer, db.ForeignKey("evaluaciones.id", ondelete="CASCADE"), nullable=False)
    pregunta_id = db.Column(db.Integer, db.ForeignKey("preguntas.id", ondelete="CASCADE"), nullable=False)
    valor = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("valor BETWEEN 1 AND 5", name="ck_respuesta_valor"),
        UniqueConstraint("evaluacion_id", "pregunta_id", name="uq_respuesta_evaluacion_pregunta"),
    )
