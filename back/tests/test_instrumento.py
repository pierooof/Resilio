"""El BAT-12 es un instrumento que no debe modificarse (burnoutassessmenttool.be): este test fija
el texto oficial en español e inglés y la estructura 3 ítems × 4 dimensiones."""
from resilio.models import Pregunta, PreguntaTraduccion

OFICIAL_ES = [
    "En mi trabajo, me siento agotado/a mentalmente",
    "Al final del día de trabajo, me resulta difícil recuperar mi energía",
    "Me siento físicamente agotado/a en mi trabajo",
    "Me esfuerzo por encontrar entusiasmo en mi trabajo",
    "Siento una fuerte aversión hacia mi trabajo",
    "Soy cínico sobre lo que mi trabajo significa para los demás",
    "Tengo problemas para mantenerme enfocado en mi trabajo",
    "Cuando estoy trabajando, tengo dificultades para concentrarme",
    "Cometo errores en mi trabajo, porque tengo mi mente en otras cosas",
    "En mi trabajo, me siento incapaz de controlar mis emociones",
    "No me reconozco en la forma que reacciono en el trabajo",
    "Puedo reaccionar exageradamente sin querer",
]
OFICIAL_EN = [
    "At work, I feel mentally exhausted",
    "After a day at work, I find it hard to recover my energy",
    "At work, I feel physically exhausted",
    "I struggle to find any enthusiasm for my work",
    "I feel a strong aversion towards my job",
    "I'm cynical about what my work means to others",
    "At work, I have trouble staying focused",
    "When I'm working, I have trouble concentrating",
    "I make mistakes in my work because I have my mind on other things",
    "At work, I feel unable to control my emotions",
    "I do not recognize myself in the way I react emotionally at work",
    "At work I may overreact unintentionally",
]


def test_texto_oficial_es_y_en(app):
    es = [p.texto for p in Pregunta.query.order_by(Pregunta.id)]
    en = [t.texto for t in PreguntaTraduccion.query.filter_by(idioma="en").order_by(PreguntaTraduccion.pregunta_id)]
    assert es == OFICIAL_ES and en == OFICIAL_EN


def test_tres_items_por_dimension_y_catalan_completo(app):
    dims = [p.dimension_id for p in Pregunta.query.order_by(Pregunta.id)]
    assert dims == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]
    assert PreguntaTraduccion.query.filter_by(idioma="ca").count() == 12
