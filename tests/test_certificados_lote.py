"""Importación de certificados públicos en lote (K4): se revisa primero, se importa solo al confirmar y se enlaza con el cliente por su NIF."""
import io

import pytest

from app import certificados as ce
from app import certificados_lote as lote
from app import db, verticales
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_certificados import _p12, der, hacer_cert, pem


@pytest.fixture
def despacho(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "cert-lote@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho certificados lote")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "gestoria", True)
    return cliente, uid, t


def test_revisar_clasifica_nuevo_duplicado_y_no_valido_y_enlaza_por_nif(despacho):
    _c, uid, t = despacho
    cf = db.crear_cliente_fiscal(t, "Marta Puig", nif="12345678Z")
    marta = pem(hacer_cert(cn="MARTA PUIG", serie_id="IDCES-12345678Z", dias=300, clave=31))
    otro = pem(hacer_cert(cn="OTRA PERSONA", serie_id="IDCES-87654321X", dias=300, clave=32))
    ya_pem = pem(hacer_cert(cn="YA ESTABA", serie_id="IDCES-11111111H", dias=300, clave=33))
    ya = ce.importar(t, uid, ya_pem)["id"]
    filas = lote.revisar(t, uid, [("marta.pem", marta), ("otro.pem", otro), ("repetido.pem", marta), ("ya.pem", ya_pem), ("clave.p12", _p12()), ("vacio.cer", b"")])
    estados = {f["nombre"]: f["estado"] for f in filas}
    assert estados == {"marta.pem": "nuevo", "otro.pem": "nuevo", "repetido.pem": "duplicado", "ya.pem": "duplicado", "clave.p12": "error", "vacio.cer": "error"}
    por_nombre = {f["nombre"]: f for f in filas}
    assert por_nombre["marta.pem"]["cliente"] == {"id": cf, "nombre": "Marta Puig"} and por_nombre["otro.pem"]["cliente"] is None
    assert "clave" in (por_nombre["clave.p12"]["motivo"] or "").lower() or "privad" in (por_nombre["clave.p12"]["motivo"] or "").lower()
    assert [x["id"] for x in ce.listar(t)] == [ya]                                                           # revisar no guarda nada


def test_importar_guarda_solo_los_nuevos_y_los_enlaza(despacho):
    _c, uid, t = despacho
    cf = db.crear_cliente_fiscal(t, "Marta Puig", nif="12345678Z")
    ficheros = [("marta.pem", pem(hacer_cert(cn="MARTA PUIG", serie_id="IDCES-12345678Z", dias=300, clave=41))), ("otro.pem", pem(hacer_cert(cn="OTRA", serie_id="IDCES-87654321X", dias=300, clave=42))), ("roto.cer", b"no es un certificado")]
    r = lote.importar(t, uid, ficheros)
    assert (r["importados"], r["enlazados"], r["saltados"]) == (2, 1, 1) and len(r["errores"]) == 1 and "roto.cer" in r["errores"][0]
    por_titular = {c["sujeto"]: c for c in ce.listar(t)}
    assert any(c["cliente_titular_id"] == cf for c in por_titular.values()) and sum(1 for c in por_titular.values() if c["cliente_titular_id"]) == 1
    assert lote.importar(t, uid, ficheros)["importados"] == 0                                                 # repetir la subida no duplica nada


def test_la_pantalla_revisa_primero_y_importa_al_confirmar(despacho):
    cliente, uid, t = despacho
    db.crear_cliente_fiscal(t, "Marta Puig", nif="12345678Z")
    datos = {"archivos": [(io.BytesIO(pem(hacer_cert(cn="MARTA PUIG", serie_id="IDCES-12345678Z", dias=300, clave=51))), "marta.pem")]}
    r = cliente.post("/certificados/importar-lote", data=datos, content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Nuevo" in html and "Marta Puig" in html and "Importar 1 certificado" in html and not ce.listar(t)
    import re
    b64 = re.search(r'name="contenido_b64" value="([^"]+)"', html).group(1)
    final = cliente.post("/certificados/importar-lote", data={"accion": "importar", "nombre": "marta.pem", "contenido_b64": b64}).get_data(as_text=True)
    assert "Importación terminada" in final and "1 certificado importado" in final and len(ce.listar(t)) == 1
    assert cliente.get("/certificados/importar-lote").status_code == 200 and "Importar en lote" in cliente.get("/certificados/").get_data(as_text=True)
    assert "Elige uno o varios" in cliente.post("/certificados/importar-lote", data={}, content_type="multipart/form-data").get_data(as_text=True)
