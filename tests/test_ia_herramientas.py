"""Tests de app/ia_herramientas.py: el catálogo de herramientas del
Asistente IA y su dispatcher, que reutiliza directamente las funciones ya
definidas en mcp_server.py."""
import pytest

from app import db, ia_herramientas as h


def test_catalogo_tiene_las_mismas_44_herramientas_clasificadas():
    # 39 + 4 del calendario fiscal + 1 de adjuntos del chat (Fase G2).
    nombres = {t["function"]["name"] for t in h.HERRAMIENTAS}
    assert len(nombres) == 44
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


# --- Calendario fiscal (Fase G2) ----------------------------------------------

def test_tools_fiscales_sin_tenant_dan_error_legible(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA, match="tenant"):
        h.ejecutar(usuario_id, "listar_clientes_fiscales", {})


def test_tools_fiscales_ciclo_completo(usuario_id):
    tenant_id = db.crear_tenant("Gestoria IA Herramientas")
    db.asignar_tenant(usuario_id, tenant_id)

    creado = h.ejecutar(usuario_id, "crear_cliente_fiscal", {"nombre": "Cliente IA", "modelos_fiscales": ["303"]})
    assert creado["nombre"] == "Cliente IA"

    listado = h.ejecutar(usuario_id, "listar_clientes_fiscales", {})
    assert len(listado) == 1

    generado = h.ejecutar(
        usuario_id, "generar_vencimientos_fiscales",
        {"cliente_id": creado["id"], "modelos": ["303"], "anio": 2026},
    )
    assert generado["creados"] == 4

    vencimientos = h.ejecutar(usuario_id, "listar_vencimientos_fiscales", {})
    assert len(vencimientos) == 4


# --- Adjuntos del chat (Fase G2) ----------------------------------------------

def test_leer_adjunto_chat_es_privado_del_usuario(usuario_id):
    otro_usuario_id = db.crear_usuario_vinculado_a_kratos("otro-adjunto@ejemplo.com", "kratos-otro-adjunto")
    adjunto_id = db.crear_adjunto_ia(usuario_id, "datos.csv", "text/csv", b"a,b\n1,2\n")

    resultado = h.ejecutar(usuario_id, "leer_adjunto_chat", {"adjunto_id": adjunto_id})
    assert resultado["nombre_archivo"] == "datos.csv"
    assert "1,2" in resultado["texto"]

    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(otro_usuario_id, "leer_adjunto_chat", {"adjunto_id": adjunto_id})
