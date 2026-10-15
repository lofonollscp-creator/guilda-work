"""Comprobación automática de la cadena y de la revocación de un certificado (los «P1» que la fase B dejó anotados a mano): ¿lo firmó una autoridad en la que confiamos y sigue sin estar
revocado? Usa solo lo que el propio certificado publica (AIA: emisor y OCSP; CDP: lista de revocación) y el almacén de CA del sistema.

**Esas direcciones las escribe quien emitió el certificado, así que se tratan como no fiables**: solo http/https en puertos conocidos, sin credenciales en la URL, y el servidor nunca se
conecta a una dirección que no sea pública (ni 127.0.0.1, ni redes privadas, ni 169.254.x.x de metadatos): se resuelve el nombre, se comprueban **todas** las IP y se conecta a la IP
ya comprobada (no se vuelve a resolver, para que un DNS cambiante no pueda saltarse la comprobación). Respuestas con tope de tamaño, de tiempo y de redirecciones, y cada redirección se revalida.

Resultados con el vocabulario de `certificados.RESULTADOS`: cadena `valida` / `invalida` / `indeterminada`; revocación `no_revocado_en_comprobacion` / `revocado` / `indeterminada`. Un fallo de red,
una respuesta ilegible o una CA que no está en el almacén de confianza dan **«indeterminada», nunca «válida»**: sin pruebas no se afirma nada."""
from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import ssl
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509 import ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

logger = logging.getLogger(__name__)

PUERTOS_PERMITIDOS = (80, 443, 8080, 8443)
MAX_BYTES = 4 * 1024 * 1024
TIMEOUT = 10
MAX_SALTOS = 3
PROFUNDIDAD_MAXIMA = 6
RUTA_CA_SISTEMA = "/etc/ssl/certs/ca-certificates.crt"


class ErrorDescarga(Exception):
    """Mensaje legible de por qué no se pudo obtener algo de una dirección del certificado."""


# --- Descarga segura -------------------------------------------------------------------------------------------------------------------------------

