"""Alta de un buzón del despacho en un solo paso (app/correo_buzones.py, app/stalwart.py:crear_buzon). Stalwart y el servidor IMAP se simulan: aquí no se crea ninguna cuenta real."""
import pytest

from app import acceso, correo, correo_buzones as cb, db, stalwart
from app.correo import ErrorCorreo
from tests.conftest import iniciar_sesion_de_prueba


class _Jmap:
    """Un Stalwart de juguete: guarda las llamadas y contesta como el real (ids y secreto generados)."""
    def __init__(self, falla_en=None):
        self.llamadas, self.falla_en = [], falla_en

    def __call__(self, calls, *, cabeceras):
        out = []
        for nombre, args, ident in calls:
            self.llamadas.append((nombre, args))
            if nombre == self.falla_en:
                out.append(["error", {"description": "forbidden"}, ident]); continue
            if nombre == "x:Account/set" and "create" in args:
                out.append([nombre, {"created": {"u1": {"id": "acc42"}}}, ident])
            elif nombre == "x:AppPassword/set":
                out.append([nombre, {"created": {"k1": {"id": "k1", "secret": "SECRETO-DE-APLICACION"}}}, ident])
            else:
                out.append([nombre, {"destroyed": args.get("destroy", [])}, ident])
        return {"methodResponses": out}


@pytest.fixture
def stal(monkeypatch):
    j = _Jmap()
    monkeypatch.setattr(stalwart, "_jmap", j)
    monkeypatch.setattr(stalwart, "STALWART_ADMIN_USER", "admin"); monkeypatch.setattr(stalwart, "STALWART_ADMIN_PASSWORD", "x")
    return j


def _despacho(cliente, email, con_dominio=True, directivo=True, monkeypatch=None):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email); db.asignar_tenant(uid, t)
    if con_dominio:
        db.guardar_stalwart(t, "st-t1", "dom1", "despacho.test", "acc0", "API_x")
    if monkeypatch is not None:
        monkeypatch.setattr(acceso, "es_directivo", lambda u: directivo)
    return uid, t


def test_crear_buzon_en_stalwart_pide_cuenta_y_contrasena_de_aplicacion(stal):
    r = stalwart.crear_buzon("st-t1", "dom1", "marta", "Guilda Work — marta@despacho.test")
    assert r == {"account_id": "acc42", "secreto": "SECRETO-DE-APLICACION"}
    cuenta = stal.llamadas[0][1]["create"]["u1"]
    assert cuenta["name"] == "marta" and cuenta["domainId"] == "dom1" and cuenta["memberTenantId"] == "st-t1" and cuenta["@type"] == "User"
    assert stal.llamadas[1][0] == "x:AppPassword/set" and stal.llamadas[1][1]["accountId"] == "acc42"


def test_si_falla_la_contrasena_se_borra_la_cuenta_creada(monkeypatch):
    j = _Jmap(falla_en="x:AppPassword/set")
    monkeypatch.setattr(stalwart, "_jmap", j); monkeypatch.setattr(stalwart, "STALWART_ADMIN_USER", "a"); monkeypatch.setattr(stalwart, "STALWART_ADMIN_PASSWORD", "b")
    with pytest.raises(stalwart.ErrorStalwart):
        stalwart.crear_buzon("t", "d", "marta", "x")
    assert j.llamadas[-1] == ("x:Account/set", {"accountId": "b", "destroy": ["acc42"]})


def test_si_stalwart_rechaza_la_cuenta_no_se_intenta_nada_mas(monkeypatch):
    j = _Jmap(falla_en="x:Account/set")
    monkeypatch.setattr(stalwart, "_jmap", j); monkeypatch.setattr(stalwart, "STALWART_ADMIN_USER", "a"); monkeypatch.setattr(stalwart, "STALWART_ADMIN_PASSWORD", "b")
    with pytest.raises(stalwart.ErrorStalwart):
        stalwart.crear_buzon("t", "d", "marta", "x")
    assert [c[0] for c in j.llamadas] == ["x:Account/set"]


def test_eliminar_buzon_no_falla_sin_stalwart_ni_sin_id(monkeypatch):
    monkeypatch.setattr(stalwart, "STALWART_ADMIN_USER", None)
    stalwart.eliminar_buzon("acc1"); stalwart.eliminar_buzon(None)


@pytest.mark.parametrize("local", ["", "Mar ta", "a@b", "-x", "x-", "a" * 70, "ñu", "a/b"])
def test_nombres_de_buzon_no_validos(cliente, stal, monkeypatch, local):
    uid, t = _despacho(cliente, f"buz-n{abs(hash(local))}@ejemplo.com", monkeypatch=monkeypatch)
    monkeypatch.setattr(cb, "dominio_del_despacho", lambda u: {"tenant_id": t, "stalwart_tenant_id": "st-t1", "domain_id": "dom1", "dominio": "despacho.test"})
    with pytest.raises(cb.ErrorBuzon, match="letras, números"):
        cb.alta_buzon(uid, local)
    assert stal.llamadas == []


