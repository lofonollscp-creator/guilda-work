"""Comprobación automática de cadena y revocación de certificados (app/certificados_verificacion.py). PKI ficticia generada en el test; ninguna consulta sale a Internet."""
import socket
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509 import ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

from app import certificados as ce, certificados_verificacion as cv, db

AHORA = datetime.now(timezone.utc)


def _nombre(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _clave():
    return ec.generate_private_key(ec.SECP256R1())


def _cert(sujeto, clave_publica, emisor_nombre, clave_emisor, *, ca=False, serie=None, valido_desde=None, valido_hasta=None, ocsp_url=None, crl_url=None, emisor_url=None):
    b = (x509.CertificateBuilder().subject_name(_nombre(sujeto)).issuer_name(emisor_nombre).public_key(clave_publica).serial_number(serie or x509.random_serial_number())
         .not_valid_before(valido_desde or AHORA - timedelta(days=30)).not_valid_after(valido_hasta or AHORA + timedelta(days=300))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    acceso = []
    if ocsp_url:
        acceso.append(x509.AccessDescription(AuthorityInformationAccessOID.OCSP, x509.UniformResourceIdentifier(ocsp_url)))
    if emisor_url:
        acceso.append(x509.AccessDescription(AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier(emisor_url)))
    if acceso:
        b = b.add_extension(x509.AuthorityInformationAccess(acceso), critical=False)
    if crl_url:
        b = b.add_extension(x509.CRLDistributionPoints([x509.DistributionPoint([x509.UniformResourceIdentifier(crl_url)], None, None, None)]), critical=False)
    return b.sign(clave_emisor, hashes.SHA256())


class Pki:
    def __init__(self, ocsp_url="http://ocsp.pki.test/r", crl_url="http://crl.pki.test/c.crl", emisor_url="http://pki.test/ca.cer"):
        self.k_raiz, self.k_int, self.k_hoja = _clave(), _clave(), _clave()
        self.raiz = _cert("Raíz Ficticia", self.k_raiz.public_key(), _nombre("Raíz Ficticia"), self.k_raiz, ca=True)
        self.inter = _cert("Intermedia Ficticia", self.k_int.public_key(), self.raiz.subject, self.k_raiz, ca=True)
        self.hoja = _cert("Titular Ficticio", self.k_hoja.public_key(), self.inter.subject, self.k_int, serie=4242, ocsp_url=ocsp_url, crl_url=crl_url, emisor_url=emisor_url)
        self.hoja_der = self.hoja.public_bytes(serialization.Encoding.DER)

    def ocsp(self, estado="good", firmante=None, k_firmante=None, serie=None, next_update=None, hoja=None):
        hoja = hoja or self.hoja
        b = ocsp.OCSPResponseBuilder()
        kw = {"revocation_time": AHORA - timedelta(days=2), "revocation_reason": x509.ReasonFlags.key_compromise} if estado == "revoked" else {"revocation_time": None, "revocation_reason": None}
        st = {"good": ocsp.OCSPCertStatus.GOOD, "revoked": ocsp.OCSPCertStatus.REVOKED, "unknown": ocsp.OCSPCertStatus.UNKNOWN}[estado]
        b = b.add_response(cert=hoja, issuer=self.inter, algorithm=hashes.SHA1(), cert_status=st, this_update=AHORA - timedelta(minutes=5), next_update=next_update or AHORA + timedelta(days=1), **kw)
        b = b.responder_id(ocsp.OCSPResponderEncoding.HASH, firmante or self.inter)
        return b.sign(k_firmante or self.k_int, hashes.SHA256()).public_bytes(serialization.Encoding.DER)

    def crl(self, revocados=(), firmante=None, next_update=None):
        ultima = (next_update - timedelta(days=3)) if next_update else AHORA - timedelta(hours=1)
        b = x509.CertificateRevocationListBuilder().issuer_name(self.inter.subject).last_update(ultima).next_update(next_update or AHORA + timedelta(days=3))
        for s in revocados:
            b = b.add_revoked_certificate(x509.RevokedCertificateBuilder().serial_number(s).revocation_date(AHORA - timedelta(days=1)).build())
        return b.sign(firmante or self.k_int, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


def _red(respuestas):
    """Un `descargar` falso: URL -> bytes (o una excepción)."""
    def f(url, **kw):
        r = respuestas.get(url)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise cv.ErrorDescarga("El servidor respondió 404.")
        return r
    return f


# --- Cadena ----------------------------------------------------------------------------------------------------------------------------------------

def test_la_cadena_se_completa_bajando_el_emisor_de_su_direccion_aia():
    p = Pki()
    red = _red({"http://pki.test/ca.cer": p.inter.public_bytes(serialization.Encoding.DER)})
    r, d = cv.comprobar_cadena(p.hoja, [], [p.raiz], descargar_fn=red)
    assert r == "valida" and "3 certificado(s)" in d


def test_cadena_con_intermedio_conocido_y_raiz_de_confianza():
    p = Pki()
    r, d = cv.comprobar_cadena(p.hoja, [p.inter], [p.raiz], descargar_fn=_red({}))
    assert r == "valida" and "Raíz Ficticia" in d


def test_raiz_que_no_esta_en_el_almacen_es_indeterminada_no_valida():
    p = Pki()
    r, d = cv.comprobar_cadena(p.hoja, [p.inter, p.raiz], [], descargar_fn=_red({}))
    assert r == "indeterminada" and "almacén de confianza" in d


def test_sin_poder_obtener_el_emisor_es_indeterminada():
    p = Pki()
    r, d = cv.comprobar_cadena(p.hoja, [], [p.raiz], descargar_fn=_red({"http://pki.test/ca.cer": cv.ErrorDescarga("No se pudo conectar: OSError.")}))
    assert r == "indeterminada" and "No se pudo obtener el certificado del emisor" in d


def test_un_emisor_que_no_es_ca_o_esta_caducado_invalida_la_cadena():
    p = Pki()
    k = _clave()
    no_ca = _cert("Intermedia Ficticia", p.k_int.public_key(), p.raiz.subject, p.k_raiz, ca=False)
    hoja = _cert("Titular", k.public_key(), no_ca.subject, p.k_int)
    assert cv.comprobar_cadena(hoja, [no_ca], [p.raiz], descargar_fn=_red({}))[0] == "invalida"
    caducada = _cert("Intermedia Ficticia", p.k_int.public_key(), p.raiz.subject, p.k_raiz, ca=True, valido_desde=AHORA - timedelta(days=400), valido_hasta=AHORA - timedelta(days=10))
    hoja2 = _cert("Titular", k.public_key(), caducada.subject, p.k_int)
    r, d = cv.comprobar_cadena(hoja2, [caducada], [p.raiz], descargar_fn=_red({}))
    assert r == "invalida" and "no está vigente" in d


def test_una_firma_que_no_cuadra_no_construye_cadena():
    p, otra = Pki(), Pki()
    # hoja de «otra» PKI presentada con el intermedio de p: el nombre del emisor coincide pero la firma no
    r, _ = cv.comprobar_cadena(otra.hoja, [p.inter], [p.raiz], descargar_fn=_red({}))
    assert r == "indeterminada"


# --- Revocación: OCSP ------------------------------------------------------------------------------------------------------------------------------

def test_ocsp_bueno_revocado_y_desconocido():
    p = Pki()
    assert cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": p.ocsp("good")}))[0] == "no_revocado_en_comprobacion"
    r, d = cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": p.ocsp("revoked")}))
    assert r == "revocado" and "key_compromise" in d
    assert cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": p.ocsp("unknown")}))[0] == "indeterminada"


def test_una_respuesta_ocsp_firmada_por_un_extraño_se_descarta():
    p = Pki()
    k_intruso = _clave()
    intruso = _cert("Intruso", k_intruso.public_key(), _nombre("Intruso"), k_intruso)           # certificado propio, que el emisor no ha firmado
    b = (ocsp.OCSPResponseBuilder().add_response(cert=p.hoja, issuer=p.inter, algorithm=hashes.SHA1(), cert_status=ocsp.OCSPCertStatus.GOOD, this_update=AHORA - timedelta(minutes=1),
                                                 next_update=AHORA + timedelta(days=1), revocation_time=None, revocation_reason=None)
         .responder_id(ocsp.OCSPResponderEncoding.NAME, intruso).certificates([intruso]))
    falsa = b.sign(k_intruso, hashes.SHA256()).public_bytes(serialization.Encoding.DER)
    r, d = cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": falsa}))
    assert r == "indeterminada" and "descarta" in d


def test_ocsp_caducado_basura_o_de_otro_certificado_no_valen():
    p = Pki()
    assert cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": p.ocsp("good", next_update=AHORA - timedelta(hours=1))}))[1].startswith("La respuesta OCSP está caducada")
    assert cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": b"no es ocsp"}))[0] == "indeterminada"
    otra_hoja = _cert("Otro", _clave().public_key(), p.inter.subject, p.k_int, serie=999)
    r, d = cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": p.ocsp("good", hoja=otra_hoja)}))
    assert r == "indeterminada" and "otro certificado" in d


def test_ocsp_con_responder_delegado_firmado_por_el_emisor():
    p = Pki()
    k_del = _clave()
    delegado = _cert("Respondedor OCSP", k_del.public_key(), p.inter.subject, p.k_int)
    b = (ocsp.OCSPResponseBuilder().add_response(cert=p.hoja, issuer=p.inter, algorithm=hashes.SHA1(), cert_status=ocsp.OCSPCertStatus.GOOD, this_update=AHORA - timedelta(minutes=1),
                                                 next_update=AHORA + timedelta(days=1), revocation_time=None, revocation_reason=None)
         .responder_id(ocsp.OCSPResponderEncoding.NAME, delegado).certificates([delegado]))
    resp = b.sign(k_del, hashes.SHA256()).public_bytes(serialization.Encoding.DER)
    assert cv.comprobar_ocsp(p.hoja, p.inter, descargar_fn=_red({"http://ocsp.pki.test/r": resp}))[0] == "no_revocado_en_comprobacion"


# --- Revocación: CRL y combinación ----------------------------------------------------------------------------------------------------------------

def test_crl_con_y_sin_el_certificado_y_firma_ajena():
    p = Pki()
    assert cv.comprobar_crl(p.hoja, p.inter, descargar_fn=_red({"http://crl.pki.test/c.crl": p.crl()}))[0] == "no_revocado_en_comprobacion"
    r, d = cv.comprobar_crl(p.hoja, p.inter, descargar_fn=_red({"http://crl.pki.test/c.crl": p.crl([4242])}))
    assert r == "revocado" and "CRL" in d
    assert cv.comprobar_crl(p.hoja, p.inter, descargar_fn=_red({"http://crl.pki.test/c.crl": p.crl(firmante=_clave())}))[0] == "indeterminada"
    assert cv.comprobar_crl(p.hoja, p.inter, descargar_fn=_red({"http://crl.pki.test/c.crl": p.crl(next_update=AHORA - timedelta(days=1))}))[1].startswith("La lista de revocación está caducada")


def test_si_ocsp_falla_se_usa_la_crl_y_si_ambas_fallan_es_indeterminada():
    p = Pki()
    red = _red({"http://ocsp.pki.test/r": cv.ErrorDescarga("sin red"), "http://crl.pki.test/c.crl": p.crl([4242])})
    r, d, metodo = cv.comprobar_revocacion(p.hoja, p.inter, descargar_fn=red)
    assert (r, metodo) == ("revocado", "crl")
    r, d, metodo = cv.comprobar_revocacion(p.hoja, p.inter, descargar_fn=_red({}))
    assert r == "indeterminada" and metodo == "ocsp+crl"
    assert cv.comprobar_revocacion(p.hoja, None, descargar_fn=_red({}))[0] == "indeterminada"


def test_un_certificado_sin_direcciones_de_consulta_es_indeterminado():
    p = Pki(ocsp_url=None, crl_url=None, emisor_url=None)
    assert cv.comprobar_ocsp(p.hoja, p.inter)[1] == "El certificado no publica dirección OCSP."
    assert "no publica lista" in cv.comprobar_crl(p.hoja, p.inter)[1]


def test_verificar_de_extremo_a_extremo():
    p = Pki()
    red = _red({"http://pki.test/ca.cer": p.inter.public_bytes(serialization.Encoding.DER), "http://ocsp.pki.test/r": p.ocsp("good")})
    r = cv.verificar(p.hoja_der, [p.inter], [p.raiz], descargar_fn=red)
    assert r["cadena"][0] == "valida" and r["revocacion"][0] == "no_revocado_en_comprobacion" and r["revocacion"][2] == "ocsp"


# --- Descarga segura (SSRF) ------------------------------------------------------------------------------------------------------------------------

def _dns(tabla):
    def r(host, puerto, type=None):
        if host not in tabla:
            raise socket.gaierror("no existe")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, puerto)) for ip in tabla[host]]
    return r