def _destino_seguro(url: str, resolver=socket.getaddrinfo) -> tuple[str, str, int, str, str]:
    """`(esquema, host, puerto, ruta, ip)` de una URL aceptable o `ErrorDescarga`."""
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https"):
        raise ErrorDescarga("Solo se admiten direcciones http o https.")
    if partes.username or partes.password or not partes.hostname:
        raise ErrorDescarga("Dirección no válida.")
    try:
        puerto = partes.port or (443 if partes.scheme == "https" else 80)
    except ValueError:
        raise ErrorDescarga("Dirección no válida.") from None
    if puerto not in PUERTOS_PERMITIDOS:
        raise ErrorDescarga("Puerto no permitido.")
    try:
        direcciones = {r[4][0] for r in resolver(partes.hostname, puerto, type=socket.SOCK_STREAM)}
    except OSError:
        raise ErrorDescarga("No se pudo resolver el nombre del servidor.") from None
    if not direcciones:
        raise ErrorDescarga("No se pudo resolver el nombre del servidor.")
    for d in direcciones:
        ip = ipaddress.ip_address(d.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise ErrorDescarga("La dirección apunta a una red no pública: no se consulta.")
    ruta = partes.path or "/"
    if partes.query:
        ruta += "?" + partes.query
    return partes.scheme, partes.hostname, puerto, ruta, sorted(direcciones)[0]


def descargar(url: str, *, metodo: str = "GET", cuerpo: bytes | None = None, cabeceras: dict | None = None, resolver=socket.getaddrinfo) -> bytes:
    """El cuerpo de la respuesta (200) o `ErrorDescarga`. Sigue hasta `MAX_SALTOS` redirecciones, revalidando cada destino."""
    for _ in range(MAX_SALTOS + 1):
        esquema, host, puerto, ruta, ip = _destino_seguro(url, resolver)
        try:
            sock = socket.create_connection((ip, puerto), timeout=TIMEOUT)
            if esquema == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            conn = http.client.HTTPConnection(host, puerto, timeout=TIMEOUT)
            conn.sock = sock
            conn.request(metodo, ruta, body=cuerpo, headers={"Host": host if puerto in (80, 443) else f"{host}:{puerto}", "User-Agent": "GuildaWork-verificacion/1", "Connection": "close", **(cabeceras or {})})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                url = r.getheader("Location")
                if url.startswith("/"):
                    url = f"{esquema}://{host}{url}"
                conn.close()
                continue
            if r.status != 200:
                raise ErrorDescarga(f"El servidor respondió {r.status}.")
            datos = r.read(MAX_BYTES + 1)
            conn.close()
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            raise ErrorDescarga(f"No se pudo conectar: {type(e).__name__}.") from None
        if len(datos) > MAX_BYTES:
            raise ErrorDescarga("La respuesta es demasiado grande.")
        return datos
    raise ErrorDescarga("Demasiadas redirecciones.")


# --- Lo que publica el certificado ---------------------------------------------------------------------------------------------------------------

def _aia(cert: x509.Certificate, tipo) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return []
    return [d.access_location.value for d in ext if d.access_method == tipo and isinstance(d.access_location, x509.UniformResourceIdentifier)]


def urls_ocsp(cert: x509.Certificate) -> list[str]:
    return _aia(cert, AuthorityInformationAccessOID.OCSP)


def urls_emisor(cert: x509.Certificate) -> list[str]:
    return _aia(cert, AuthorityInformationAccessOID.CA_ISSUERS)


def urls_crl(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.CRL_DISTRIBUTION_POINTS).value
    except x509.ExtensionNotFound:
        return []
    return [n.value for p in ext for n in (p.full_name or []) if isinstance(n, x509.UniformResourceIdentifier)]


def _cargar_certificados(datos: bytes) -> list[x509.Certificate]:
    for cargador in (lambda d: [x509.load_der_x509_certificate(d)], x509.load_pem_x509_certificates,
                     lambda d: __import__("cryptography.hazmat.primitives.serialization.pkcs7", fromlist=["x"]).load_der_pkcs7_certificates(d)):
        try:
            return list(cargador(datos))
        except Exception:  # noqa: BLE001 -- se prueba el siguiente formato
            continue
    return []


_RAICES: list[x509.Certificate] | None = None


def raices_del_sistema() -> list[x509.Certificate]:
    global _RAICES
    if _RAICES is None:
        try:
            with open(RUTA_CA_SISTEMA, "rb") as f:
                _RAICES = x509.load_pem_x509_certificates(f.read())
        except (OSError, ValueError):
            _RAICES = []
    return _RAICES


# --- Cadena ----------------------------------------------------------------------------------------------------------------------------------------

def _firmado_por(cert: x509.Certificate, emisor: x509.Certificate) -> bool:
    try:
        cert.verify_directly_issued_by(emisor)
        return True
    except (ValueError, TypeError, InvalidSignature, Exception):  # noqa: BLE001
        return False


def _es_ca(cert: x509.Certificate) -> bool:
    try:
        return bool(cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca)
    except x509.ExtensionNotFound:
        return False


def _autofirmado(cert: x509.Certificate) -> bool:
    return cert.issuer == cert.subject and _firmado_por(cert, cert)


def buscar_emisor(cert: x509.Certificate, intermedios: list[x509.Certificate], raices: list[x509.Certificate], descargar_fn=descargar) -> tuple[x509.Certificate | None, str]:
    """El certificado que firmó a `cert`: entre los conocidos (intermedios + raíces de confianza) o bajándolo de su dirección AIA. `(emisor | None, nota)`."""
    for c in [*intermedios, *raices]:
        if c.subject == cert.issuer and _firmado_por(cert, c):
            return c, ""
    errores = []
    for url in urls_emisor(cert)[:3]:
        try:
            for c in _cargar_certificados(descargar_fn(url)):
                if c.subject == cert.issuer and _firmado_por(cert, c):
                    return c, ""
        except ErrorDescarga as e:
            errores.append(str(e))
    return None, ("No se pudo obtener el certificado del emisor" + (f" ({'; '.join(errores)})" if errores else "") + ".")


def comprobar_cadena(hoja: x509.Certificate, intermedios: list[x509.Certificate] | None = None, raices: list[x509.Certificate] | None = None, ahora: datetime | None = None,
                     descargar_fn=descargar) -> tuple[str, str]:
    """`(resultado, detalle)`. Sube de la hoja hasta una raíz de confianza comprobando cada firma, que cada emisor sea una CA y que esté vigente."""
    ahora = ahora or datetime.now(timezone.utc)
    raices = raices_del_sistema() if raices is None else raices
    huellas_raices = {r.fingerprint(hashes.SHA256()) for r in raices}
    actual, vistos, cadena = hoja, set(), [hoja]
    for _ in range(PROFUNDIDAD_MAXIMA):
        if actual.fingerprint(hashes.SHA256()) in huellas_raices and _autofirmado(actual):
            return "valida", f"Cadena de {len(cadena)} certificado(s) hasta la raíz de confianza «{actual.subject.rfc4514_string()[:80]}»."
        if _autofirmado(actual):
            return "indeterminada", f"La raíz «{actual.subject.rfc4514_string()[:80]}» no está en el almacén de confianza del servidor: no se puede afirmar que sea de confianza."
        emisor, nota = buscar_emisor(actual, intermedios or [], raices, descargar_fn)
        if emisor is None:
            return "indeterminada", nota
        huella = emisor.fingerprint(hashes.SHA256())
        if huella in vistos:
            return "invalida", "La cadena da vueltas sobre sí misma."
        vistos.add(huella)
        if not _es_ca(emisor):
            return "invalida", f"El emisor «{emisor.subject.rfc4514_string()[:80]}» no es una autoridad de certificación."
        if not (emisor.not_valid_before_utc <= ahora <= emisor.not_valid_after_utc):
            return "invalida", f"El certificado del emisor «{emisor.subject.rfc4514_string()[:80]}» no está vigente."
        cadena.append(emisor)
        actual = emisor
    return "indeterminada", "La cadena es demasiado larga para comprobarla."


# --- Revocación ------------------------------------------------------------------------------------------------------------------------------------

def _verificar_firma(clave, firma: bytes, datos: bytes, hash_alg) -> bool:
    try:
        if isinstance(clave, rsa.RSAPublicKey):
            clave.verify(firma, datos, padding.PKCS1v15(), hash_alg)
        elif isinstance(clave, ec.EllipticCurvePublicKey):
            clave.verify(firma, datos, ec.ECDSA(hash_alg))
        else:
            return False
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _respondedor(resp: ocsp.OCSPResponse, emisor: x509.Certificate) -> x509.Certificate | None:
    """Quien firma la respuesta OCSP: el propio emisor o un certificado delegado que el emisor haya firmado."""
    candidatos = [emisor, *resp.certificates]
    for c in candidatos:
        coincide = (resp.responder_name == c.subject) if resp.responder_name is not None else (
            resp.responder_key_hash == x509.SubjectKeyIdentifier.from_public_key(c.public_key()).digest)
        if not coincide:
            continue
        if c == emisor or _firmado_por(c, emisor):
            return c
    return None


def comprobar_ocsp(hoja: x509.Certificate, emisor: x509.Certificate, ahora: datetime | None = None, descargar_fn=descargar) -> tuple[str, str]:
    ahora = ahora or datetime.now(timezone.utc)
    urls = urls_ocsp(hoja)
    if not urls:
        return "indeterminada", "El certificado no publica dirección OCSP."
    peticion = ocsp.OCSPRequestBuilder().add_certificate(hoja, emisor, hashes.SHA1()).build().public_bytes(serialization.Encoding.DER)   # SHA-1 solo identifica al emisor, como pide el RFC 6960
    ultimo = ""
    for url in urls[:2]:
        try:
            resp = ocsp.load_der_ocsp_response(descargar_fn(url, metodo="POST", cuerpo=peticion, cabeceras={"Content-Type": "application/ocsp-request"}))
        except ErrorDescarga as e:
            ultimo = str(e); continue
        except Exception:  # noqa: BLE001
            ultimo = "Respuesta OCSP ilegible."; continue
        if resp.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
            ultimo = f"El servidor OCSP respondió «{resp.response_status.name}»."; continue
        firmante = _respondedor(resp, emisor)
        if firmante is None or not _verificar_firma(firmante.public_key(), resp.signature, resp.tbs_response_bytes, resp.signature_hash_algorithm):
            return "indeterminada", "La respuesta OCSP no está firmada por el emisor ni por un delegado suyo: se descarta."
        if resp.serial_number != hoja.serial_number:
            return "indeterminada", "La respuesta OCSP es de otro certificado."
        if resp.next_update_utc is not None and resp.next_update_utc < ahora:
            ultimo = "La respuesta OCSP está caducada."; continue
        if resp.this_update_utc > ahora + timedelta(minutes=10):
            ultimo = "La respuesta OCSP es de fecha futura."; continue
        if resp.certificate_status == ocsp.OCSPCertStatus.GOOD:
            return "no_revocado_en_comprobacion", f"OCSP: sin revocar a {resp.this_update_utc:%Y-%m-%d %H:%M} UTC."
        if resp.certificate_status == ocsp.OCSPCertStatus.REVOKED:
            cuando = f" el {resp.revocation_time_utc:%Y-%m-%d}" if resp.revocation_time_utc else ""
            motivo = f" (motivo: {resp.revocation_reason.name})" if resp.revocation_reason else ""
            return "revocado", f"OCSP: revocado{cuando}{motivo}."
        return "indeterminada", "OCSP: el servidor no conoce este certificado."
    return "indeterminada", ultimo or "No se pudo consultar OCSP."


def comprobar_crl(hoja: x509.Certificate, emisor: x509.Certificate, ahora: datetime | None = None, descargar_fn=descargar) -> tuple[str, str]:
    ahora = ahora or datetime.now(timezone.utc)
    urls = urls_crl(hoja)
    if not urls:
        return "indeterminada", "El certificado no publica lista de revocación (CRL)."
    ultimo = ""
    for url in urls[:2]:
        try:
            datos = descargar_fn(url)
        except ErrorDescarga as e:
            ultimo = str(e); continue
        try:
            crl = x509.load_der_x509_crl(datos)
        except ValueError:
            try:
                crl = x509.load_pem_x509_crl(datos)
            except ValueError:
                ultimo = "Lista de revocación ilegible."; continue
        if not crl.is_signature_valid(emisor.public_key()):
            return "indeterminada", "La lista de revocación no está firmada por el emisor: se descarta."
        if crl.next_update_utc is not None and crl.next_update_utc < ahora:
            ultimo = "La lista de revocación está caducada."; continue
        entrada = crl.get_revoked_certificate_by_serial_number(hoja.serial_number)
        if entrada is not None:
            return "revocado", f"CRL: revocado el {entrada.revocation_date_utc:%Y-%m-%d}."
        return "no_revocado_en_comprobacion", f"CRL: no figura (lista de {crl.last_update_utc:%Y-%m-%d})."
    return "indeterminada", ultimo or "No se pudo consultar la CRL."


def comprobar_revocacion(hoja: x509.Certificate, emisor: x509.Certificate | None, ahora: datetime | None = None, descargar_fn=descargar) -> tuple[str, str, str]:
    """`(resultado, detalle, método)`. Primero OCSP; si no da una respuesta firmada y válida, la CRL. Sin emisor no se puede comprobar."""
    if emisor is None:
        return "indeterminada", "Sin el certificado del emisor no se puede comprobar la revocación.", "ocsp"
    r, d = comprobar_ocsp(hoja, emisor, ahora, descargar_fn)
    if r in ("revocado", "no_revocado_en_comprobacion"):
        return r, d, "ocsp"
    r2, d2 = comprobar_crl(hoja, emisor, ahora, descargar_fn)
    if r2 in ("revocado", "no_revocado_en_comprobacion"):
        return r2, d2, "crl"
    return "indeterminada", f"{d} {d2}", "ocsp+crl"


def verificar(der: bytes, intermedios: list[x509.Certificate] | None = None, raices: list[x509.Certificate] | None = None, ahora: datetime | None = None, descargar_fn=descargar) -> dict:
    """Las dos comprobaciones de un certificado dado en DER: `{"cadena": (resultado, detalle), "revocacion": (resultado, detalle, método)}`."""
    hoja = x509.load_der_x509_certificate(der)
    raices_ = raices_del_sistema() if raices is None else raices
    emisor, _ = buscar_emisor(hoja, intermedios or [], raices_, descargar_fn)
    return {"cadena": comprobar_cadena(hoja, intermedios, raices_, ahora, descargar_fn), "revocacion": comprobar_revocacion(hoja, emisor, ahora, descargar_fn)}
