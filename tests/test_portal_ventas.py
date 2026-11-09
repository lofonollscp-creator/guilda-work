"""«Mis ventas» (A2): el cliente factura desde el portal con FacturaScripts (simulado: nunca se toca una instancia real), apagado por defecto y aislado por cliente."""
import pytest

from app import db, facturascripts, portal_ventas as pv
from tests.test_facturas_contables import _web
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


class FS:
    """Una FacturaScripts de mentira que apunta lo que se le pide."""
    def __init__(self, monkeypatch, empresas=(2,)):
        self.clientes, self.facturas, self.empresas = [], [], [{"idempresa": e} for e in empresas]
        monkeypatch.setattr(facturascripts, "crear_cliente", self._crear_cliente)
        monkeypatch.setattr(facturascripts, "crear_factura", self._crear_factura)
        monkeypatch.setattr(facturascripts, "obtener_factura", lambda url, key, i: {"codigo": f"FAC2026{i}", "neto": 100.0, "total": 121.0})
        monkeypatch.setattr(facturascripts, "listar_empresas", lambda url, key: self.empresas)
        self.cae = False

    def _crear_cliente(self, url, key, nombre, nif="", email=""):
        self.clientes.append((nombre, nif, email))
        return {"codcliente": f"{len(self.clientes):06d}"}

    def _crear_factura(self, url, key, codcliente, lineas, extra=None):
        if self.cae:
            raise facturascripts.ErrorFacturaScripts("caída")
        self.facturas.append((codcliente, lineas, extra))
        return {"idfactura": str(len(self.facturas))}


def _preparar(t, c, activar=True, idempresa=2, serie="A"):
    conn = db.get_connection()
    conn.execute("UPDATE tenants SET facturascripts_url = 'http://fs.test', facturascripts_api_key = 'k' WHERE id = ?", (t,))
    conn.execute("UPDATE clientes_fiscales SET ventas_portal = ?, facturascripts_idempresa = ?, facturascripts_serie = ? WHERE id = ?", (1 if activar else 0, idempresa, serie, c))
    conn.commit(); conn.close()


def test_apagado_por_defecto_y_sin_empresa_o_sin_facturascripts_no_hay_ventas(cliente, correo):
    t, u, c = _despacho("Ventas apagado")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert pv.activa_para(_ficha(c)) is False and cliente.get("/portal/ventas").status_code == 404 and "/portal/ventas" not in _html(cliente, "/portal/")
    _preparar(t, c, activar=True, idempresa=None)
    assert pv.activa_para(_ficha(c)) is False
    _preparar(t, c)
    conn = db.get_connection(); conn.execute("UPDATE tenants SET facturascripts_url = NULL WHERE id = ?", (t,)); conn.commit(); conn.close()
    assert pv.activa_para(_ficha(c)) is False