@pytest.mark.parametrize("url,fragmento", [
    ("file:///etc/passwd", "http o https"), ("ftp://x.test/a", "http o https"), ("gopher://x.test", "http o https"),
    ("http://user:pass@pub.test/a", "no válida"), ("http:///a", "no válida"),
    ("http://pub.test:22/a", "Puerto"), ("http://pub.test:6379/", "Puerto"),
    ("http://local.test/a", "no pública"), ("http://metadatos.test/latest", "no pública"), ("http://red.test/a", "no pública"), ("http://doble.test/a", "no pública"), ("http://ipv6.test/a", "no pública"),
    ("http://noexiste.test/a", "resolver")])
def test_destinos_peligrosos_se_rechazan(url, fragmento):
    dns = _dns({"pub.test": ["93.184.216.34"], "local.test": ["127.0.0.1"], "metadatos.test": ["169.254.169.254"], "red.test": ["10.0.0.5"],
                "doble.test": ["93.184.216.34", "192.168.1.10"], "ipv6.test": ["::1"]})
    with pytest.raises(cv.ErrorDescarga, match=fragmento):
        cv._destino_seguro(url, dns)


def test_un_destino_publico_se_acepta_y_se_conecta_a_la_ip_comprobada():
    esquema, host, puerto, ruta, ip = cv._destino_seguro("http://pub.test/crl/a.crl?x=1", _dns({"pub.test": ["93.184.216.34"]}))
    assert (esquema, host, puerto, ruta, ip) == ("http", "pub.test", 80, "/crl/a.crl?x=1", "93.184.216.34")
    assert cv._destino_seguro("https://pub.test:8443", _dns({"pub.test": ["93.184.216.34"]}))[2:4] == (8443, "/")


