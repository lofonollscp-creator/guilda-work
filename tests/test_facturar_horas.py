"""Facturar las horas de un expediente (app/facturacion_despacho.py › facturar_horas, POST /expedientes/<id>/facturar-horas). FacturaScripts es siempre el de mentira: nunca se emite nada real."""
import pytest

from app import db, facturacion_despacho as fd, facturascripts as fs, nucleo
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturacion_despacho import FakeFS, _despacho


class FSVarias(FakeFS):
    """Como el de mentira, pero suma todas las líneas y recuerda lo que se le mandó."""
    def crear(self, url, key, cliente_codigo, lineas):
        self.enviadas = lineas
        r = super().crear(url, key, cliente_codigo, [{"precio": sum(l["precio"] * l["cantidad"] for l in lineas)}])
        return r


@pytest.fixture
def ffs(monkeypatch):
    f = FSVarias()
    monkeypatch.setattr(fs, "listar_facturas", f.listar)
    monkeypatch.setattr(fs, "crear_factura", f.crear)
    monkeypatch.setattr(fs, "obtener_factura", f.obtener)
    fd._cache.clear()
    return f


def _partes(t, u, x, *specs):
    """specs: (minutos, tarifa €/h o None, facturable)"""
    return [nucleo.registrar_parte(t, u, f"Trabajo {i}", minutos=m, expediente_id=x, facturable=fa, tarifa_hora_centimos=int(tar * 100) if tar else None, supervisor=True)
            for i, (m, tar, fa) in enumerate(specs, start=1)]


def test_solo_salen_las_horas_facturables_aun_sin_facturar_con_su_importe(ffs):
    t, u1, u2, x = _despacho()
    a, b, c, d = _partes(t, u2, x, (90, 100, True), (30, 80, True), (60, 100, False), (60, None, True))
    nucleo.marcar_facturado(t, [b])
    horas = {h["id"]: h for h in fd.horas_sin_facturar(t, x)}
    assert set(horas) == {a, d} and horas[a]["importe_centimos"] == 15000 and horas[d]["importe_centimos"] == 0


def test_facturar_horas_crea_una_linea_por_parte_las_marca_y_deja_rastro(ffs):
    t, u1, u2, x = _despacho()
    a, b = _partes(t, u2, x, (90, 100, True), (30, 80, True))
    r = fd.facturar_horas(t, u2, False, x, [a, b])
    assert (r["partes"], r["base_centimos"], r["idfactura"]) == (2, 19000, "1")
    assert [l["precio"] for l in ffs.enviadas] == [150.0, 40.0] and "1:30 h × 100.00 €/h" in ffs.enviadas[0]["descripcion"] and "Trabajo 1" in ffs.enviadas[0]["descripcion"]
    assert fd.horas_sin_facturar(t, x) == []
    f = fd.facturas_del_expediente(t, x)[0]
    assert f["base"].startswith("190") and "2 partes" in f["concepto"]
    with pytest.raises(ValueError, match="ya se ha facturado"):
        fd.facturar_horas(t, u2, False, x, [a])
    assert len(ffs.facturas) == 1, "no se factura dos veces"


def test_si_facturascripts_falla_las_horas_quedan_libres(ffs):
    t, u1, u2, x = _despacho()
    a, = _partes(t, u2, x, (60, 100, True))
    ffs.fallar = True
    with pytest.raises(fs.ErrorFacturaScripts):
        fd.facturar_horas(t, u2, False, x, [a])
    assert [h["id"] for h in fd.horas_sin_facturar(t, x)] == [a]
    ffs.fallar = False
    assert fd.facturar_horas(t, u2, False, x, [a])["partes"] == 1


@pytest.mark.parametrize("ids,fragmento", [([], "al menos un parte"), ([999999], "ya se ha facturado o no es de este expediente")])
def test_selecciones_no_validas(ffs, ids, fragmento):
    t, u1, u2, x = _despacho()
    _partes(t, u2, x, (60, 100, True))
    with pytest.raises(ValueError, match=fragmento):
        fd.facturar_horas(t, u2, False, x, ids)


def test_horas_sin_tarifa_o_de_otro_expediente_no_se_facturan(ffs):
    t, u1, u2, x = _despacho()
    sin, = _partes(t, u2, x, (60, None, True))
    with pytest.raises(ValueError, match="sin tarifa"):
        fd.facturar_horas(t, u2, False, x, [sin])
    c = nucleo.listar_clientes(t, limite=5)[0][0]["id"]
    y = nucleo.crear_expediente(t, u2, c, "Otro asunto", responsable_id=u2)
    ajena, = _partes(t, u2, y, (60, 100, True))
    with pytest.raises(ValueError, match="no es de este expediente"):
        fd.facturar_horas(t, u2, False, x, [ajena])
    assert [h["id"] for h in fd.horas_sin_facturar(t, y)] == [ajena]
    assert ffs.facturas == []


def test_maximo_de_partes_y_permisos(ffs):
    t, u1, u2, x = _despacho()
    ids = _partes(t, u2, x, *[(10, 100, True)] * (fd.MAX_PARTES_POR_FACTURA + 1))
    with pytest.raises(ValueError, match="Como máximo"):
        fd.facturar_horas(t, u2, False, x, ids)
    otro = db.crear_usuario_vinculado_a_kratos("horas-otro@ejemplo.com", "k-horas-otro"); db.asignar_tenant(otro, t)
    with pytest.raises(ValueError):
        fd.facturar_horas(t, otro, False, x, ids[:1])
    assert fd.facturar_horas(t, u1, True, x, ids[:2])["partes"] == 2, "la dirección sí puede"


def test_sin_vincular_con_facturascripts_no_se_factura(ffs):
    t, u1, u2, x = _despacho(vinculado=False)
    a, = _partes(t, u2, x, (60, 100, True))
    with pytest.raises(ValueError, match="Vincula primero"):
        fd.facturar_horas(t, u2, False, x, [a])
    assert [h["id"] for h in fd.horas_sin_facturar(t, x)] == [a]


def test_desde_la_web_se_ven_las_horas_y_se_facturan_con_confirmacion(cliente, ffs):
    uid = iniciar_sesion_de_prueba(cliente, "horasweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho horas web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    db.guardar_facturascripts(t, "http://127.0.0.1:1/", "a", "b"); db.guardar_facturascripts_api_key(t, "k")
    f = crear_cliente_fiscal(t, "Cliente Horas", nif="12345678Z"); db.editar_cliente_fiscal(t, f, facturascripts_cliente_codigo="C7")
    c = nucleo.listar_clientes(t, limite=5)[0][0]["id"]
    x = nucleo.crear_expediente(t, uid, c, "Expediente horas")
    a, b = _partes(t, uid, x, (60, 120, True), (45, None, True))
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert "Horas sin facturar" in html and "120.00 €" in html and "Sin tarifa" in html and "Facturar las horas elegidas" in html
    r = cliente.post(f"/expedientes/{x}/facturar-horas", data={"parte_id": [a]})
    assert r.status_code == 302 and "error=" in r.headers["Location"] and ffs.facturas == [], "sin confirmar no se emite"
    r = cliente.post(f"/expedientes/{x}/facturar-horas", data={"parte_id": [a], "confirmo": "1"})
    assert r.status_code == 302 and "error=" not in r.headers["Location"] and len(ffs.facturas) == 1
    r = cliente.post(f"/expedientes/{x}/facturar-horas", data={"parte_id": [a], "confirmo": "1"})
    assert "error=" in r.headers["Location"] and len(ffs.facturas) == 1
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert "Horas (1 partes" in html or "Horas (1 parte" in html