def test_alta_de_un_cliente_y_emision_a_nombre_de_su_empresa_con_su_serie(cliente, correo, monkeypatch):
    fs = FS(monkeypatch)
    t, u, c = _despacho("Ventas flujo")
    _preparar(t, c)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "/portal/ventas" in _html(cliente, "/portal/") and "Mis ventas" in _html(cliente, "/portal/ventas")
    r = cliente.post("/portal/ventas/clientes", data={"nombre": "Bar Paco SL", "nif": "b87654323", "email": "paco@bar.es"})
    assert r.status_code == 302 and fs.clientes == [("Bar Paco SL", "B87654323", "paco@bar.es")]
    vc = pv.clientes(_ficha(c))[0]
    r = cliente.post("/portal/ventas/nueva", data={"cliente_id": vc["id"], "descripcion_0": "Consultoría octubre", "cantidad_0": "2", "precio_0": "50,00", "descripcion_1": "", "precio_1": ""})
    assert r.status_code == 302 and "emitida=" in r.headers["Location"]
    cod, lineas, extra = fs.facturas[0]
    assert cod == vc["codcliente"] and lineas == [{"descripcion": "Consultoría octubre", "cantidad": 2.0, "precio": 50.0}] and extra["idempresa"] == 2 and extra["codserie"] == "A" and extra["fecha"]
    f = pv.listar(_ficha(c))[0]
    assert f["codigo"] == "FAC20261" and f["total_centimos"] == 12100 and f["cliente_nombre"] == "Bar Paco SL"
    html = _html(cliente, r.headers["Location"])
    assert "Factura emitida" in html and "FAC20261" in html
    pdf = cliente.get(f"/portal/ventas/{f['id']}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and pdf.headers["Cache-Control"] == "private, no-store"


def test_validaciones_y_si_facturascripts_cae_no_se_apunta_nada(cliente, correo, monkeypatch):
    fs = FS(monkeypatch)
    t, u, c = _despacho("Ventas validar")
    _preparar(t, c)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Indica el nombre y el NIF" in cliente.post("/portal/ventas/clientes", data={"nombre": "x", "nif": ""}, follow_redirects=True).get_data(as_text=True)
    cliente.post("/portal/ventas/clientes", data={"nombre": "Cliente Uno", "nif": "A11111119"})
    vc = pv.clientes(_ficha(c))[0]["id"]
    for malo, msg in (({"descripcion_0": "x", "precio_0": "0"}, "positivos"), ({"descripcion_0": "x", "precio_0": "abc"}, "número válido"), ({"descripcion_0": "", "precio_0": ""}, "al menos una línea"), ({"descripcion_0": "x", "precio_0": "5", "fecha": "2026-02-31"}, "fecha válida")):
        assert msg in cliente.post("/portal/ventas/nueva", data={"cliente_id": vc, **malo}, follow_redirects=True).get_data(as_text=True)
    assert "Elige uno de tus clientes" in cliente.post("/portal/ventas/nueva", data={"cliente_id": 9999, "descripcion_0": "x", "precio_0": "5"}, follow_redirects=True).get_data(as_text=True)
    fs.cae = True
    assert "No se ha creado nada" in cliente.post("/portal/ventas/nueva", data={"cliente_id": vc, "descripcion_0": "x", "precio_0": "5"}, follow_redirects=True).get_data(as_text=True)
    assert pv.listar(_ficha(c)) == [] and fs.facturas == []


def test_cada_cliente_solo_ve_y_usa_lo_suyo(cliente, correo, monkeypatch):
    fs = FS(monkeypatch)
    t, u, c = _despacho("Ventas aislado")
    t2, u2, c2 = _despacho("Ventas ajeno", cliente_email="otro@ejemplo.com", cliente_nombre="Otra SL")
    _preparar(t, c); _preparar(t2, c2)
    ajeno = pv.anadir_cliente(_ficha(c2), "Cliente de otra", "B87654323")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert pv.clientes(_ficha(c)) == [] and "Elige uno de tus clientes" in cliente.post("/portal/ventas/nueva", data={"cliente_id": ajeno, "descripcion_0": "x", "precio_0": "5"}, follow_redirects=True).get_data(as_text=True)
    f2 = pv.emitir(_ficha(c2), ajeno, [{"descripcion": "x", "cantidad": 1.0, "precio": 5.0}], "otro")
    assert cliente.get(f"/portal/ventas/{f2['id']}.pdf").status_code == 404


def test_el_perfil_de_consulta_ve_pero_no_emite(cliente, correo, monkeypatch):
    from app import portal_personas
    FS(monkeypatch)
    t, u, c = _despacho("Ventas consulta")
    _preparar(t, c)
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    _entrar(cliente, c, "mira@ejemplo.com")
    assert cliente.get("/portal/ventas").status_code == 200 and cliente.post("/portal/ventas/nueva", data={}).status_code == 403 and cliente.post("/portal/ventas/clientes", data={}).status_code == 403


def test_el_equipo_activa_comprobando_que_la_empresa_existe(cliente, monkeypatch):
    uid, t, c = _web(cliente, email="ventas-equipo@ejemplo.com")
    FS(monkeypatch, empresas=(3,))
    conn = db.get_connection(); conn.execute("UPDATE tenants SET facturascripts_url = 'http://fs.test', facturascripts_api_key = 'k' WHERE id = ?", (t,)); conn.commit(); conn.close()
    cliente.post(f"/fiscal/clientes/{c}/ventas-portal", data={"activo": "1", "idempresa": "9"})
    assert db.obtener_cliente_fiscal_por_id(c)["ventas_portal"] == 0                                    # la empresa 9 no existe: no se activa
    cliente.post(f"/fiscal/clientes/{c}/ventas-portal", data={"activo": "1", "idempresa": "3", "serie": "b"})
    f = db.obtener_cliente_fiscal_por_id(c)
    assert (f["ventas_portal"], f["facturascripts_idempresa"], f["facturascripts_serie"]) == (1, 3, "B")
    cliente.post(f"/fiscal/clientes/{c}/ventas-portal", data={})
    assert db.obtener_cliente_fiscal_por_id(c)["ventas_portal"] == 0


def test_crear_factura_manda_los_campos_extra_sin_pisar_el_cliente_ni_las_lineas_y_omite_los_vacios(monkeypatch):
    enviados = []
    monkeypatch.setattr(facturascripts, "_peticion", lambda url, key, endpoint, metodo="GET", cuerpo=None: enviados.append((endpoint, cuerpo)) or (200, {"idfactura": "7"}))
    facturascripts.crear_factura("http://x", "k", "000001", [{"descripcion": "a", "cantidad": 1, "precio": 2}], extra={"idempresa": 3, "codserie": None, "fecha": "2026-01-01", "codcliente": "HACK", "lineas": []})
    assert enviados[0] == ("crearFacturaCliente", {"idempresa": 3, "fecha": "2026-01-01", "codcliente": "000001", "lineas": [{"descripcion": "a", "cantidad": 1, "precio": 2}]})