def test_descargar_revalida_cada_redireccion(monkeypatch):
    """Un servidor público que redirige a 127.0.0.1 (o a los metadatos de la nube) no consigue que el servidor consulte su red interna."""
    dns = _dns({"pub.test": ["93.184.216.34"], "interno.test": ["127.0.0.1"]})
    conexiones = []

    class Resp:
        status = 302
        def getheader(self, n): return "http://interno.test/secreto"
        def read(self, n=None): return b""

    class Conn:
        def __init__(self, *a, **k): self.sock = None
        def request(self, *a, **k): pass
        def getresponse(self): return Resp()
        def close(self): pass

    monkeypatch.setattr(cv.socket, "create_connection", lambda dest, timeout=None: conexiones.append(dest) or object())
    monkeypatch.setattr(cv.http.client, "HTTPConnection", Conn)
    with pytest.raises(cv.ErrorDescarga, match="no pública"):
        cv.descargar("http://pub.test/a", resolver=dns)
    assert conexiones == [("93.184.216.34", 80)]            # solo se llegó a conectar al destino público


def test_descargar_limita_respuestas_y_acepta_solo_200(monkeypatch):
    dns = _dns({"pub.test": ["93.184.216.34"]})

    def instalar(status, cuerpo):
        class Resp:
            def __init__(self): self.status = status
            def getheader(self, n): return None
            def read(self, n=None): return cuerpo[: (n or len(cuerpo))]
        class Conn:
            def __init__(self, *a, **k): self.sock = None
            def request(self, *a, **k): pass
            def getresponse(self): return Resp()
            def close(self): pass
        monkeypatch.setattr(cv.socket, "create_connection", lambda dest, timeout=None: object())
        monkeypatch.setattr(cv.http.client, "HTTPConnection", Conn)
    instalar(200, b"ok")
    assert cv.descargar("http://pub.test/a", resolver=dns) == b"ok"
    instalar(404, b"")
    with pytest.raises(cv.ErrorDescarga, match="404"):
        cv.descargar("http://pub.test/a", resolver=dns)
    instalar(200, b"x" * (cv.MAX_BYTES + 5))
    with pytest.raises(cv.ErrorDescarga, match="demasiado grande"):
        cv.descargar("http://pub.test/a", resolver=dns)


