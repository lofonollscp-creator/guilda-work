"""Facturación conectada al trabajo del despacho (app/facturacion_despacho.py, app/rutas_cobros.py, ficha del cliente y «Hoy»)."""
from datetime import date

import pytest

from app import bandeja_hoy, db, facturacion_despacho as fd, facturascripts as fs, nucleo, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba


class FakeFS:
    """FacturaScripts de mentira: guarda las facturas que se «crean» y responde a listar/obtener."""
    def __init__(self):
        self.facturas = []
        self.fallar = False
        self.llamadas = 0

    def listar(self, url, key, cliente_codigo=None, limite=20):
        self.llamadas += 1
        if self.fallar:
            raise fs.ErrorFacturaScripts("caído")
        return [f for f in self.facturas if cliente_codigo in (None, f["codcliente"])][:limite]

    def crear(self, url, key, cliente_codigo, lineas):
        if self.fallar:
            raise fs.ErrorFacturaScripts("caído")
        n = len(self.facturas) + 1
        precio = lineas[0]["precio"]
        self.facturas.append({"idfactura": str(n), "codigo": f"FAC2026{n:04d}", "codcliente": cliente_codigo, "nombrecliente": "Cliente", "fecha": date.today().isoformat(),
                              "total": round(precio * 1.21, 2), "pagada": False, "vencida": False})
        return {"idfactura": str(n)}

    def obtener(self, url, key, idfactura):
        return next((f for f in self.facturas if f["idfactura"] == str(idfactura)), None)


@pytest.fixture
def ffs(monkeypatch):
    f = FakeFS()
    monkeypatch.setattr(fs, "listar_facturas", f.listar)
    monkeypatch.setattr(fs, "crear_factura", f.crear)
    monkeypatch.setattr(fs, "obtener_factura", f.obtener)
    fd._cache.clear()
    return f


def _despacho(vinculado=True, con_fs=True, gestion_fiscal=True):
    t = db.crear_tenant("Despacho fact")
    u1 = db.crear_usuario_vinculado_a_kratos("fact1@ejemplo.com", "k-fact1"); db.asignar_tenant(u1, t); db.asignar_supervisor_tenant(u1, True)
    u2 = db.crear_usuario_vinculado_a_kratos("fact2@ejemplo.com", "k-fact2"); db.asignar_tenant(u2, t)
    if con_fs:
        db.guardar_facturascripts(t, "http://127.0.0.1:1/", "admin", "x"); db.guardar_facturascripts_api_key(t, "clave")
    nombre = "Cliente Facturable"
    if gestion_fiscal:
        f = crear_cliente_fiscal(t, nombre, nif="12345678Z")
        if vinculado:
            db.editar_cliente_fiscal(t, f, facturascripts_cliente_codigo="C1")
        c = nucleo.listar_clientes(t, limite=5)[0][0]["id"]
    else:
        c = nucleo.crear_cliente(t, nombre)
    x = nucleo.crear_expediente(t, u2, c, "Asunto a facturar", responsable_id=u2)
    return t, u1, u2, x


# --- importes y estado -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [("1234,56", "1234.56"), ("1.234,56", "1234.56"), ("1234.56", "1234.56"), ("500", "500.00"), (" 99,9 € ", "99.90"), ("1.000", "1000.00")])
def test_importes_validos(texto, esperado):
    assert str(fd.importe_valido(texto)) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "0", "-5", "0,00", "9999999999", "1,2,3"])
def test_importes_no_validos(texto):
    with pytest.raises(ValueError):
        fd.importe_valido(texto)


def test_estado_y_resumen_de_cobro():
    fs_ = [{"total": "100", "pagada": True}, {"total": "50.5", "pagada": False, "vencida": True}, {"total": "20", "pagada": False, "vencida": False}, {"total": None}]
    assert [fd.estado_de(f) for f in fs_] == ["pagada", "vencida", "pendiente", "pendiente"]
    r = fd.resumen_cobro(fs_)
    assert (float(r["facturado"]), float(r["cobrado"]), float(r["pendiente"]), float(r["vencido"]), r["n_vencidas"], r["n"]) == (170.5, 100.0, 70.5, 50.5, 1, 4)


# --- Facturar desde un expediente --------------------------------------------------------------------------------------------------------------

def test_facturar_crea_la_factura_enlaza_el_expediente_y_deja_rastro(ffs):
    t, u1, u2, x = _despacho()
    r = fd.facturar_expediente(t, u2, False, x, "Honorarios de la demanda", "1.000,00")
    assert r["idfactura"] == "1" and r["codigo"] == "FAC20260001" and str(r["base"]) == "1000.00"
    assert ffs.facturas[0]["total"] == 1210.0 and ffs.facturas[0]["codcliente"] == "C1"
    lista = fd.facturas_del_expediente(t, x)
    assert [(f["codigo"], f["estado"], f["base"]) for f in lista] == [("FAC20260001", "pendiente", "1.000,00 €")]
    assert any(e["tipo"] == "factura" and "FAC20260001" in e["texto"] for e in db.get_connection().execute("SELECT * FROM expediente_eventos WHERE expediente_id = ?", (x,)).fetchall())
    from app import auditoria
    assert "factura.creada" in [a["accion"] for a in auditoria.listar(t)]


