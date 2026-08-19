"""Icono elegible por menú (categoría) -- ver app/main.py:ICONOS_MENU_VALIDOS.
El valor viene de un formulario con botones fijos, pero por si alguien
manda un POST a mano con un valor fuera del catálogo, se descarta en vez
de guardarse tal cual (evita referencias a símbolos que no existen en el
sprite, y cierra la puerta a manipular el atributo libremente)."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_crear_menu_con_icono_valido_lo_guarda(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "menu-icono-ok@ejemplo.com", "contrasena123")
    cliente.post("/menus", data={"nombre": "Lueira", "icono": "briefcase"})
    categorias = db.listar_categorias(usuario_id)
    assert categorias[0]["icono"] == "briefcase"


def test_crear_menu_con_icono_fuera_del_catalogo_se_descarta(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "menu-icono-mal@ejemplo.com", "contrasena123")
    cliente.post("/menus", data={"nombre": "Lueira", "icono": "<script>alert(1)</script>"})
    categorias = db.listar_categorias(usuario_id)
    assert categorias[0]["icono"] is None


def test_renombrar_menu_actualiza_icono(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "menu-icono-renombrar@ejemplo.com", "contrasena123")
    cid = db.crear_categoria(usuario_id, "Guilda", icono="folder")
    cliente.post(f"/menu/{cid}/renombrar", data={"nombre": "Guilda", "icono": "rocket"})
    cat = db.obtener_categoria(usuario_id, cid)
    assert cat["icono"] == "rocket"