# --- Integración con certificados.py ---------------------------------------------------------------------------------------------------------------

def _despacho_con_certificado():
    t = db.crear_tenant("Despacho verificación")
    u = db.crear_usuario_vinculado_a_kratos("ver-cert@ejemplo.com", "k-ver-cert")
    db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(u, True)
    p = Pki()
    r = ce.importar(t, u, p.hoja_der)
    return t, u, p, r["id"]


def test_comprobar_ahora_anota_las_dos_evaluaciones_como_automaticas(monkeypatch):
    t, u, p, cid = _despacho_con_certificado()
    res = ce.comprobar_ahora(t, u, cid, verificar=lambda der: {"cadena": ("valida", "ok"), "revocacion": ("revocado", "OCSP: revocado.", "ocsp")})
    assert res == {"cadena": "valida", "revocacion": "revocado"}
    conn = db.get_connection()
    filas = conn.execute("SELECT dimension, resultado, metodo, detalle FROM certificados_evaluaciones WHERE certificado_id = ? ORDER BY id", (cid,)).fetchall()
    conn.close()
    assert [(f["dimension"], f["resultado"], f["metodo"]) for f in filas] == [("cadena", "valida", "automatica"), ("revocacion", "revocado", "ocsp")]


def test_un_fallo_inesperado_se_anota_como_indeterminada_y_nunca_como_valida(monkeypatch):
    t, u, p, cid = _despacho_con_certificado()
    def revienta(der): raise RuntimeError("fallo raro")
    assert ce.comprobar_ahora(t, u, cid, verificar=revienta) == {"cadena": "indeterminada", "revocacion": "indeterminada"}