def test_quien_no_lleva_el_expediente_no_puede_facturar_y_la_direccion_si(ffs):
    t, u1, u2, x = _despacho()
    otro = db.crear_usuario_vinculado_a_kratos("fact3@ejemplo.com", "k-fact3"); db.asignar_tenant(otro, t)
    with pytest.raises(ValueError, match="Solo la dirección"):
        fd.facturar_expediente(t, otro, False, x, "x", "10")
    assert ffs.facturas == []
    assert fd.facturar_expediente(t, u1, True, x, "Por la dirección", "10")["idfactura"] == "1"


@pytest.mark.parametrize("kw,mensaje", [({"vinculado": False}, "Vincula primero"), ({"gestion_fiscal": False}, "gestión fiscal")])
def test_sin_vincular_o_sin_gestion_fiscal_explica_que_falta(ffs, kw, mensaje):
    t, u1, u2, x = _despacho(**kw)
    with pytest.raises(ValueError, match=mensaje):
        fd.facturar_expediente(t, u2, False, x, "x", "10")
    assert ffs.facturas == []


def test_sin_facturascripts_no_se_ofrece_nada(ffs):
    t, u1, u2, x = _despacho(con_fs=False)
    exp = nucleo.obtener_expediente(t, x, u2)
    assert fd.situacion(t, u2, False, exp) == {"disponible": False, "motivo": None}
    with pytest.raises(ValueError, match="FacturaScripts"):
        fd.facturar_expediente(t, u2, False, x, "x", "10")


def test_validaciones_de_concepto_e_importe(ffs):
    t, u1, u2, x = _despacho()
    for concepto, importe, fragmento in (("", "10", "concepto"), ("x" * 201, "10", "largo"), ("ok", "abc", "importe"), ("ok", "0", "mayor")):
        with pytest.raises(ValueError, match=fragmento):
            fd.facturar_expediente(t, u2, False, x, concepto, importe)
    assert ffs.facturas == []


def test_si_facturascripts_falla_no_se_guarda_nada(ffs):
    t, u1, u2, x = _despacho()
    ffs.fallar = True
    with pytest.raises(fs.ErrorFacturaScripts):
        fd.facturar_expediente(t, u2, False, x, "x", "10")
    assert db.get_connection().execute("SELECT COUNT(*) FROM facturacion_expedientes").fetchone()[0] == 0


def test_un_expediente_confidencial_ajeno_no_se_puede_facturar(ffs):
    t, u1, u2, x = _despacho()
    c = nucleo.listar_clientes(t, limite=5)[0][0]["id"]
    reservado = nucleo.crear_expediente(t, u1, c, "Reservado", confidencial=True)
    with pytest.raises(ValueError, match="no encontrado"):
        fd.facturar_expediente(t, u2, False, reservado, "x", "10")


def test_las_relaciones_se_borran_con_el_despacho(ffs):
    t, u1, u2, x = _despacho()
    fd.facturar_expediente(t, u2, False, x, "x", "10")
    db.borrar_tenant(t, incluir_fichajes=True)
    assert db.get_connection().execute("SELECT COUNT(*) FROM facturacion_expedientes").fetchone()[0] == 0


# --- Estado de cobro y vencidas -----------------------------------------------------------------------------------------------------------------

def test_la_cache_evita_llamar_a_facturascripts_en_cada_pantalla(ffs):
    t, u1, u2, x = _despacho()
    fd._facturas(t); fd._facturas(t); fd._facturas(t)
    assert ffs.llamadas == 1
    fd.olvidar_cache(t); fd._facturas(t)
    assert ffs.llamadas == 2


def test_facturascripts_caido_no_rompe_nada(ffs):
    t, u1, u2, x = _despacho()
    ffs.fallar = True
    assert fd._facturas(t) == [] and fd.facturas_del_expediente(t, x) == [] and fd.vencidas_sin_cobrar(t, u1, True) == []


