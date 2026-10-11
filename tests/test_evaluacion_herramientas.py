"""Evaluación de la oferta de herramientas: ¿la herramienta que hace falta está ya en el primer turno? Sin modelo real: mide lo que SÍ depende
de nosotros (agrupar las ~90 herramientas por palabras clave) con un conjunto de peticiones realistas (tests/datos/evaluacion_herramientas.py)."""
import pytest

from app import herramientas_grupos as hg
from app import ia_herramientas as ih
from tests.datos.evaluacion_herramientas import CASOS


def _ofrecidas(peticion: str) -> set[str]:
    return {t["function"]["name"] for t in ih.herramientas_para([{"role": "user", "content": peticion}])}


def test_el_conjunto_es_valido_y_equilibrado():
    nombres = {t["function"]["name"] for t in ih.HERRAMIENTAS}
    assert len(CASOS) >= 55 and len({p for p, _ in CASOS}) == len(CASOS), "peticiones repetidas o muy pocas"
    desconocidas = sorted({h for _, h in CASOS if h not in nombres})
    assert not desconocidas, f"herramientas esperadas que no existen: {desconocidas}"
    grupos = {hg.grupo_de(h) for _, h in CASOS}
    assert grupos >= set(hg.GRUPOS), f"faltan peticiones de los grupos: {set(hg.GRUPOS) - grupos}"


@pytest.mark.parametrize("peticion,esperada", CASOS)
def test_la_herramienta_correcta_esta_en_el_primer_turno(peticion, esperada):
    assert esperada in _ofrecidas(peticion), f"«{peticion}» → falta {esperada} (grupo {hg.grupo_de(esperada)})"


def test_la_oferta_sigue_siendo_pequena():
    """El objetivo de los grupos es no mandar las ~90 herramientas en cada turno: de media debe ofrecerse una fracción."""
    total = len(ih.HERRAMIENTAS)
    medias = [len(_ofrecidas(p)) for p, _ in CASOS]
    assert sum(medias) / len(medias) <= total * 0.55, f"se ofrecen de media {sum(medias) / len(medias):.0f} de {total}"
    assert len(_ofrecidas("hola, ¿qué tal?")) <= 20, "una charla sin intención no debería traer herramientas de dominio"
