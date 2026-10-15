"""Correo C6: consultas DNS mínimas (app/dns_simple.py) y diagnóstico del dominio de correo (app/correo_dominio.py). Dominios ficticios; ninguna consulta sale a Internet."""
import socket
import struct
import threading

import pytest

from app import correo_dominio as cd, db, dns_simple
from tests.conftest import iniciar_sesion_de_prueba


# --- Protocolo DNS -------------------------------------------------------------------------------------------------------------------------------

def _nombre(n: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\x00"


def _respuesta(consulta: bytes, rrs: list[tuple[int, bytes]], rcode=0, truncada=False) -> bytes:
    ident = consulta[:2]
    flags = 0x8180 | rcode | (0x0200 if truncada else 0)
    pregunta = consulta[12:]
    cuerpo = b"".join(b"\xc0\x0c" + struct.pack("!HHIH", tipo, 1, 60, len(rd)) + rd for tipo, rd in rrs)
    return ident + struct.pack("!HHHHH", flags, 1, len(rrs), 0, 0) + pregunta + cuerpo


def _txt(texto: str, trozo: int = 255) -> bytes:
    b = texto.encode()
    return b"".join(bytes([len(b[i:i + trozo])]) + b[i:i + trozo] for i in range(0, len(b), trozo))


def test_la_consulta_lleva_la_pregunta_bien_formada():
    q = dns_simple.construir_consulta("ejemplo.test", "TXT", ident=7)
    assert q[:2] == b"\x00\x07" and q[12:] == _nombre("ejemplo.test") + struct.pack("!HH", 16, 1)
    with pytest.raises(dns_simple.ErrorDNS):
        dns_simple.construir_consulta("a" * 70 + ".test", "TXT")


def test_interpretar_txt_con_trozos_y_mx_con_compresion():
    q = dns_simple.construir_consulta("ejemplo.test", "TXT", ident=1)
    r = dns_simple.interpretar_respuesta(_respuesta(q, [(16, _txt("v=spf1 " + "x" * 300 + " ~all", 100))]), 1)
    assert r["respuestas"][0]["valor"] == "v=spf1 " + "x" * 300 + " ~all"
    qm = dns_simple.construir_consulta("ejemplo.test", "MX", ident=2)
    r = dns_simple.interpretar_respuesta(_respuesta(qm, [(15, struct.pack("!H", 10) + b"\x04mail\xc0\x0c")]), 2)
    assert r["respuestas"] == [{"tipo": "MX", "valor": (10, "mail.ejemplo.test")}]


def test_respuestas_rotas_o_ajenas_se_rechazan():
    q = dns_simple.construir_consulta("ejemplo.test", "TXT", ident=3)
    ok = _respuesta(q, [(16, _txt("hola"))])
    with pytest.raises(dns_simple.ErrorDNS, match="no corresponde"):
        dns_simple.interpretar_respuesta(ok, 99)
    with pytest.raises(dns_simple.ErrorDNS):
        dns_simple.interpretar_respuesta(ok[:20], 3)
    with pytest.raises(dns_simple.ErrorDNS):
        dns_simple.interpretar_respuesta(b"", None)
    with pytest.raises(dns_simple.ErrorDNS, match="bucle"):
        dns_simple.interpretar_respuesta(q[:2] + struct.pack("!HHHHH", 0x8180, 1, 0, 0, 0) + b"\xc0\x0c" + b"\x00\x10\x00\x01", None)


@pytest.fixture
def servidor_dns():
    """Un servidor DNS UDP de juguete en localhost que contesta con lo que se le configure por nombre."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 0)); s.settimeout(0.2)
    datos = {"respuestas": {}, "rcode": 0}
    parar = threading.Event()

    def bucle():
        while not parar.is_set():
            try:
                q, dire = s.recvfrom(512)
            except socket.timeout:
                continue
            tipo = struct.unpack("!H", q[-4:-2])[0]
            nombre = ".".join(p.decode() for p in _partir(q[12:-4]))
            s.sendto(_respuesta(q, datos["respuestas"].get((nombre, tipo), []), rcode=datos["rcode"]), dire)
    t = threading.Thread(target=bucle, daemon=True); t.start()
    yield s.getsockname()[1], datos
    parar.set(); t.join(); s.close()


def _partir(b: bytes):
    i = 0
    while b[i]:
        yield b[i + 1:i + 1 + b[i]]; i += 1 + b[i]


def test_resolver_contra_un_servidor_real_en_localhost(servidor_dns):
    puerto, datos = servidor_dns
    datos["respuestas"][("ejemplo.test", 16)] = [(16, _txt("v=spf1 mx ~all")), (16, _txt("otro"))]
    datos["respuestas"][("ejemplo.test", 15)] = [(15, struct.pack("!H", 20) + _nombre("b.ejemplo.test")), (15, struct.pack("!H", 10) + _nombre("a.ejemplo.test"))]
    assert sorted(dns_simple.resolver("ejemplo.test", "TXT", ["127.0.0.1"], puerto=puerto)) == ["otro", "v=spf1 mx ~all"]
    assert dns_simple.resolver("ejemplo.test", "MX", ["127.0.0.1"], puerto=puerto) == [(10, "a.ejemplo.test"), (20, "b.ejemplo.test")]
    assert dns_simple.resolver("no-existe.test", "TXT", ["127.0.0.1"], puerto=puerto) == []
    datos["rcode"] = 2
    with pytest.raises(dns_simple.ErrorDNS, match="error 2"):
        dns_simple.resolver("ejemplo.test", "TXT", ["127.0.0.1"], puerto=puerto)


def test_sin_servidores_no_se_puede_consultar():
    with pytest.raises(dns_simple.ErrorDNS, match="No hay servidores"):
        dns_simple.resolver("ejemplo.test", "TXT", [])
    assert dns_simple.servidores_del_sistema("/ruta/que/no/existe") == []


# --- Diagnóstico ---------------------------------------------------------------------------------------------------------------------------------

def _dns(tabla):
    return lambda nombre, tipo: tabla.get((nombre, tipo), [])


BUENO = {("d.test", "MX"): [(10, "mx.d.test")], ("d.test", "TXT"): ["v=spf1 mx include:_spf.p.test ~all"],
         ("rsa._domainkey.d.test", "TXT"): ["v=DKIM1; k=rsa; p=MIIBIjANBg"], ("_dmarc.d.test", "TXT"): ["v=DMARC1; p=quarantine; rua=mailto:x@d.test"]}


def test_un_dominio_bien_configurado_sale_correcto():
    r = cd.diagnosticar("D.test", consulta=_dns(BUENO))
    assert r["estado"] == "ok" and [c["estado"] for c in r["comprobaciones"]] == ["ok"] * 4 and [c["clave"] for c in r["comprobaciones"]] == ["mx", "spf", "dkim", "dmarc"]


def test_un_dominio_sin_nada_falla_y_dice_que_falta():
    r = cd.diagnosticar("vacio.test", consulta=_dns({}))
    estados = {c["clave"]: c["estado"] for c in r["comprobaciones"]}
    assert r["estado"] == "error" and estados == {"mx": "error", "spf": "error", "dkim": "aviso", "dmarc": "error"}


@pytest.mark.parametrize("spf,estado", [("v=spf1 mx ~all", "ok"), ("v=spf1 mx -all", "ok"), ("v=spf1 redirect=_spf.p.test", "ok"), ("v=spf1 mx +all", "aviso"), ("v=spf1 mx ?all", "aviso"), ("v=spf1 mx", "aviso")])
def test_casos_de_spf(spf, estado):
    assert cd.comprobar_spf("d.test", _dns({("d.test", "TXT"): [spf]}))["estado"] == estado


def test_dos_spf_y_demasiadas_consultas():
    assert cd.comprobar_spf("d.test", _dns({("d.test", "TXT"): ["v=spf1 mx ~all", "v=spf1 a ~all"]}))["estado"] == "error"
    muchos = "v=spf1 " + " ".join(f"include:i{n}.p.test" for n in range(11)) + " ~all"
    assert cd.comprobar_spf("d.test", _dns({("d.test", "TXT"): [muchos]}))["estado"] == "aviso"


@pytest.mark.parametrize("dmarc,estado", [("v=DMARC1; p=reject", "ok"), ("v=DMARC1; p=quarantine", "ok"), ("v=DMARC1; p=none", "aviso"), ("v=DMARC1; p=otra", "aviso"), ("v=DMARC1", "aviso")])
def test_casos_de_dmarc(dmarc, estado):
    assert cd.comprobar_dmarc("d.test", _dns({("_dmarc.d.test", "TXT"): [dmarc]}))["estado"] == estado


def test_dkim_con_selector_propio():
    tabla = {("mio._domainkey.d.test", "TXT"): ["v=DKIM1; p=ABC"]}
    assert cd.comprobar_dkim("d.test", _dns(tabla), "mio")["estado"] == "ok"
    assert cd.comprobar_dkim("d.test", _dns(tabla), "otro")["estado"] == "error"
    assert cd.comprobar_dkim("d.test", _dns(tabla))["estado"] == "aviso"          # sin selector solo se prueban los habituales


@pytest.mark.parametrize("dominio", ["", "sin-punto", "a b.test", "-x.test", "x..test", "http://x.test", "x.t"])
def test_dominios_y_selectores_no_validos(dominio):
    with pytest.raises(ValueError, match="no es válido"):
        cd.diagnosticar(dominio, consulta=_dns({}))
    assert cd.dominio_valido("mi-dominio.example.com") and not cd.dominio_valido(dominio)
    with pytest.raises(ValueError, match="selector"):
        cd.diagnosticar("d.test", "mal selector!", consulta=_dns({}))


# --- Pantalla ------------------------------------------------------------------------------------------------------------------------------------

def test_solo_se_diagnostican_los_dominios_propios_y_la_pantalla_lo_enseña(cliente, monkeypatch):
    uid = iniciar_sesion_de_prueba(cliente, "dom-1@ejemplo.com", "contrasena123")
    db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@d.test")
    assert cd.dominios_de_la_persona(uid) == ["d.test"]
    llamadas = []
    monkeypatch.setattr(dns_simple, "resolver", lambda n, t: llamadas.append((n, t)) or BUENO.get((n, t), []))
    assert cliente.get("/correo/cuentas/dominio?dominio=ajeno.test").status_code == 404 and llamadas == []
    html = cliente.get("/correo/cuentas/dominio?dominio=d.test").get_data(as_text=True)
    assert "Salud del dominio de correo" in html and "SPF (quién puede enviar)" in html and "dominio-ok" in html and "dominio-error" not in html
    assert "Salud del dominio" in cliente.get("/correo/cuentas").get_data(as_text=True)
    assert "no es válido" in cliente.get("/correo/cuentas/dominio?dominio=d.test&selector=mal selector!").get_data(as_text=True)


def test_si_el_dns_no_responde_se_avisa(cliente, monkeypatch):
    uid = iniciar_sesion_de_prueba(cliente, "dom-2@ejemplo.com", "contrasena123")
    db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@d.test")
    def cae(n, t): raise dns_simple.ErrorDNS("sin red")
    monkeypatch.setattr(dns_simple, "resolver", cae)
    assert "No se ha podido consultar el DNS" in cliente.get("/correo/cuentas/dominio?dominio=d.test").get_data(as_text=True)


def test_sin_dominios_la_seccion_no_aparece(cliente):
    iniciar_sesion_de_prueba(cliente, "dom-3@ejemplo.com", "contrasena123")
    assert "Salud del dominio" not in cliente.get("/correo/cuentas").get_data(as_text=True)