def test_vencidas_sin_cobrar_segun_quien_pregunta(ffs):
    t, u1, u2, x = _despacho()
    otro = db.crear_usuario_vinculado_a_kratos("fact4@ejemplo.com", "k-fact4"); db.asignar_tenant(otro, t)
    fd.facturar_expediente(t, u2, False, x, "Uno", "100")
    fd.facturar_expediente(t, u2, False, x, "Dos", "200")
    ffs.facturas[0]["vencida"] = True
    ffs.facturas[1]["pagada"] = True
    fd.olvidar_cache(t)
    dir_ = fd.vencidas_sin_cobrar(t, u1, True)
    assert [f["codigo"] for f in dir_] == ["FAC20260001"] and dir_[0]["expediente_id"] == x
    assert [f["codigo"] for f in fd.vencidas_sin_cobrar(t, u2, False)] == ["FAC20260001"], "quien lleva el expediente la ve"
    assert fd.vencidas_sin_cobrar(t, otro, False) == [], "otra persona sin expediente, no"


def test_hoy_enseña_las_facturas_vencidas_a_quien_toca(ffs, cliente):
    uid = iniciar_sesion_de_prueba(cliente, "hoyfact@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho hoyfact"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    db.guardar_facturascripts(t, "http://127.0.0.1:1/", "a", "b"); db.guardar_facturascripts_api_key(t, "k")
    verticales.fijar_activo(t, "abogados", True)
    ffs.facturas.append({"idfactura": "7", "codigo": "FAC70", "codcliente": "Z", "nombrecliente": "Moroso S.L.", "fecha": "2026-01-01", "total": 500.0, "pagada": False, "vencida": True})
    html = cliente.get("/hoy/").get_data(as_text=True)
    assert "Facturas vencidas sin cobrar" in html and "Factura FAC70 sin cobrar" in html and "Moroso S.L." in html


# --- Pantallas --------------------------------------------------------------------------------------------------------------------------------------

def test_el_panel_del_expediente_ofrece_facturar_y_lista_lo_facturado(ffs, cliente):
    uid = iniciar_sesion_de_prueba(cliente, "panelfact@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho panelfact"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    db.guardar_facturascripts(t, "http://127.0.0.1:1/", "a", "b"); db.guardar_facturascripts_api_key(t, "k")
    f = crear_cliente_fiscal(t, "Cliente Panel", nif="12345678Z"); db.editar_cliente_fiscal(t, f, facturascripts_cliente_codigo="C9")
    c = nucleo.listar_clientes(t, limite=5)[0][0]["id"]
    x = nucleo.crear_expediente(t, uid, c, "Expediente panel")
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert 'id="facturacion"' in html and "Emitir factura" in html and "Todavía no se ha facturado nada" in html
    r = cliente.post(f"/expedientes/{x}/facturar", data={"concepto": "Honorarios", "importe": "300,00"})
    assert r.status_code == 302 and "error=" in r.headers["Location"], "sin la casilla de confirmación no se factura"
    assert ffs.facturas == []
    r = cliente.post(f"/expedientes/{x}/facturar", data={"concepto": "Honorarios", "importe": "300,00", "confirmo": "1"})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert "FAC20260001" in html and "Honorarios" in html and "Pendiente de cobro" in html and "300,00 €" in html
    ffs.facturas[0]["pagada"] = True; fd.olvidar_cache(t)
    assert "Cobrada" in cliente.get(f"/expedientes/{x}").get_data(as_text=True)


def test_el_panel_no_aparece_sin_facturascripts_ni_para_quien_no_puede(ffs, cliente):
    uid = iniciar_sesion_de_prueba(cliente, "sinfs@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho sinfs"); db.asignar_tenant(uid, t)
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, uid, c, "Expediente")
    assert 'id="facturacion"' not in cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    db.guardar_facturascripts(t, "http://127.0.0.1:1/", "a", "b"); db.guardar_facturascripts_api_key(t, "k")
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert 'id="facturacion"' in html and "Emitir factura" not in html and "gestión fiscal" in html


def test_la_ficha_del_cliente_enseña_el_estado_de_cobro(ffs, cliente):
    uid = iniciar_sesion_de_prueba(cliente, "cobro@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho cobro"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    db.guardar_facturascripts(t, "http://127.0.0.1:1/", "a", "b"); db.guardar_facturascripts_api_key(t, "k")
    f = crear_cliente_fiscal(t, "Cliente Cobro", nif="12345678Z"); db.editar_cliente_fiscal(t, f, facturascripts_cliente_codigo="C5")
    ffs.facturas += [{"idfactura": "1", "codigo": "A1", "codcliente": "C5", "fecha": "2026-01-01", "total": 100.0, "pagada": True, "vencida": False},
                     {"idfactura": "2", "codigo": "A2", "codcliente": "C5", "fecha": "2026-02-01", "total": 60.0, "pagada": False, "vencida": True}]
    c = nucleo.listar_clientes(t, limite=5)[0][0]["id"]
    html = cliente.get(f"/clientes/{c}?pestana=fiscal").get_data(as_text=True)
    assert "Facturado" in html and "160.00 €" in html and "Cobrado" in html and "100.00 €" in html and "60.00 €" in html and "1 factura vencida" in html and "Cobrada" in html and "Vencida" in html
