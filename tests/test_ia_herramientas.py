"""Tests de app/ia_herramientas.py: el catálogo de herramientas del
Asistente IA y su dispatcher, que reutiliza directamente las funciones ya
definidas en mcp_server.py."""
import pytest

from app import db, ia_herramientas as h


def test_catalogo_tiene_las_mismas_27_herramientas_clasificadas():
    nombres = {t["function"]["name"] for t in h.HERRAMIENTAS}
    assert len(nombres) == 27
    assert nombres == (h.LECTURA | h.ESCRITURA | h.SIEMPRE_CONFIRMAR)
    assert not (h.LECTURA & h.ESCRITURA)
    assert not (h.LECTURA & h.SIEMPRE_CONFIRMAR)
    assert not (h.ESCRITURA & h.SIEMPRE_CONFIRMAR)


def test_ejecutar_crear_nota_usa_mcp_server_directamente(usuario_id):
    resultado = h.ejecutar(usuario_id, "crear_nota", {"texto": "creada por el asistente"})
    assert resultado["texto"] == "creada por el asistente"
    notas = [n for n in db.historial(usuario_id) if n["origen"] == "nota"]
    assert len(notas) == 1


def test_ejecutar_herramienta_desconocida_da_error_legible(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "no_existe", {})


def test_ejecutar_propaga_value_error_como_error_de_herramienta(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "editar_nota", {"nota_id": 9999, "texto": "x"})


@pytest.mark.parametrize(
    "nombre,modo_autonomo,esperado",
    [
        ("listar_notas", False, False),
        ("listar_notas", True, False),
        ("crear_nota", False, True),
        ("crear_nota", True, False),
        ("enviar_borrador_correo", True, True),
        ("enviar_borrador_correo", False, True),
    ],
)
def test_necesita_confirmacion(nombre, modo_autonomo, esperado):
    assert h.necesita_confirmacion(nombre, modo_autonomo) is esperado
