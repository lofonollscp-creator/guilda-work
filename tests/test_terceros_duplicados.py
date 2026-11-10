"""Terceros duplicados de un cliente (app/terceros_duplicados.py)."""
import pytest

from app import facturas_contables as fc, terceros_duplicados as td
from tests.test_facturas_contables import LINEA, _datos, _despacho, _web


def _f(t, u, c, numero, nif, nombre, tipo="recibida", estado=None):
    fid = fc.crear(t, u, c, _datos(numero=numero, tipo=tipo, tercero_nif=nif, tercero_nombre=nombre), [LINEA])
    if estado == "exportada":
        fc.cambiar_estado(t, u, fid, "revisada", confirmar_duplicado=True)
        fc.exportar(t, u, c)
    return fid


def test_encuentra_el_mismo_nif_con_nombres_distintos_y_el_mismo_nombre_con_nifs_distintos():
    t, u, c = _despacho()
    _f(t, u, c, "A-1", "A58818501", "Papelería Sol S.L."); _f(t, u, c, "A-2", "A58818501", "PAPELERIA SOL"); _f(t, u, c, "A-3", "A58818501", "Papelería Sol S.L.")
    _f(t, u, c, "B-1", "B12345674", "Transportes Norte"); _f(t, u, c, "B-2", "B12345675", "Transportes Norte")
    _f(t, u, c, "C-1", "B99999999", "Único SL")
    d = td.encontrar(t, u, c)
    assert [(x["nif"], [(n["nombre"], n["facturas"]) for n in x["nombres"]]) for x in d["mismo_nif"]] == [("A58818501", [("Papelería Sol S.L.", 2), ("PAPELERIA SOL", 1)])]
    assert [(x["nombre"], sorted(n["nif"] for n in x["nifs"])) for x in d["mismo_nombre"]] == [("Transportes Norte", ["B12345674", "B12345675"])]


def test_un_proveedor_y_un_cliente_con_el_mismo_nif_no_se_mezclan():
    t, u, c = _despacho()
    _f(t, u, c, "A-1", "A58818501", "Sol SL"); _f(t, u, c, "V-1", "A58818501", "Sol SL (cliente)", tipo="emitida")
    assert td.encontrar(t, u, c) == {"mismo_nif": [], "mismo_nombre": []}


def test_unificar_el_nombre_solo_toca_pendientes_y_revisadas():
    t, u, c = _despacho()
    exportada = _f(t, u, c, "A-1", "A58818501", "PAPELERIA SOL", estado="exportada")
    pendiente = _f(t, u, c, "A-2", "A58818501", "Papelería  sol")
    assert td.unificar_nombre(t, u, c, "recibida", "A58818501", "Papelería Sol S.L.") == 1
    assert fc.obtener(t, u, pendiente)["tercero_nombre"] == "Papelería Sol S.L." and fc.obtener(t, u, exportada)["tercero_nombre"] == "PAPELERIA SOL"
    assert td.unificar_nombre(t, u, c, "recibida", "A58818501", "Papelería Sol S.L.") == 0                      # ya estaba
    with pytest.raises(ValueError):
        td.unificar_nombre(t, u, c, "recibida", "A58818501", "  ")


def test_corregir_un_nif_mal_leido():
    t, u, c = _despacho()
    a = _f(t, u, c, "B-1", "B12345675", "Transportes Norte"); _f(t, u, c, "B-2", "B12345674", "Transportes Norte")
    assert td.corregir_nif(t, u, c, "recibida", "B12345675", "B12345674") == 1 and fc.obtener(t, u, a)["tercero_nif"] == "B12345674"
    assert td.encontrar(t, u, c)["mismo_nombre"] == []
    for malo in (("recibida", "", "B12345674"), ("recibida", "B12345674", "B12345674"), ("rara", "B12345674", "B1")):
        with pytest.raises(ValueError):
            td.corregir_nif(t, u, c, *malo)


def test_la_pantalla_lista_y_corrige(cliente):
    uid, t, c = _web(cliente, "tercerosdup@ejemplo.com")
    _f(t, uid, c, "A-1", "A58818501", "Papelería Sol S.L."); _f(t, uid, c, "A-2", "A58818501", "PAPELERIA SOL")
    _f(t, uid, c, "B-1", "B12345674", "Transportes Norte"); _f(t, uid, c, "B-2", "B12345675", "Transportes Norte")
    html = cliente.get(f"/contabilidad/cliente/{c}/terceros").get_data(as_text=True)
    assert "Mismo NIF con nombres distintos" in html and "Mismo nombre con NIF distintos" in html
    r = cliente.post(f"/contabilidad/cliente/{c}/terceros", data={"accion": "nombre", "tipo": "recibida", "nif": "A58818501", "nombre": "Papelería Sol S.L."})
    assert "Se ha unificado el nombre en 1 factura" in r.get_data(as_text=True)
    r = cliente.post(f"/contabilidad/cliente/{c}/terceros", data={"accion": "nif", "tipo": "recibida", "nif_mal": "B12345675", "nif_bien": "B12345674"})
    assert "Se ha corregido el NIF en 1 factura" in r.get_data(as_text=True) and "No hay duplicados" in r.get_data(as_text=True)
    assert "Proveedores y clientes duplicados" in cliente.get(f"/contabilidad/cliente/{c}/cuentas").get_data(as_text=True)