def test_un_certificado_dado_de_alta_a_mano_no_se_puede_comprobar(monkeypatch):
    t, u, p, cid = _despacho_con_certificado()
    conn = db.get_connection(); conn.execute("UPDATE certificados SET der = NULL WHERE id = ?", (cid,)); conn.commit(); conn.close()
    with pytest.raises(ValueError, match="dio de alta a mano"):
        ce.comprobar_ahora(t, u, cid)
    with pytest.raises(ValueError, match="No existe"):
        ce.comprobar_ahora(t, u, 99999)


def test_el_boton_de_la_ficha_comprueba_y_muestra_el_resultado(cliente, monkeypatch):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "ver-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho verificación web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    db.crear_cliente_fiscal(t, "Cliente SL")                       # sin Gestoría activa el módulo no existe
    p = Pki()
    cid = ce.importar(t, uid, p.hoja_der)["id"]
    monkeypatch.setattr(cv, "verificar", lambda der: {"cadena": ("valida", "Cadena de 3 certificado(s)."), "revocacion": ("no_revocado_en_comprobacion", "OCSP: sin revocar.", "ocsp")})
    html = cliente.get(f"/certificados/{cid}").get_data(as_text=True)
    assert "Comprobar ahora la cadena y la revocación" in html and f"/certificados/{cid}/comprobar" in html
    r = cliente.post(f"/certificados/{cid}/comprobar")
    assert r.status_code == 302 and "aviso=comprobado" in r.headers["Location"]
    html = cliente.get(r.headers["Location"]).get_data(as_text=True)
    assert "Cadena de 3 certificado(s)." in html and "OCSP: sin revocar." in html and "Comprobación hecha" in html