def test_alta_completa_crea_el_buzon_y_conecta_la_cuenta_de_la_persona(cliente, stal, monkeypatch):
    uid, t = _despacho(cliente, "buz-1@ejemplo.com", monkeypatch=monkeypatch)
    monkeypatch.setattr(cb, "dominio_del_despacho", lambda u: {"tenant_id": t, "stalwart_tenant_id": "st-t1", "domain_id": "dom1", "dominio": "despacho.test"})
    guardadas = []
    monkeypatch.setattr(correo, "guardar_cuenta", lambda persona, nombre, proto, host, puerto, usuario, contrasena, **kw: guardadas.append((persona, nombre, proto, host, puerto, usuario, contrasena, kw)) or 77)
    r = cb.alta_buzon(uid, " Marta ")
    assert r == {"email": "marta@despacho.test", "cuenta_id": 77, "persona_id": uid}
    persona, nombre, proto, host, puerto, usuario, contrasena, kw = guardadas[0]
    assert (persona, nombre, proto, usuario, contrasena) == (uid, "marta@despacho.test", "imap", "marta@despacho.test", "SECRETO-DE-APLICACION")
    assert host == cb.HOST and puerto == cb.PUERTO_IMAP and kw["smtp_host"] == cb.HOST and kw["smtp_puerto"] == cb.PUERTO_SMTP


def test_si_no_se_puede_conectar_el_buzon_creado_se_borra(cliente, stal, monkeypatch):
    uid, t = _despacho(cliente, "buz-2@ejemplo.com", monkeypatch=monkeypatch)
    monkeypatch.setattr(cb, "dominio_del_despacho", lambda u: {"tenant_id": t, "stalwart_tenant_id": "st-t1", "domain_id": "dom1", "dominio": "despacho.test"})
    def falla(*a, **k): raise ErrorCorreo("no se puede conectar")
    monkeypatch.setattr(correo, "guardar_cuenta", falla)
    with pytest.raises(cb.ErrorBuzon, match="se ha deshecho"):
        cb.alta_buzon(uid, "marta")
    assert stal.llamadas[-1] == ("x:Account/set", {"accountId": "b", "destroy": ["acc42"]})


def test_solo_la_direccion_y_solo_con_dominio_propio(cliente, stal, monkeypatch):
    uid, t = _despacho(cliente, "buz-3@ejemplo.com", directivo=False, monkeypatch=monkeypatch)
    monkeypatch.setattr(cb, "dominio_del_despacho", lambda u: {"tenant_id": t, "stalwart_tenant_id": "st-t1", "domain_id": "dom1", "dominio": "despacho.test"})
    with pytest.raises(cb.ErrorBuzon, match="dirección"):
        cb.alta_buzon(uid, "marta")
    monkeypatch.setattr(cb, "dominio_del_despacho", lambda u: None)
    monkeypatch.setattr(acceso, "es_directivo", lambda u: True)
    with pytest.raises(cb.ErrorBuzon, match="dominio de correo propio"):
        cb.alta_buzon(uid, "marta")
    assert stal.llamadas == []


def test_no_se_conecta_el_buzon_a_alguien_de_otro_despacho(cliente, stal, monkeypatch):
    uid, t = _despacho(cliente, "buz-4@ejemplo.com", monkeypatch=monkeypatch)
    monkeypatch.setattr(cb, "dominio_del_despacho", lambda u: {"tenant_id": t, "stalwart_tenant_id": "st-t1", "domain_id": "dom1", "dominio": "despacho.test"})
    ajeno = db.crear_usuario_vinculado_a_kratos("ajeno-buz@ejemplo.com", "k-ajeno-buz")
    with pytest.raises(cb.ErrorBuzon, match="no es de tu despacho"):
        cb.alta_buzon(uid, "marta", persona_id=ajeno)
    assert stal.llamadas == []


def test_la_pantalla_solo_ofrece_crear_buzones_a_la_direccion_con_dominio(cliente, monkeypatch):
    uid, t = _despacho(cliente, "buz-5@ejemplo.com", con_dominio=False, monkeypatch=monkeypatch)
    assert "Crear un buzón del despacho" not in cliente.get("/correo/cuentas").get_data(as_text=True)         # sin dominio propio
    db.guardar_stalwart(t, "st-t1", "dom1", "despacho.test", "acc0", "API_x")
    html = cliente.get("/correo/cuentas").get_data(as_text=True)
    assert "Crear un buzón del despacho" in html and "@despacho.test" in html and "(tú)" in html
    monkeypatch.setattr(acceso, "es_directivo", lambda u: False)
    assert "Crear un buzón del despacho" not in cliente.get("/correo/cuentas").get_data(as_text=True)
    assert cliente.post("/correo/cuentas/buzon", data={"nombre": "marta"}).status_code == 403


def test_la_ruta_crea_y_avisa_o_muestra_el_error(cliente, stal, monkeypatch):
    uid, t = _despacho(cliente, "buz-6@ejemplo.com", monkeypatch=monkeypatch)
    monkeypatch.setattr(cb, "dominio_del_despacho", lambda u: {"tenant_id": t, "stalwart_tenant_id": "st-t1", "domain_id": "dom1", "dominio": "despacho.test"})
    monkeypatch.setattr(correo, "guardar_cuenta", lambda *a, **k: 5)
    r = cliente.post("/correo/cuentas/buzon", data={"nombre": "marta", "persona_id": str(uid)})
    assert r.status_code == 302 and "aviso=" in r.headers["Location"]
    assert "marta@despacho.test" in cliente.get(r.headers["Location"]).get_data(as_text=True)
    assert "letras, números" in cliente.post("/correo/cuentas/buzon", data={"nombre": "no valido!"}).get_data(as_text=True)
