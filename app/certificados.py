"""Inventario de certificados digitales X.509 (especificación de control fiscal, RF-07 a RF-12).

Es una **capa de control**: sabe qué certificados tiene el despacho, cuándo caducan, a qué clientes y servicios dan acceso, quién es su custodio y en qué punto
está su renovación. **No custodia claves privadas**: solo se admite material público (PEM/DER) y cualquier fichero que contenga una clave privada o un contenedor
.p12/.pfx se rechaza antes de guardar nada (`contiene_clave_privada`, que también usan los puntos de subida de documentos).

Principios:
- El estado se mide en **dimensiones independientes** (temporal, cadena, revocación, clave, operativa, renovación). Una fecha correcta no acredita cadena, revocación,
  posesión de la clave ni autorización; lo no comprobado se muestra como «no comprobado», nunca como «correcto».
- La validez temporal sigue RFC 5280: de `notBefore` a `notAfter`, ambos incluidos, a precisión de instante (UTC). El contador de días es solo informativo.
- La identificación fiscal que se extrae del certificado es una **sugerencia**: la confirma el custodio. Titular del certificado y cliente representado son cosas distintas.
- No se borra nada: un certificado sustituido o archivado conserva su historial y sus evidencias.
- Los avisos (90, 60, 30, 15, 7, 1 días y caducidad) se deduplican y, si un certificado entra ya dentro de un umbral, solo avisa el vigente: nunca una ráfaga retrospectiva."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from cryptography import x509
from flask_babel import lazy_gettext as _l
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed448, ed25519, rsa
from cryptography.x509.oid import ExtensionOID, NameOID

from . import db, nucleo

logger = logging.getLogger(__name__)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS certificados (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    huella_sha256 TEXT NOT NULL,
    der BLOB,
    verificado INTEGER NOT NULL DEFAULT 1,
    origen TEXT NOT NULL DEFAULT 'importacion',
    numero_serie TEXT,
    emisor TEXT,
    sujeto TEXT,
    nombre_comun TEXT,
    san TEXT,
    not_before TEXT,
    not_after TEXT,
    algoritmo_firma TEXT,
    clave_publica TEXT,
    usos_clave TEXT,
    politicas TEXT,
    es_ca INTEGER NOT NULL DEFAULT 0,
    ruta_cadena TEXT,
    nif_sugerido TEXT,
    nif_confirmado TEXT,
    tipo_titular_sugerido TEXT,
    tipo_titular TEXT,
    custodio_id INTEGER REFERENCES usuarios(id),
    ubicacion_externa TEXT,
    notas TEXT,
    estado_operativo TEXT NOT NULL DEFAULT 'inventariado' CHECK (estado_operativo IN ('inventariado', 'autorizado', 'suspendido', 'sustituido', 'archivado')),
    sustituye_a INTEGER REFERENCES certificados(id),
    version INTEGER NOT NULL DEFAULT 1,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    UNIQUE (tenant_id, huella_sha256)
);
CREATE INDEX IF NOT EXISTS idx_certificados_caducidad ON certificados(tenant_id, estado_operativo, not_after);
CREATE TABLE IF NOT EXISTS certificados_evaluaciones (
    id INTEGER PRIMARY KEY,
    certificado_id INTEGER NOT NULL REFERENCES certificados(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL CHECK (dimension IN ('cadena', 'revocacion', 'clave')),
    resultado TEXT NOT NULL,
    metodo TEXT NOT NULL DEFAULT 'manual',
    detalle TEXT,
    comprobado_por INTEGER REFERENCES usuarios(id),
    comprobado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cert_eval ON certificados_evaluaciones(certificado_id, dimension, comprobado_en);
CREATE TABLE IF NOT EXISTS certificados_vinculos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    certificado_id INTEGER NOT NULL REFERENCES certificados(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER REFERENCES clientes_fiscales(id),
    servicio TEXT NOT NULL CHECK (servicio IN ('acceso_buzon', 'firma', 'presentacion', 'otro')),
    autorizacion TEXT NOT NULL,
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,
    estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'retirado')),
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    retirado_en TEXT,
    motivo_retirada TEXT
);
CREATE INDEX IF NOT EXISTS idx_cert_vinculos ON certificados_vinculos(certificado_id, estado);
CREATE INDEX IF NOT EXISTS idx_cert_vinculos_cliente ON certificados_vinculos(cliente_fiscal_id, estado);
CREATE TABLE IF NOT EXISTS certificados_renovaciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    certificado_id INTEGER NOT NULL REFERENCES certificados(id),
    nuevo_certificado_id INTEGER REFERENCES certificados(id),
    fase TEXT NOT NULL DEFAULT 'sin_iniciar' CHECK (fase IN ('sin_iniciar', 'en_gestion', 'pendiente_titular', 'obtenido', 'validado', 'implantado', 'cerrado', 'cancelada')),
    titular TEXT,
    notas TEXT,
    abierta_por INTEGER REFERENCES usuarios(id),
    abierta_en TEXT NOT NULL,
    cerrada_en TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cert_renovacion_activa ON certificados_renovaciones(certificado_id) WHERE fase NOT IN ('cerrado', 'cancelada');
CREATE TABLE IF NOT EXISTS certificados_implantaciones (
    id INTEGER PRIMARY KEY,
    renovacion_id INTEGER NOT NULL REFERENCES certificados_renovaciones(id) ON DELETE CASCADE,
    vinculo_id INTEGER NOT NULL REFERENCES certificados_vinculos(id),
    resultado TEXT NOT NULL CHECK (resultado IN ('correcta', 'fallida')),
    nota TEXT,
    comprobado_por INTEGER REFERENCES usuarios(id),
    comprobado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cert_implantaciones ON certificados_implantaciones(renovacion_id, vinculo_id, comprobado_en);
CREATE TABLE IF NOT EXISTS certificados_eventos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    certificado_id INTEGER,
    usuario_id INTEGER,
    accion TEXT NOT NULL,
    detalle TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cert_eventos ON certificados_eventos(certificado_id, id);
CREATE TABLE IF NOT EXISTS certificados_avisos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    certificado_id INTEGER NOT NULL REFERENCES certificados(id) ON DELETE CASCADE,
    umbral INTEGER NOT NULL,
    destinatario_id INTEGER NOT NULL,
    canal TEXT NOT NULL,
    version_fecha TEXT NOT NULL,
    estado TEXT NOT NULL,
    detalle TEXT,
    creado_en TEXT NOT NULL,
    UNIQUE (certificado_id, umbral, destinatario_id, canal, version_fecha)
);
"""

MAX_BYTES = 256 * 1024
MAX_CERTIFICADOS_EN_FICHERO = 20
UMBRALES = (90, 60, 30, 15, 7, 1, 0)                   # 0 = caducado
UMBRAL_RENOVACION = 60                                 # a partir de aquí se abre sola la renovación
SERVICIOS = (("acceso_buzon", "Acceso a un buzón de notificaciones"), ("firma", "Firma"), ("presentacion", "Presentación de impuestos"), ("otro", "Otro"))
OPERATIVOS = ("inventariado", "autorizado", "suspendido", "sustituido", "archivado")
FASES = ("sin_iniciar", "en_gestion", "pendiente_titular", "obtenido", "validado", "implantado", "cerrado")
_TRANSICIONES = {
    "sin_iniciar": {"en_gestion"}, "en_gestion": {"pendiente_titular", "obtenido"}, "pendiente_titular": {"en_gestion", "obtenido"},
    "obtenido": {"validado"}, "validado": {"implantado"}, "implantado": {"cerrado"},
}
RESULTADOS = {"cadena": ("no_comprobada", "valida", "invalida", "indeterminada"),
              "revocacion": ("no_comprobada", "no_revocado_en_comprobacion", "revocado", "indeterminada"),
              "clave": ("no_declarada", "declarada_en_medio_autorizado", "no_disponible")}
_MARCAS_CLAVE_PRIVADA = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
_OID_PKCS7_DATOS = bytes.fromhex("2a864886f70d010701")
_NIF = re.compile(r"\b([XYZ]\d{7}[A-Z]|\d{8}[A-Z]|[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J])\b")
_SECRETOS = re.compile(r"contrase[ñn]a|password|passphrase|\bpwd\b|\bpin\s*[:=]", re.I)


class EleccionRequerida(ValueError):
    """El fichero trae varios certificados finales posibles: hay que decir cuál es (`candidatos`)."""
    def __init__(self, mensaje: str, candidatos: list[dict]):
        super().__init__(mensaje)
        self.candidatos = candidatos


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    """Borra todo lo de certificados de un despacho, en el orden que respeta las claves foráneas (lo llama `borrar_tenant` ANTES de borrar los clientes fiscales)."""
    cert = "SELECT id FROM certificados WHERE tenant_id = ?"
    reno = f"SELECT id FROM certificados_renovaciones WHERE certificado_id IN ({cert})"
    for sql in (f"DELETE FROM certificados_implantaciones WHERE renovacion_id IN ({reno})", f"DELETE FROM certificados_renovaciones WHERE certificado_id IN ({cert})",
                f"UPDATE certificados SET sustituye_a = NULL WHERE tenant_id = ?", f"DELETE FROM certificados_vinculos WHERE tenant_id = ?",
                f"DELETE FROM certificados_evaluaciones WHERE certificado_id IN ({cert})", "DELETE FROM certificados_avisos WHERE tenant_id = ?",
                "DELETE FROM certificados_avisos_cliente WHERE tenant_id = ?", "DELETE FROM certificados_config WHERE tenant_id = ?",
                "DELETE FROM certificados_eventos WHERE tenant_id = ?", "DELETE FROM certificados WHERE tenant_id = ?"):
        conn.execute(sql, (tenant_id,) * sql.count("?"))


ESQUEMA_AVISOS_CLIENTE = """
CREATE TABLE IF NOT EXISTS certificados_config (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    avisar_cliente INTEGER NOT NULL DEFAULT 0,
    mostrar_en_portal INTEGER NOT NULL DEFAULT 0,
    dias_antes TEXT NOT NULL DEFAULT '60,30,15,7',
    dias_despues TEXT NOT NULL DEFAULT '3',
    asunto TEXT NOT NULL DEFAULT '',
    cuerpo TEXT NOT NULL DEFAULT '',
    instrucciones TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS certificados_avisos_cliente (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    certificado_id INTEGER NOT NULL REFERENCES certificados(id) ON DELETE CASCADE,
    dias INTEGER NOT NULL,
    version_fecha TEXT NOT NULL,
    estado TEXT NOT NULL,
    detalle TEXT,
    creado_en TEXT NOT NULL,
    UNIQUE (certificado_id, dias, version_fecha)
);
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "usuarios", "custodio_certificados", "INTEGER NOT NULL DEFAULT 0")
    for col, tipo in (("tipo_certificado", "TEXT"), ("cliente_titular_id", "INTEGER REFERENCES clientes_fiscales(id)"), ("avisar_cliente", "INTEGER"), ("ayuda_solicitada_en", "TEXT")):
        db._asegurar_columna(conn, "certificados", col, tipo)
    conn.executescript(ESQUEMA_AVISOS_CLIENTE)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_certificados_cliente ON certificados(tenant_id, cliente_titular_id)")


# --- Seguridad del material: nada de claves privadas ---------------------------------------------------------------------------------------------
def es_pkcs12(datos: bytes) -> bool:
    """Contenedor .p12/.pfx (lleva la clave privada). Se reconoce por el contenido, no por la extensión."""
    if len(datos) > 8 and datos[0] == 0x30 and b"\x02\x01\x03" in datos[:14] and _OID_PKCS7_DATOS in datos[:64]:
        return True
    if datos[:1] == b"\x30":
        try:
            from cryptography.hazmat.primitives.serialization import pkcs12
            pkcs12.load_pkcs12(datos, None)
            return True
        except Exception:  # noqa: BLE001  (contraseña pedida o no es PKCS#12: ya lo ha descartado la comprobación estructural)
            return False
    return False


def contiene_clave_privada(datos: bytes) -> str | None:
    """Motivo (texto para personas) si el contenido es o lleva una clave privada o un contenedor .p12/.pfx; `None` si no. Barato: se usa en cada subida de documentos."""
    if not datos or len(datos) > 4 * 1024 * 1024:
        return None
    if _MARCAS_CLAVE_PRIVADA.search(datos):
        return "contiene una clave privada en formato PEM"
    if es_pkcs12(datos):
        return "es un contenedor PKCS#12 (.p12/.pfx), que incluye la clave privada"
    if datos[:1] == b"\x30" and len(datos) < 16384:
        try:
            serialization.load_der_private_key(datos, password=None)
            return "es una clave privada"
        except TypeError:
            return "es una clave privada protegida con contraseña"
        except Exception:  # noqa: BLE001
            return None
    return None


def _sin_secretos(texto: str | None, campo: str) -> str | None:
    t = (texto or "").strip()
    if t and _SECRETOS.search(t):
        raise ValueError(f"{campo}: no escribas contraseñas, PIN ni claves aquí; indica solo dónde está custodiado el certificado.")
    return t or None


# --- Lectura de certificados públicos -----------------------------------------------------------------------------------------------------------
def _utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tipo_clave(pub) -> str:
    if isinstance(pub, rsa.RSAPublicKey):
        return f"RSA {pub.key_size}"
    if isinstance(pub, ec.EllipticCurvePublicKey):
        return f"EC {pub.curve.name}"
    if isinstance(pub, ed25519.Ed25519PublicKey):
        return "Ed25519"
    if isinstance(pub, ed448.Ed448PublicKey):
        return "Ed448"
    return type(pub).__name__


def _extension(cert, oid):
    try:
        return cert.extensions.get_extension_for_oid(oid).value
    except (x509.ExtensionNotFound, ValueError):
        return None


_NOMBRES_OID = {"2.5.4.3": "CN", "2.5.4.5": "serialNumber", "2.5.4.6": "C", "2.5.4.7": "L", "2.5.4.8": "ST", "2.5.4.10": "O", "2.5.4.11": "OU", "2.5.4.12": "T", "2.5.4.4": "SN", "2.5.4.42": "GN",
                "2.5.4.97": "organizationIdentifier", "1.2.840.113549.1.9.1": "emailAddress"}


def _nombre_legible(nombre: x509.Name) -> str:
    """«CN=MARTA PUIG, serialNumber=IDCES-12345678Z»: como RFC 4514, pero con los atributos conocidos por su nombre en vez de por su OID."""
    return ", ".join(f"{_NOMBRES_OID.get(a.oid.dotted_string, a.oid.dotted_string)}={a.value}" for a in reversed(list(nombre)))


def _info(cert: x509.Certificate) -> dict:
    der = cert.public_bytes(serialization.Encoding.DER)
    sujeto_atributos = {a.oid.dotted_string: str(a.value) for a in cert.subject}
    texto_id = " ".join(sujeto_atributos.get(o, "") for o in ("2.5.4.5", "2.5.4.97", "2.5.4.3"))
    nif = _NIF.search(texto_id.upper())
    juridica = bool(sujeto_atributos.get("2.5.4.97") or sujeto_atributos.get("2.5.4.10"))
    ku = _extension(cert, ExtensionOID.KEY_USAGE)
    usos = [n for n in ("digital_signature", "content_commitment", "key_encipherment", "data_encipherment", "key_agreement", "key_cert_sign", "crl_sign") if ku is not None and getattr(ku, n, False)]
    eku = _extension(cert, ExtensionOID.EXTENDED_KEY_USAGE)
    usos += [o.dotted_string for o in eku] if eku is not None else []
    san = _extension(cert, ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
    pol = _extension(cert, ExtensionOID.CERTIFICATE_POLICIES)
    bc = _extension(cert, ExtensionOID.BASIC_CONSTRAINTS)
    try:
        hash_firma = cert.signature_hash_algorithm.name if cert.signature_hash_algorithm else "sin hash"
    except Exception:  # noqa: BLE001
        hash_firma = "desconocido"
    return {
        "huella": hashlib.sha256(der).hexdigest(), "der": der, "numero_serie": format(cert.serial_number, "x"), "emisor": _nombre_legible(cert.issuer), "sujeto": _nombre_legible(cert.subject),
        "nombre_comun": sujeto_atributos.get("2.5.4.3"), "san": [str(v) for v in san.get_values_for_type(x509.GeneralName)] if san is not None else [],
        "not_before": _utc(cert.not_valid_before_utc), "not_after": _utc(cert.not_valid_after_utc), "algoritmo_firma": f"{cert.signature_algorithm_oid._name or cert.signature_algorithm_oid.dotted_string} ({hash_firma})",
        "clave_publica": _tipo_clave(cert.public_key()), "usos_clave": usos, "politicas": [p.policy_identifier.dotted_string for p in pol] if pol is not None else [],
        "es_ca": bool(bc is not None and bc.ca), "nif_sugerido": nif.group(1) if nif else None, "tipo_titular_sugerido": "persona_juridica" if juridica else "persona_fisica",
        "_subject_bytes": cert.subject.public_bytes(), "_issuer_bytes": cert.issuer.public_bytes(),
    }


def _publico(info: dict) -> dict:
    return {k: v for k, v in info.items() if not k.startswith("_") and k != "der"}


def analizar(datos: bytes) -> dict:
    """Examina un fichero SIN guardar nada. Devuelve `{"certificados": [...], "hoja": huella | None, "cadena": [...]}`.
    Rechaza claves privadas, contenedores .p12/.pfx, ficheros enormes y cualquier cosa que no sea un certificado público PEM/DER."""
    if not datos:
        raise ValueError("El archivo está vacío.")
    if len(datos) > MAX_BYTES:
        raise ValueError(f"El archivo es demasiado grande para ser un certificado público (máximo {MAX_BYTES // 1024} KB).")
    motivo = contiene_clave_privada(datos)
    if motivo:
        raise ValueError(f"Este archivo {motivo}. Guilda Work no guarda claves privadas: exporta solo la parte pública del certificado (.cer, .crt o .pem) con tu herramienta local.")
    try:
        if b"-----BEGIN CERTIFICATE-----" in datos or b"-----BEGIN X509 CERTIFICATE-----" in datos:
            certs = x509.load_pem_x509_certificates(datos)
        else:
            certs = [x509.load_der_x509_certificate(datos)]
    except Exception:  # noqa: BLE001  (ASN.1 corrupto, formato desconocido...)
        raise ValueError("El archivo no es un certificado público válido (se esperaba PEM o DER).") from None
    if not certs or len(certs) > MAX_CERTIFICADOS_EN_FICHERO:
        raise ValueError("El archivo no contiene entre 1 y %d certificados." % MAX_CERTIFICADOS_EN_FICHERO)
    infos = [_info(c) for c in certs]
    emisores = {i["_issuer_bytes"] for i in infos if i["_subject_bytes"] != i["_issuer_bytes"]}
    hojas = [i for i in infos if i["_subject_bytes"] not in emisores] if len(infos) > 1 else infos
    unicas = {i["huella"]: i for i in hojas}
    return {"certificados": [_publico(i) for i in infos], "hoja": next(iter(unicas)) if len(unicas) == 1 else None,
            "candidatos": [_publico(i) for i in unicas.values()], "_infos": {i["huella"]: i for i in infos}}


# --- Estado temporal ---------------------------------------------------------------------------------------------------------------------------
def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _dt(iso: str | None) -> datetime | None:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if iso else None


def estado_temporal(not_before: str | None, not_after: str | None, ahora: datetime | None = None) -> str:
    """`todavia_no_vigente`, `vigente` o `caducado` (RFC 5280: ambos extremos incluidos). `desconocido` si faltan las fechas."""
    ahora = ahora or _ahora()
    ini, fin = _dt(not_before), _dt(not_after)
    if fin is None:
        return "desconocido"
    if ini is not None and ahora < ini:
        return "todavia_no_vigente"
    if ahora > fin:
        return "caducado"
    return "vigente"


def dias_restantes(not_after: str | None, ahora: datetime | None = None) -> int | None:
    """Días completos hasta `notAfter` (negativo si ya caducó). Informativo: no determina la validez."""
    fin = _dt(not_after)
    if fin is None:
        return None
    segundos = (fin - (ahora or _ahora())).total_seconds()
    return int(segundos // 86400)


def hora_local(iso: str | None, tenant_id: int) -> str | None:
    """«2026-11-30 23:59 (hora de Europe/Madrid)» a partir del instante UTC."""
    d = _dt(iso)
    if d is None:
        return None
    from zoneinfo import ZoneInfo
    t = db.obtener_tenant(tenant_id)
    zona = (t["zona_horaria"] if t is not None and "zona_horaria" in t.keys() and t["zona_horaria"] else "Europe/Madrid")
    try:
        return d.astimezone(ZoneInfo(zona)).strftime("%Y-%m-%d %H:%M") + f" ({zona})"
    except Exception:  # noqa: BLE001
        return d.strftime("%Y-%m-%d %H:%M") + " (UTC)"


# --- Permisos ----------------------------------------------------------------------------------------------------------------------------------
def es_custodio(usuario_id: int, tenant_id: int | None) -> bool:
    u = db.obtener_usuario(usuario_id)
    return bool(u is not None and tenant_id and u["tenant_id"] == tenant_id and u["custodio_certificados"])


def puede_gestionar(usuario_id: int, tenant_id: int | None) -> bool:
    """Custodios de certificados y supervisores del despacho (dirección y coordinación)."""
    if not tenant_id:
        return False
    u = db.obtener_usuario(usuario_id)
    return bool(u is not None and u["tenant_id"] == tenant_id and (u["custodio_certificados"] or db.es_supervisor_tenant(usuario_id)))


def _exigir(usuario_id: int, tenant_id: int) -> None:
    if not puede_gestionar(usuario_id, tenant_id):
        raise ValueError("Solo los custodios de certificados y los supervisores del despacho pueden hacer esto.")


def fijar_custodio_flag(tenant_id: int, supervisor_id: int, usuario_id: int, valor: bool) -> None:
    if not db.es_supervisor_tenant(supervisor_id) or db.tenant_de_usuario(supervisor_id) is None or db.tenant_de_usuario(supervisor_id)["id"] != tenant_id:
        raise ValueError("Solo un supervisor del despacho puede designar custodios.")
    conn = db.get_connection()
    try:
        nucleo._usuario_de_tenant(conn, usuario_id, tenant_id)
        conn.execute("UPDATE usuarios SET custodio_certificados = ? WHERE id = ?", (int(bool(valor)), usuario_id))
        conn.commit()
    finally:
        conn.close()


def custodios(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT u.id, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS nombre, u.custodio_certificados AS custodio FROM usuarios u "
                                                "LEFT JOIN usuario_perfil p ON p.usuario_id = u.id WHERE u.tenant_id = ? ORDER BY lower(nombre)", (tenant_id,))]
    finally:
        conn.close()


# --- Registro de eventos ---------------------------------------------------------------------------------------------------------------------------
def _evento(conn, tenant_id: int, certificado_id: int | None, usuario_id: int | None, accion: str, detalle: dict | str | None = None) -> None:
    from . import auditoria
    auditoria.registrar(tenant_id, usuario_id, f"certificado.{accion}", "certificado", certificado_id, detalle, conn=conn)       # misma transacción que el cambio
    conn.execute("INSERT INTO certificados_eventos (tenant_id, certificado_id, usuario_id, accion, detalle, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                 (tenant_id, certificado_id, usuario_id, accion, json.dumps(detalle, ensure_ascii=False) if isinstance(detalle, dict) else detalle, db.now_iso()))


def eventos(tenant_id: int, certificado_id: int, limite: int = 100) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT e.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS actor FROM certificados_eventos e LEFT JOIN usuarios u ON u.id = e.usuario_id "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = e.usuario_id WHERE e.tenant_id = ? AND e.certificado_id = ? ORDER BY e.id DESC LIMIT ?", (tenant_id, certificado_id, limite))]
    finally:
        conn.close()


# --- Alta de certificados ----------------------------------------------------------------------------------------------------------------------
_COLUMNAS_JSON = ("san", "usos_clave", "politicas", "ruta_cadena")


def importar(tenant_id: int, usuario_id: int, datos: bytes, *, huella: str | None = None, origen: str = "importacion", ubicacion_externa: str | None = None,
             custodio_id: int | None = None, notas: str | None = None, sustituye_a: int | None = None) -> dict:
    """Importa un certificado público. Si el fichero trae varios certificados finales exige `huella` (lanza `EleccionRequerida`). Importar de nuevo el mismo no crea otro:
    devuelve `{"id": ..., "nuevo": False}`."""
    _exigir(usuario_id, tenant_id)
    a = analizar(datos)
    elegida = huella or a["hoja"]
    if elegida is None:
        raise EleccionRequerida("El archivo contiene varios certificados finales: elige cuál es el del cliente.", a["candidatos"])
    info = a["_infos"].get(elegida)
    if info is None:
        raise ValueError("Esa huella no corresponde a ningún certificado del archivo.")
    ubicacion = _sin_secretos(ubicacion_externa, "Ubicación")
    notas = _sin_secretos(notas, "Notas")
    cadena = [{"huella": i["huella"], "sujeto": i["sujeto"], "es_ca": i["es_ca"]} for i in a["certificados"] if i["huella"] != elegida]
    conn = db.get_connection()
    try:
        existente = conn.execute("SELECT id FROM certificados WHERE tenant_id = ? AND huella_sha256 = ?", (tenant_id, elegida)).fetchone()
        if existente:
            return {"id": existente["id"], "nuevo": False, "huella": elegida}
        if custodio_id:
            nucleo._usuario_de_tenant(conn, custodio_id, tenant_id, "El custodio")
        if sustituye_a is not None and conn.execute("SELECT 1 FROM certificados WHERE id = ? AND tenant_id = ?", (sustituye_a, tenant_id)).fetchone() is None:
            raise ValueError("El certificado que se sustituye no existe.")
        ahora = db.now_iso()
        cur = conn.execute(
            "INSERT INTO certificados (tenant_id, huella_sha256, der, verificado, origen, numero_serie, emisor, sujeto, nombre_comun, san, not_before, not_after, algoritmo_firma, clave_publica, usos_clave, politicas, "
            "es_ca, ruta_cadena, nif_sugerido, tipo_titular_sugerido, custodio_id, ubicacion_externa, notas, sustituye_a, creado_por, creado_en, actualizado_en) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, elegida, info["der"], origen, info["numero_serie"], info["emisor"], info["sujeto"], info["nombre_comun"], json.dumps(info["san"]), info["not_before"], info["not_after"],
             info["algoritmo_firma"], info["clave_publica"], json.dumps(info["usos_clave"]), json.dumps(info["politicas"]), int(info["es_ca"]), json.dumps(cadena), info["nif_sugerido"],
             info["tipo_titular_sugerido"], custodio_id or (usuario_id if es_custodio(usuario_id, tenant_id) else None), ubicacion, notas, sustituye_a, usuario_id, ahora, ahora))
        cid = cur.lastrowid
        _evento(conn, tenant_id, cid, usuario_id, "importado", {"huella": elegida, "origen": origen})
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "nuevo": True, "huella": elegida}


def alta_manual(tenant_id: int, usuario_id: int, *, sujeto: str, emisor: str, numero_serie: str, not_before: str | None, not_after: str, evidencia: str,
                ubicacion_externa: str | None = None, custodio_id: int | None = None) -> dict:
    """Alta de metadatos sin el fichero (queda «pendiente de comprobar»: `verificado = 0`, sin huella real). `evidencia` es obligatoria: de dónde salen los datos."""
    _exigir(usuario_id, tenant_id)
    sujeto, emisor, serie = (sujeto or "").strip()[:300], (emisor or "").strip()[:300], (numero_serie or "").strip().lower().replace(":", "")[:80]
    if not sujeto or not emisor or not serie:
        raise ValueError("Indica sujeto, emisor y número de serie.")
    evidencia = _sin_secretos(evidencia, "Evidencia")
    if not evidencia:
        raise ValueError("Indica la evidencia de la que salen estos datos (por ejemplo, «captura del portal del emisor, 13/10/2026»).")
    try:
        fin = datetime.strptime((not_after or "").strip()[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        ini = datetime.strptime(not_before.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) if (not_before or "").strip() else None
    except ValueError:
        raise ValueError("Las fechas deben tener el formato AAAA-MM-DD.") from None
    huella = hashlib.sha256(f"manual|{emisor}|{serie}".encode()).hexdigest()
    ubicacion = _sin_secretos(ubicacion_externa, "Ubicación")
    conn = db.get_connection()
    try:
        existente = conn.execute("SELECT id FROM certificados WHERE tenant_id = ? AND huella_sha256 = ?", (tenant_id, huella)).fetchone()
        if existente:
            return {"id": existente["id"], "nuevo": False, "huella": huella}
        if custodio_id:
            nucleo._usuario_de_tenant(conn, custodio_id, tenant_id, "El custodio")
        ahora = db.now_iso()
        cur = conn.execute("INSERT INTO certificados (tenant_id, huella_sha256, verificado, origen, numero_serie, emisor, sujeto, not_before, not_after, custodio_id, ubicacion_externa, notas, creado_por, creado_en, actualizado_en) "
                           "VALUES (?, ?, 0, 'manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, huella, serie, emisor, sujeto, _utc(ini) if ini else None, _utc(fin), custodio_id, ubicacion, evidencia, usuario_id, ahora, ahora))
        cid = cur.lastrowid
        _evento(conn, tenant_id, cid, usuario_id, "alta_manual", {"evidencia": evidencia})
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "nuevo": True, "huella": huella}


# --- Consulta ---------------------------------------------------------------------------------------------------------------------------------
def _ultima(conn, certificado_id: int, dimension: str):
    return conn.execute("SELECT * FROM certificados_evaluaciones WHERE certificado_id = ? AND dimension = ? ORDER BY id DESC LIMIT 1", (certificado_id, dimension)).fetchone()


def _enriquecer(conn, f, ahora: datetime, zona=None) -> dict:
    d = dict(f)
    d.pop("der", None)
    for c in _COLUMNAS_JSON:
        d[c] = json.loads(d[c]) if d.get(c) else []
    d["temporal"] = estado_temporal(d["not_before"], d["not_after"], ahora)
    d["dias_restantes"] = dias_restantes(d["not_after"], ahora)
    for dim, defecto in (("cadena", "no_comprobada"), ("revocacion", "no_comprobada"), ("clave", "no_declarada")):
        e = _ultima(conn, d["id"], dim)
        d[dim] = {"resultado": e["resultado"] if e else defecto, "comprobado_en": e["comprobado_en"] if e else None, "metodo": e["metodo"] if e else None, "detalle": e["detalle"] if e else None}
    reno = conn.execute("SELECT fase FROM certificados_renovaciones WHERE certificado_id = ? ORDER BY id DESC LIMIT 1", (d["id"],)).fetchone()
    d["renovacion"] = reno["fase"] if reno else "sin_iniciar"
    d["vinculos_activos"] = conn.execute("SELECT COUNT(*) FROM certificados_vinculos WHERE certificado_id = ? AND estado = 'activo'", (d["id"],)).fetchone()[0]
    d["custodio_nombre"] = db.nombre_mostrado_usuario(d["custodio_id"]) or (db.obtener_usuario(d["custodio_id"])["email"] if d["custodio_id"] else None)
    d["pendiente_de_comprobar"] = not d["verificado"]
    d["caduca_el"] = fecha_local(d["not_after"], zona) if zona is not None else (d["not_after"] or "")[:10] or None
    if zona is not None and d["caduca_el"]:
        # Los días que faltan se cuentan por fechas del despacho («caduca el 12, hoy es 7: faltan 5»), no por horas: es lo que se espera leer y lo que cuenta el cliente.
        d["dias_restantes"] = (date.fromisoformat(d["caduca_el"]) - ahora.astimezone(zona).date()).days
    d["emitido_el"] = fecha_local(d["not_before"], zona) if zona is not None else (d["not_before"] or "")[:10] or None
    d["cliente_nombre"] = None
    if d.get("cliente_titular_id"):
        cl = conn.execute("SELECT nombre, email FROM clientes_fiscales WHERE id = ?", (d["cliente_titular_id"],)).fetchone()
        d["cliente_nombre"], d["cliente_email"] = (cl["nombre"], cl["email"]) if cl else (None, None)
    return d


def obtener(tenant_id: int, certificado_id: int, ahora: datetime | None = None) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM certificados WHERE id = ? AND tenant_id = ?", (certificado_id, tenant_id)).fetchone()
        return _enriquecer(conn, f, ahora or _ahora(), _zona_del_despacho(tenant_id)) if f else None
    finally:
        conn.close()


def listar(tenant_id: int, *, q: str | None = None, temporal: str | None = None, operativo: str | None = None, incluir_archivados: bool = False, ahora: datetime | None = None, limite: int = 500,
           cliente_fiscal_id: int | None = None, plazo: str | None = None) -> list[dict]:
    """`plazo`: `caducados`, `mes` (caducan en ≤ 30 días), `tres_meses` (31-90), `vigentes` (> 90) o `sin_fecha`: los mismos grupos que las tarjetas del panel."""
    donde, p = ["tenant_id = ?"], [tenant_id]
    if cliente_fiscal_id:
        donde.append("cliente_titular_id = ?"); p.append(cliente_fiscal_id)
    if operativo:
        donde.append("estado_operativo = ?"); p.append(operativo)
    elif not incluir_archivados:
        donde.append("estado_operativo NOT IN ('archivado', 'sustituido')")
    if q:
        donde.append("(lower(sujeto) LIKE ? OR lower(emisor) LIKE ? OR lower(COALESCE(nif_confirmado, nif_sugerido, '')) LIKE ? OR lower(numero_serie) LIKE ?)")
        like = f"%{q.lower().strip()}%"
        p += [like, like, like, like]
        donde[-1] = donde[-1][:-1] + " OR lower(COALESCE((SELECT nombre FROM clientes_fiscales cf WHERE cf.id = certificados.cliente_titular_id), '')) LIKE ?)"
        p.append(like)
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT * FROM certificados WHERE {' AND '.join(donde)} ORDER BY not_after IS NULL, not_after LIMIT ?", [*p, max(1, min(limite, 2000))]).fetchall()
        zona = _zona_del_despacho(tenant_id)
        res = [_enriquecer(conn, f, ahora or _ahora(), zona) for f in filas]
    finally:
        conn.close()
    def _en_plazo(c) -> bool:
        d = c["dias_restantes"]
        if plazo == "sin_fecha":
            return c["temporal"] == "desconocido" or d is None
        if c["temporal"] == "desconocido" or d is None:
            return False
        return {"caducados": c["temporal"] == "caducado", "mes": c["temporal"] != "caducado" and d <= 30, "tres_meses": c["temporal"] != "caducado" and 30 < d <= 90,
                "vigentes": c["temporal"] != "caducado" and d > 90}.get(plazo, True)
    return [c for c in res if (not temporal or c["temporal"] == temporal) and (not plazo or _en_plazo(c))]


# --- Evaluaciones, datos del custodio, estado operativo ----------------------------------------------------------------------------------------
def registrar_evaluacion(tenant_id: int, usuario_id: int, certificado_id: int, dimension: str, resultado: str, *, detalle: str | None = None, metodo: str = "manual") -> None:
    """Anota el resultado de una comprobación (en el MVP, manual y con su fecha). Sin comprobación, la dimensión sigue como «no comprobada»."""
    _exigir(usuario_id, tenant_id)
    if dimension not in RESULTADOS or resultado not in RESULTADOS[dimension]:
        raise ValueError("Dimensión o resultado no válidos.")
    detalle = _sin_secretos(detalle, "Detalle")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM certificados WHERE id = ? AND tenant_id = ?", (certificado_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe ese certificado.")
        conn.execute("INSERT INTO certificados_evaluaciones (certificado_id, dimension, resultado, metodo, detalle, comprobado_por, comprobado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (certificado_id, dimension, resultado, metodo, detalle, usuario_id, db.now_iso()))
        _evento(conn, tenant_id, certificado_id, usuario_id, f"evaluacion_{dimension}", {"resultado": resultado, "metodo": metodo})
        conn.commit()
    finally:
        conn.close()


def comprobar_ahora(tenant_id: int, usuario_id: int, certificado_id: int, *, verificar=None) -> dict:
    """Comprueba la cadena de confianza y la revocación del certificado (app/certificados_verificacion.py) y anota los dos resultados como evaluaciones automáticas, con su fecha y detalle. Un
    fallo de red o una CA desconocida se anotan como «indeterminada», nunca como «válida». `ValueError` si el certificado se dio de alta a mano y no hay archivo que comprobar."""
    _exigir(usuario_id, tenant_id)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT der FROM certificados WHERE id = ? AND tenant_id = ?", (certificado_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None:
        raise ValueError("No existe ese certificado.")
    if not f["der"]:
        raise ValueError("Este certificado se dio de alta a mano: no hay archivo que comprobar. Impórtalo para poder hacerlo automáticamente.")
    if verificar is None:
        from . import certificados_verificacion
        verificar = certificados_verificacion.verificar
    try:
        r = verificar(bytes(f["der"]))
    except Exception:  # noqa: BLE001 -- un certificado raro o un fallo inesperado no debe romper la pantalla: queda como indeterminada
        logger.exception("Fallo al comprobar el certificado %s", certificado_id)
        r = {"cadena": ("indeterminada", "No se pudo completar la comprobación."), "revocacion": ("indeterminada", "No se pudo completar la comprobación.", "automatica")}
    registrar_evaluacion(tenant_id, usuario_id, certificado_id, "cadena", r["cadena"][0], detalle=r["cadena"][1][:300], metodo="automatica")
    registrar_evaluacion(tenant_id, usuario_id, certificado_id, "revocacion", r["revocacion"][0], detalle=r["revocacion"][1][:300], metodo=r["revocacion"][2])
    return {"cadena": r["cadena"][0], "revocacion": r["revocacion"][0]}


def actualizar_datos(tenant_id: int, usuario_id: int, certificado_id: int, *, custodio_id: int | None = ..., nif_confirmado: str | None = ..., tipo_titular: str | None = ...,
                     ubicacion_externa: str | None = ..., notas: str | None = ...) -> None:
    """Datos que confirma o completa el custodio (lo que no se pasa no se toca)."""
    _exigir(usuario_id, tenant_id)
    sets, vals = [], []
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM certificados WHERE id = ? AND tenant_id = ?", (certificado_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe ese certificado.")
        if custodio_id is not ...:
            if custodio_id:
                nucleo._usuario_de_tenant(conn, custodio_id, tenant_id, "El custodio")
            sets.append("custodio_id = ?"); vals.append(custodio_id or None)
        if nif_confirmado is not ...:
            nif = (nif_confirmado or "").strip().upper()
            if nif and not _NIF.fullmatch(nif):
                raise ValueError("El NIF/CIF/NIE no tiene un formato válido.")
            sets.append("nif_confirmado = ?"); vals.append(nif or None)
        if tipo_titular is not ...:
            if tipo_titular not in (None, "", "persona_fisica", "persona_juridica", "representante"):
                raise ValueError("Tipo de titular no válido.")
            sets.append("tipo_titular = ?"); vals.append(tipo_titular or None)
        if ubicacion_externa is not ...:
            sets.append("ubicacion_externa = ?"); vals.append(_sin_secretos(ubicacion_externa, "Ubicación"))
        if notas is not ...:
            sets.append("notas = ?"); vals.append(_sin_secretos(notas, "Notas"))
        if sets:
            conn.execute(f"UPDATE certificados SET {', '.join(sets)}, version = version + 1, actualizado_en = ? WHERE id = ?", [*vals, db.now_iso(), certificado_id])
            _evento(conn, tenant_id, certificado_id, usuario_id, "datos_actualizados", {"campos": [s.split(" = ")[0] for s in sets]})
        conn.commit()
    finally:
        conn.close()


def cambiar_estado_operativo(tenant_id: int, usuario_id: int, certificado_id: int, nuevo: str, motivo: str | None = None) -> None:
    """inventariado → autorizado → suspendido ↔ autorizado, y cualquiera → archivado. `sustituido` solo lo pone el cierre de una renovación.
    Autorizar exige un certificado no caducado, y suspender o archivar, un motivo."""
    _exigir(usuario_id, tenant_id)
    if nuevo not in OPERATIVOS or nuevo == "sustituido":
        raise ValueError("Estado operativo no válido.")
    c = obtener(tenant_id, certificado_id)
    if c is None:
        raise ValueError("No existe ese certificado.")
    if c["estado_operativo"] in ("sustituido", "archivado") and nuevo != "archivado":
        raise ValueError("Un certificado sustituido o archivado ya no se puede reactivar: importa el vigente.")
    if nuevo == "autorizado" and c["temporal"] == "caducado":
        raise ValueError("No se puede autorizar un certificado caducado.")
    if nuevo in ("suspendido", "archivado") and not (motivo or "").strip():
        raise ValueError("Indica el motivo.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE certificados SET estado_operativo = ?, version = version + 1, actualizado_en = ? WHERE id = ? AND tenant_id = ?", (nuevo, db.now_iso(), certificado_id, tenant_id))
        _evento(conn, tenant_id, certificado_id, usuario_id, f"estado_{nuevo}", {"anterior": c["estado_operativo"], "motivo": (motivo or "").strip()[:300] or None})
        conn.commit()
    finally:
        conn.close()


# --- Dependencias (qué servicio de qué cliente usa cada certificado) ------------------------------------------------------------------------
def vincular(tenant_id: int, usuario_id: int, certificado_id: int, *, cliente_fiscal_id: int | None, servicio: str, autorizacion: str, vigente_desde: str | None = None, vigente_hasta: str | None = None) -> int:
    """Registra que el certificado se usa para un servicio (acceso a un buzón, firma, presentación) de un cliente. `autorizacion` es la representación o el mandato que lo permite."""
    _exigir(usuario_id, tenant_id)
    if servicio not in dict(SERVICIOS):
        raise ValueError("Servicio no válido.")
    autorizacion = _sin_secretos(autorizacion, "Autorización")
    if not autorizacion:
        raise ValueError("Indica la autorización o representación que permite este uso.")
    desde = (vigente_desde or date.today().isoformat())[:10]
    hasta = (vigente_hasta or "")[:10] or None
    for v in (desde, hasta):
        if v:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError("Las fechas deben tener el formato AAAA-MM-DD.") from None
    if hasta and hasta < desde:
        raise ValueError("La autorización no puede acabar antes de empezar.")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM certificados WHERE id = ? AND tenant_id = ?", (certificado_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe ese certificado.")
        if cliente_fiscal_id and conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe ese cliente en tu despacho.")
        if conn.execute("SELECT 1 FROM certificados_vinculos WHERE certificado_id = ? AND estado = 'activo' AND servicio = ? AND COALESCE(cliente_fiscal_id, 0) = ?", (certificado_id, servicio, cliente_fiscal_id or 0)).fetchone():
            raise ValueError("Ese uso ya está registrado para este certificado.")
        cur = conn.execute("INSERT INTO certificados_vinculos (tenant_id, certificado_id, cliente_fiscal_id, servicio, autorizacion, vigente_desde, vigente_hasta, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, certificado_id, cliente_fiscal_id, servicio, autorizacion, desde, hasta, usuario_id, db.now_iso()))
        _evento(conn, tenant_id, certificado_id, usuario_id, "vinculo_creado", {"cliente_fiscal_id": cliente_fiscal_id, "servicio": servicio})
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def retirar_vinculo(tenant_id: int, usuario_id: int, vinculo_id: int, motivo: str) -> None:
    _exigir(usuario_id, tenant_id)
    if not (motivo or "").strip():
        raise ValueError("Indica el motivo.")
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT * FROM certificados_vinculos WHERE id = ? AND tenant_id = ? AND estado = 'activo'", (vinculo_id, tenant_id)).fetchone()
        if v is None:
            raise ValueError("No existe ese uso activo.")
        conn.execute("UPDATE certificados_vinculos SET estado = 'retirado', retirado_en = ?, motivo_retirada = ? WHERE id = ?", (db.now_iso(), motivo.strip()[:300], vinculo_id))
        _evento(conn, tenant_id, v["certificado_id"], usuario_id, "vinculo_retirado", {"vinculo_id": vinculo_id, "motivo": motivo.strip()[:300]})
        conn.commit()
    finally:
        conn.close()


def vinculos(tenant_id: int, certificado_id: int, solo_activos: bool = False) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT v.*, c.nombre AS cliente_nombre FROM certificados_vinculos v LEFT JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id WHERE v.tenant_id = ? AND v.certificado_id = ? "
            f"{'AND v.estado = ' + chr(39) + 'activo' + chr(39) if solo_activos else ''} ORDER BY v.estado, v.id", (tenant_id, certificado_id))]
    finally:
        conn.close()


# --- Renovación y sustitución ------------------------------------------------------------------------------------------------------------------
def renovacion_activa(tenant_id: int, certificado_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM certificados_renovaciones WHERE tenant_id = ? AND certificado_id = ? AND fase NOT IN ('cerrado', 'cancelada')", (tenant_id, certificado_id)).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def renovaciones(tenant_id: int, certificado_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM certificados_renovaciones WHERE tenant_id = ? AND certificado_id = ? ORDER BY id DESC", (tenant_id, certificado_id))]
    finally:
        conn.close()


def abrir_renovacion(tenant_id: int, usuario_id: int, certificado_id: int, *, titular: str | None = None, notas: str | None = None, automatica: bool = False) -> int:
    """Abre el expediente de renovación (solo puede haber uno activo por certificado)."""
    if not automatica:
        _exigir(usuario_id, tenant_id)
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT estado_operativo FROM certificados WHERE id = ? AND tenant_id = ?", (certificado_id, tenant_id)).fetchone()
        if c is None:
            raise ValueError("No existe ese certificado.")
        if c["estado_operativo"] in ("sustituido", "archivado"):
            raise ValueError("Ese certificado ya está sustituido o archivado.")
        if conn.execute("SELECT 1 FROM certificados_renovaciones WHERE certificado_id = ? AND fase NOT IN ('cerrado', 'cancelada')", (certificado_id,)).fetchone():
            raise ValueError("Ese certificado ya tiene una renovación en curso.")
        cur = conn.execute("INSERT INTO certificados_renovaciones (tenant_id, certificado_id, titular, notas, abierta_por, abierta_en) VALUES (?, ?, ?, ?, ?, ?)",
                           (tenant_id, certificado_id, _sin_secretos(titular, "Titular"), _sin_secretos(notas, "Notas"), usuario_id or None, db.now_iso()))
        _evento(conn, tenant_id, certificado_id, usuario_id or None, "renovacion_abierta", {"automatica": automatica})
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ValueError("Ese certificado ya tiene una renovación en curso.") from None
        raise
    finally:
        conn.close()


def _renovacion(conn, tenant_id: int, renovacion_id: int):
    r = conn.execute("SELECT * FROM certificados_renovaciones WHERE id = ? AND tenant_id = ?", (renovacion_id, tenant_id)).fetchone()
    if r is None:
        raise ValueError("No existe esa renovación.")
    return r


def registrar_certificado_nuevo(tenant_id: int, usuario_id: int, renovacion_id: int, datos: bytes, *, huella: str | None = None) -> dict:
    """Importa el certificado nuevo (solo la parte pública), lo relaciona con el anterior (`sustituye_a`) y devuelve las diferencias de identidad y fechas para que
    el custodio las revise antes de validarlo. No elimina ni modifica el anterior. Deja la renovación en «obtenido»."""
    _exigir(usuario_id, tenant_id)
    conn = db.get_connection()
    try:
        r = _renovacion(conn, tenant_id, renovacion_id)
    finally:
        conn.close()
    if r["fase"] not in ("en_gestion", "pendiente_titular"):
        raise ValueError("Primero pasa la renovación a «en gestión» (o «pendiente del titular»).")
    res = importar(tenant_id, usuario_id, datos, huella=huella, origen="renovacion", sustituye_a=r["certificado_id"])
    if res["id"] == r["certificado_id"]:
        raise ValueError("Ese es el mismo certificado que se quiere renovar.")
    antiguo, nuevo = obtener(tenant_id, r["certificado_id"]), obtener(tenant_id, res["id"])
    diferencias = []
    for campo, etiqueta in (("sujeto", "Sujeto"), ("nif_sugerido", "NIF sugerido"), ("emisor", "Emisor"), ("tipo_titular_sugerido", "Tipo de titular")):
        if antiguo.get(campo) != nuevo.get(campo):
            diferencias.append({"campo": etiqueta, "antes": antiguo.get(campo), "ahora": nuevo.get(campo)})
    diferencias.append({"campo": "Válido hasta", "antes": antiguo["not_after"], "ahora": nuevo["not_after"]})
    conn = db.get_connection()
    try:
        conn.execute("UPDATE certificados SET sustituye_a = COALESCE(sustituye_a, ?) WHERE id = ?", (r["certificado_id"], res["id"]))
        conn.execute("UPDATE certificados_renovaciones SET nuevo_certificado_id = ?, fase = 'obtenido' WHERE id = ?", (res["id"], renovacion_id))
        _evento(conn, tenant_id, r["certificado_id"], usuario_id, "renovacion_obtenido", {"nuevo_certificado_id": res["id"], "diferencias": len(diferencias)})
        conn.commit()
    finally:
        conn.close()
    return {"nuevo_certificado_id": res["id"], "diferencias": diferencias}


def registrar_implantacion(tenant_id: int, usuario_id: int, renovacion_id: int, vinculo_id: int, resultado: str, nota: str | None = None) -> None:
    """Resultado de probar el certificado nuevo en un servicio concreto (por un procedimiento autorizado). Una prueba fallida mantiene la renovación abierta."""
    _exigir(usuario_id, tenant_id)
    if resultado not in ("correcta", "fallida"):
        raise ValueError("El resultado debe ser «correcta» o «fallida».")
    conn = db.get_connection()
    try:
        r = _renovacion(conn, tenant_id, renovacion_id)
        if r["fase"] not in ("validado", "implantado"):
            raise ValueError("Valida primero el certificado nuevo.")
        if conn.execute("SELECT 1 FROM certificados_vinculos WHERE id = ? AND certificado_id = ? AND estado = 'activo'", (vinculo_id, r["certificado_id"])).fetchone() is None:
            raise ValueError("Ese uso no es un servicio activo del certificado que se renueva.")
        conn.execute("INSERT INTO certificados_implantaciones (renovacion_id, vinculo_id, resultado, nota, comprobado_por, comprobado_en) VALUES (?, ?, ?, ?, ?, ?)",
                     (renovacion_id, vinculo_id, resultado, _sin_secretos(nota, "Nota"), usuario_id, db.now_iso()))
        _evento(conn, tenant_id, r["certificado_id"], usuario_id, "implantacion", {"vinculo_id": vinculo_id, "resultado": resultado})
        conn.commit()
    finally:
        conn.close()


def estado_implantacion(tenant_id: int, renovacion_id: int) -> list[dict]:
    """Para cada servicio activo del certificado que se renueva, el resultado de la última prueba (`None` si aún no se ha probado)."""
    conn = db.get_connection()
    try:
        r = _renovacion(conn, tenant_id, renovacion_id)
        res = []
        for v in conn.execute("SELECT v.*, c.nombre AS cliente_nombre FROM certificados_vinculos v LEFT JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id WHERE v.certificado_id = ? AND v.estado = 'activo' ORDER BY v.id", (r["certificado_id"],)):
            u = conn.execute("SELECT resultado, nota, comprobado_en FROM certificados_implantaciones WHERE renovacion_id = ? AND vinculo_id = ? ORDER BY id DESC LIMIT 1", (renovacion_id, v["id"])).fetchone()
            res.append({"vinculo_id": v["id"], "cliente": v["cliente_nombre"], "servicio": v["servicio"], "resultado": u["resultado"] if u else None, "nota": u["nota"] if u else None, "comprobado_en": u["comprobado_en"] if u else None})
        return res
    finally:
        conn.close()


def avanzar_renovacion(tenant_id: int, usuario_id: int, renovacion_id: int, a_fase: str, nota: str | None = None, *, confirmar_sin_servicios: bool = False) -> None:
    """Mueve la renovación a la fase siguiente. «obtenido» solo se alcanza importando el certificado nuevo; «implantado» exige que todos los servicios activos estén probados
    con éxito; «cerrado» sustituye el certificado y traslada los servicios al nuevo. «cancelada» se puede pedir en cualquier momento antes de cerrar."""
    _exigir(usuario_id, tenant_id)
    conn = db.get_connection()
    try:
        r = _renovacion(conn, tenant_id, renovacion_id)
    finally:
        conn.close()
    actual = r["fase"]
    if a_fase == "cancelada":
        if actual in ("cerrado", "cancelada"):
            raise ValueError("Esa renovación ya está terminada.")
    elif a_fase not in _TRANSICIONES.get(actual, set()):
        raise ValueError(f"No se puede pasar de «{actual}» a «{a_fase}».")
    if a_fase == "obtenido":
        if not r["nuevo_certificado_id"]:
            raise ValueError("Para marcar «obtenido» hay que importar el certificado nuevo (solo la parte pública).")
    if a_fase == "validado" and not r["nuevo_certificado_id"]:
        raise ValueError("Falta el certificado nuevo.")
    if a_fase == "implantado":
        estado = estado_implantacion(tenant_id, renovacion_id)
        if not estado and not confirmar_sin_servicios:
            raise ValueError("Este certificado no tiene servicios registrados: confirma expresamente que no hay nada que implantar.")
        pendientes = [e for e in estado if e["resultado"] != "correcta"]
        if pendientes:
            raise ValueError(f"Quedan {len(pendientes)} servicio(s) sin una prueba correcta: la renovación sigue abierta.")
    conn = db.get_connection()
    try:
        if a_fase == "cerrado":
            _cerrar(conn, tenant_id, usuario_id, r)
        else:
            conn.execute("UPDATE certificados_renovaciones SET fase = ?, cerrada_en = ? WHERE id = ?", (a_fase, db.now_iso() if a_fase == "cancelada" else None, renovacion_id))
        if nota and nota.strip():
            conn.execute("UPDATE certificados_renovaciones SET notas = COALESCE(notas || char(10), '') || ? WHERE id = ?", (_sin_secretos(nota, "Nota"), renovacion_id))
        _evento(conn, tenant_id, r["certificado_id"], usuario_id, f"renovacion_{a_fase}", {"renovacion_id": renovacion_id})
        conn.commit()
    finally:
        conn.close()


def _cerrar(conn, tenant_id: int, usuario_id: int, r) -> None:
    ahora = db.now_iso()
    antiguo = conn.execute("SELECT estado_operativo FROM certificados WHERE id = ?", (r["certificado_id"],)).fetchone()
    for v in conn.execute("SELECT * FROM certificados_vinculos WHERE certificado_id = ? AND estado = 'activo'", (r["certificado_id"],)).fetchall():
        conn.execute("INSERT INTO certificados_vinculos (tenant_id, certificado_id, cliente_fiscal_id, servicio, autorizacion, vigente_desde, vigente_hasta, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (tenant_id, r["nuevo_certificado_id"], v["cliente_fiscal_id"], v["servicio"], v["autorizacion"], date.today().isoformat(), v["vigente_hasta"], usuario_id, ahora))
        conn.execute("UPDATE certificados_vinculos SET estado = 'retirado', retirado_en = ?, motivo_retirada = 'Sustituido por un certificado nuevo' WHERE id = ?", (ahora, v["id"]))
    conn.execute("UPDATE certificados SET estado_operativo = 'sustituido', version = version + 1, actualizado_en = ? WHERE id = ?", (ahora, r["certificado_id"]))
    if antiguo and antiguo["estado_operativo"] == "autorizado":
        conn.execute("UPDATE certificados SET estado_operativo = 'autorizado', version = version + 1, actualizado_en = ? WHERE id = ?", (ahora, r["nuevo_certificado_id"]))
    conn.execute("UPDATE certificados_renovaciones SET fase = 'cerrado', cerrada_en = ? WHERE id = ?", (ahora, r["id"]))


# --- Riesgos (RF-10) ---------------------------------------------------------------------------------------------------------------------------
def riesgos(tenant_id: int, hoy: date | None = None, horizonte_dias: int = 90) -> list[dict]:
    """Obligaciones fiscales pendientes que dependen de un certificado que caducará antes (o ya ha caducado), o cuya cobertura es desconocida o no está autorizada. Cada riesgo trae
    su causa; «sin mapa de dependencias» se muestra como «cobertura desconocida», nunca como correcto."""
    hoy = hoy or date.today()
    hasta = (hoy + timedelta(days=horizonte_dias)).isoformat()
    conn = db.get_connection()
    try:
        venc = conn.execute("SELECT v.id, v.cliente_fiscal_id, v.modelo, v.periodo, v.fecha_limite, c.nombre AS cliente FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id "
                            "WHERE v.tenant_id = ? AND v.estado = 'pendiente' AND v.papelera_en IS NULL AND substr(v.fecha_limite, 1, 10) <= ? ORDER BY v.fecha_limite", (tenant_id, hasta)).fetchall()
        res = []
        # Una sola consulta con los certificados que dan servicio a cada cliente (antes, una por obligación pendiente: con miles de vencimientos eran miles de consultas).
        por_cliente: dict[int, list] = {}
        for f in conn.execute(
                "SELECT b.cliente_fiscal_id, c.id, c.sujeto, c.not_after, c.estado_operativo FROM certificados_vinculos b JOIN certificados c ON c.id = b.certificado_id WHERE b.tenant_id = ? AND b.estado = 'activo' "
                "AND b.servicio IN ('presentacion', 'acceso_buzon') AND c.estado_operativo NOT IN ('archivado', 'sustituido') ORDER BY b.id", (tenant_id,)):
            por_cliente.setdefault(f["cliente_fiscal_id"], []).append(f)
        for v in venc:
            lim = v["fecha_limite"][:10]
            certs = por_cliente.get(v["cliente_fiscal_id"], [])
            base = {"vencimiento_id": v["id"], "cliente_fiscal_id": v["cliente_fiscal_id"], "cliente": v["cliente"], "modelo": v["modelo"], "periodo": v["periodo"], "fecha_limite": lim}
            if not certs:
                res.append(base | {"tipo": "cobertura_desconocida", "motivo": "No hay ningún certificado registrado para presentar o acceder en nombre de este cliente.", "certificado_id": None})
                continue
            validos = [c for c in certs if c["estado_operativo"] != "suspendido" and (c["not_after"] or "9999")[:10] >= lim]
            if validos:
                continue
            if all(c["estado_operativo"] == "suspendido" for c in certs):
                res.append(base | {"tipo": "sin_alternativa", "motivo": "El certificado asociado está suspendido y no hay otro autorizado.", "certificado_id": certs[0]["id"]})
            else:
                c = min(certs, key=lambda x: x["not_after"] or "")
                res.append(base | {"tipo": "caduca_antes", "motivo": f"El certificado caduca el {(c['not_after'] or '')[:10]}, antes del vencimiento, y no hay otro vigente.", "certificado_id": c["id"]})
        return res
    finally:
        conn.close()


# --- Avisos escalonados (RF-11/12) ----------------------------------------------------------------------------------------------------------
def _destinatarios(conn, tenant_id: int, c: dict, umbral: int) -> list[int]:
    """Custodio (siempre; si no hay, los supervisores); coordinación desde 15 días; dirección desde 7 si el certificado da servicio o su cobertura es desconocida."""
    supervisores = [u for u in db.usuarios_de_tenant(tenant_id) if db.es_supervisor_tenant(u)]
    gestores = [u for u in db.usuarios_de_tenant(tenant_id) if db.es_gestor_fichajes(u)]
    dest = [c["custodio_id"]] if c["custodio_id"] else list(supervisores)
    if umbral <= 15:
        dest += gestores + supervisores[:1]
    if umbral <= 7:
        dest += supervisores
    return list(dict.fromkeys(u for u in dest if u))


def _texto_aviso(c: dict, umbral: int) -> tuple[str, str]:
    nombre = c["nombre_comun"] or c["sujeto"] or f"#{c['id']}"
    if umbral <= 0:
        return "Certificado caducado", f"{nombre} caducó el {(c['not_after'] or '')[:10]}. Los servicios que lo usan dejan de funcionar hasta que se sustituya."
    return f"Certificado: caduca en {c['dias_restantes']} día(s)", f"{nombre} caduca el {(c['not_after'] or '')[:10]}." + (" Sin servicios registrados: cobertura desconocida." if not c["vinculos_activos"] else f" Da servicio a {c['vinculos_activos']} uso(s).")


def _abrir_renovaciones_automaticas(ahora: datetime, tenant_id: int | None) -> int:
    """Abre la renovación de los certificados que entran en los últimos 60 días y aún no tienen una en curso ni un sucesor."""
    conn = db.get_connection()
    try:
        donde, p = ("AND tenant_id = ?", [tenant_id]) if tenant_id else ("", [])
        filas = [dict(f) for f in conn.execute(
            f"SELECT id, tenant_id, not_after FROM certificados WHERE estado_operativo IN ('inventariado', 'autorizado', 'suspendido') AND not_after IS NOT NULL {donde} "
            "AND NOT EXISTS (SELECT 1 FROM certificados_renovaciones r WHERE r.certificado_id = certificados.id AND r.fase NOT IN ('cerrado', 'cancelada')) "
            "AND NOT EXISTS (SELECT 1 FROM certificados n WHERE n.sustituye_a = certificados.id)", p)]
    finally:
        conn.close()
    n = 0
    for f in filas:
        d = dias_restantes(f["not_after"], ahora)
        if d is not None and d <= UMBRAL_RENOVACION:
            try:
                abrir_renovacion(f["tenant_id"], 0, f["id"], automatica=True)
                n += 1
            except ValueError:
                pass
    return n


def revisar_avisos(tenant_id: int | None = None, ahora: datetime | None = None, enviar_correo: bool = True) -> dict:
    """Una pasada (la lanza el hilo diario): abre solas las renovaciones a ≤ 60 días y manda los avisos de umbral pendientes. Cada aviso se envía una sola vez por certificado,
    umbral, destinatario y canal; si un certificado entra ya dentro de un umbral, solo se avisa el vigente y los anteriores se anotan como omitidos. Devuelve contadores."""
    from . import avisos, correo_diseno, notificaciones, notificaciones_email
    ahora = ahora or _ahora()
    motor = {}       # despachos con el motor de avisos v2: el aviso interno (campana/push) lo da él, con acuse y escalado; el correo sigue como siempre
    res = {"avisos": 0, "omitidos": 0, "renovaciones": _abrir_renovaciones_automaticas(ahora, tenant_id), "fallidos": 0}
    conn = db.get_connection()
    try:
        donde, p = ("AND tenant_id = ?", [tenant_id]) if tenant_id else ("", [])
        for f in conn.execute(f"SELECT * FROM certificados WHERE estado_operativo IN ('inventariado', 'autorizado', 'suspendido') AND not_after IS NOT NULL {donde}", p).fetchall():
            c = _enriquecer(conn, f, ahora, _zona_del_despacho(f["tenant_id"]))
            tid, dias = c["tenant_id"], c["dias_restantes"]
            cruzados = [u for u in UMBRALES if (c["temporal"] == "caducado" if u == 0 else dias is not None and dias <= u)]
            if not cruzados:
                continue
            actual = min(cruzados)
            for u in cruzados:
                for d in _destinatarios(conn, tid, c, u):
                    for canal in ("interno", "correo"):
                        if canal == "interno" and motor.setdefault(tid, avisos.activo(tid)):
                            continue
                        previo = conn.execute("SELECT estado FROM certificados_avisos WHERE certificado_id = ? AND umbral = ? AND destinatario_id = ? AND canal = ? AND version_fecha = ?", (c["id"], u, d, canal, c["not_after"])).fetchone()
                        if previo and previo["estado"] != "fallido":
                            continue                      # ya enviado u omitido; un envío fallido se reintenta en la pasada siguiente
                        if u != actual:
                            conn.execute("INSERT INTO certificados_avisos (tenant_id, certificado_id, umbral, destinatario_id, canal, version_fecha, estado, creado_en) VALUES (?, ?, ?, ?, ?, ?, 'omitido', ?)", (tid, c["id"], u, d, canal, c["not_after"], db.now_iso()))
                            res["omitidos"] += 1
                            continue
                        titulo, cuerpo = _texto_aviso(c, u)
                        estado, detalle = "entregado", None
                        conn.commit()                       # sin escritura abierta en esta conexión: el envío usa la suya y no debe chocar con ella
                        try:
                            if canal == "interno":
                                notificaciones.crear_y_enviar(d, "certificado", titulo, cuerpo, url=f"/certificados/{c['id']}", datos={"tipo": "certificado", "certificado_id": c["id"]})
                            else:
                                usuario = db.obtener_usuario(d)
                                if not (enviar_correo and usuario is not None and usuario["email"] and notificaciones_email.configurado()):
                                    continue
                                plano, html = correo_diseno.construir(titulo, ["Revisa el certificado en Guilda Work."], boton=("Abrir el certificado", correo_diseno.BASE + f"/certificados/{c['id']}"),
                                                                       aviso="Este aviso no incluye datos del certificado: entra para verlos.", preencabezado=titulo)
                                notificaciones_email._enviar(usuario["email"], titulo, plano, html)
                                estado = "aceptado_por_proveedor"
                        except Exception as e:  # noqa: BLE001  (un destinatario con problemas no frena al resto; queda anotado para revisar)
                            estado, detalle = "fallido", f"{type(e).__name__}: {e}"[:300]
                            res["fallidos"] += 1
                        conn.execute("INSERT INTO certificados_avisos (tenant_id, certificado_id, umbral, destinatario_id, canal, version_fecha, estado, detalle, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                                     "ON CONFLICT(certificado_id, umbral, destinatario_id, canal, version_fecha) DO UPDATE SET estado = excluded.estado, detalle = excluded.detalle, creado_en = excluded.creado_en",
                                     (tid, c["id"], u, d, canal, c["not_after"], estado, detalle, db.now_iso()))
                        if estado != "fallido":
                            res["avisos"] += 1
            conn.commit()
    finally:
        conn.close()
    return res


# --- Tipos de certificado y alta rápida (sin archivo) ------------------------------------------------------------------------------------------
# Lo normal es NO subir el certificado: el despacho apunta de quién es, de qué tipo y cuándo caduca. `anios` es la duración habitual del tipo, solo orientativa: con la fecha de emisión
# se propone la de caducidad y siempre se puede corregir.
TIPOS_CERTIFICADO: dict[str, dict] = {
    "fnmt_persona_fisica": {"nombre": _l("FNMT · Persona física"), "emisor": "FNMT-RCM", "titular": "persona_fisica", "anios": 4},
    "fnmt_representante": {"nombre": _l("FNMT · Representante de persona jurídica"), "emisor": "FNMT-RCM", "titular": "representante", "anios": 2},
    "fnmt_representante_sin_personalidad": {"nombre": _l("FNMT · Representante de entidad sin personalidad jurídica"), "emisor": "FNMT-RCM", "titular": "representante", "anios": 2},
    "dnie": {"nombre": _l("DNI electrónico"), "emisor": "Dirección General de la Policía", "titular": "persona_fisica", "anios": None},
    "accv": {"nombre": _l("ACCV (Comunitat Valenciana)"), "emisor": "ACCV", "titular": None, "anios": None},
    "izenpe": {"nombre": _l("Izenpe (País Vasco)"), "emisor": "Izenpe", "titular": None, "anios": None},
    "camerfirma": {"nombre": _l("Camerfirma"), "emisor": "Camerfirma", "titular": None, "anios": None},
    "firmaprofesional": {"nombre": _l("Firmaprofesional"), "emisor": "Firmaprofesional", "titular": None, "anios": None},
    "otro": {"nombre": _l("Otro certificado"), "emisor": None, "titular": None, "anios": None},
}


def _zona_del_despacho(tenant_id: int):
    from zoneinfo import ZoneInfo
    t = db.obtener_tenant(tenant_id)
    try:
        return ZoneInfo(t["zona_horaria"] if t is not None and "zona_horaria" in t.keys() and t["zona_horaria"] else "Europe/Madrid")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Europe/Madrid")


def fin_de_dia_utc(dia: date, tenant_id: int) -> str:
    """El instante (UTC) en que acaba ese día en la zona del despacho: un certificado que «caduca el 7 de noviembre» vale hasta el final de ese día, no hasta las 00:00."""
    local = datetime(dia.year, dia.month, dia.day, 23, 59, 59, tzinfo=_zona_del_despacho(tenant_id))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fecha_local(iso_utc: str | None, zona) -> str | None:
    d = _dt(iso_utc)
    return d.astimezone(zona).strftime("%Y-%m-%d") if d is not None else None


def sumar_anios(dia: date, n: int) -> date:
    try:
        return dia.replace(year=dia.year + n)
    except ValueError:                              # 29 de febrero
        return dia.replace(year=dia.year + n, day=28)


def _fecha(valor, campo: str, *, obligatoria: bool = False) -> date | None:
    t = (valor or "").strip() if isinstance(valor, str) else ""
    if not t:
        if obligatoria:
            raise ValueError(f"{campo}: indica la fecha.")
        return None
    try:
        d = date.fromisoformat(t[:10])
    except ValueError:
        raise ValueError(f"{campo}: usa el formato AAAA-MM-DD.") from None
    if not 2000 <= d.year <= 2100:
        raise ValueError(f"{campo}: esa fecha no parece correcta.")
    return d


def caducidad_propuesta(tipo: str, emitido: date | None) -> date | None:
    """La caducidad habitual del tipo contando desde la emisión (orientativa), o `None` si no se puede proponer."""
    anios = (TIPOS_CERTIFICADO.get(tipo) or {}).get("anios")
    return sumar_anios(emitido, anios) if (anios and emitido) else None


def alta_rapida(tenant_id: int, usuario_id: int, *, tipo: str = "otro", caduca=None, emitido=None, cliente_fiscal_id: int | None = None, titular: str | None = None, nif: str | None = None,
                serie: str | None = None, custodio_id: int | None = None, ubicacion: str | None = None, notas: str | None = None, avisar_cliente: bool | None = None) -> dict:
    """Apunta un certificado SIN archivo: de quién es, de qué tipo y cuándo caduca (con la fecha de emisión se propone la de caducidad del tipo). Si es de un cliente, sus datos se rellenan
    solos. Todo lo demás es opcional y se puede completar o corregir después. Queda como «datos introducidos a mano»."""
    _exigir(usuario_id, tenant_id)
    if tipo not in TIPOS_CERTIFICADO:
        raise ValueError("Elige un tipo de certificado.")
    preset = TIPOS_CERTIFICADO[tipo]
    ini = _fecha(emitido, "Fecha de emisión")
    fin = _fecha(caduca, "Fecha de caducidad") or caducidad_propuesta(tipo, ini)
    if fin is None:
        raise ValueError("Indica cuándo caduca (o la fecha de emisión, para que la calculemos).")
    if ini is not None and fin < ini:
        raise ValueError("La caducidad no puede ser anterior a la emisión.")
    conn = db.get_connection()
    try:
        cliente = None
        if cliente_fiscal_id:
            cliente = conn.execute("SELECT id, nombre, nif FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone()
            if cliente is None:
                raise ValueError("No existe ese cliente en tu despacho.")
        nombre = (titular or "").strip()[:200] or (cliente["nombre"] if cliente else "")
        if not nombre:
            raise ValueError("Indica a quién pertenece: elige un cliente o escribe el nombre del titular.")
        escrito = (nif or "").strip().upper().replace(" ", "").replace("-", "")
        if escrito and not _NIF.fullmatch(escrito):
            raise ValueError("El NIF/CIF/NIE no tiene un formato válido.")
        # El NIF de la ficha del cliente se hereda tal cual: un NIF mal puesto en su ficha no debe impedir apuntar el certificado.
        nif_txt = escrito or (cliente["nif"] if cliente and cliente["nif"] else "")
        nif_txt = (nif_txt or "").upper().replace(" ", "").replace("-", "")
        if nif_txt and not _NIF.fullmatch(nif_txt):
            nif_txt = ""
        if custodio_id:
            nucleo._usuario_de_tenant(conn, custodio_id, tenant_id, "El custodio")
        ubicacion, notas = _sin_secretos(ubicacion, "Ubicación"), _sin_secretos(notas, "Notas")
        serie_txt = (serie or "").strip().lower().replace(":", "").replace(" ", "")[:80] or None
        not_after = fin_de_dia_utc(fin, tenant_id)
        huella = hashlib.sha256(f"manual|{cliente_fiscal_id or 0}|{tipo}|{not_after}|{nombre.lower()}|{serie_txt or ''}".encode()).hexdigest()
        existente = conn.execute("SELECT id FROM certificados WHERE tenant_id = ? AND huella_sha256 = ?", (tenant_id, huella)).fetchone()
        if existente:
            return {"id": existente["id"], "nuevo": False, "huella": huella}
        ahora = db.now_iso()
        cur = conn.execute(
            "INSERT INTO certificados (tenant_id, huella_sha256, verificado, origen, numero_serie, emisor, sujeto, nombre_comun, not_before, not_after, nif_sugerido, nif_confirmado, tipo_titular_sugerido, tipo_titular, "
            "tipo_certificado, cliente_titular_id, avisar_cliente, custodio_id, ubicacion_externa, notas, creado_por, creado_en, actualizado_en) VALUES (?, ?, 0, 'manual', ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, huella, serie_txt, preset["emisor"], nombre, nombre, fin_de_dia_utc(ini, tenant_id).replace("23:59:59", "00:00:00") if ini else None, not_after, nif_txt or None,
             preset["titular"], preset["titular"], tipo, cliente_fiscal_id, None if avisar_cliente is None else int(bool(avisar_cliente)),
             custodio_id or (usuario_id if es_custodio(usuario_id, tenant_id) else None), ubicacion, notas, usuario_id, ahora, ahora))
        cid = cur.lastrowid
        _evento(conn, tenant_id, cid, usuario_id, "alta_rapida", {"tipo": tipo, "caduca": fin.isoformat(), "cliente_fiscal_id": cliente_fiscal_id})
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "nuevo": True, "huella": huella}


_CAMPOS_DE_ARCHIVO = ("titular", "tipo", "caduca", "emitido", "serie")


def editar(tenant_id: int, usuario_id: int, certificado_id: int, *, titular=..., tipo=..., caduca=..., emitido=..., serie=..., nif=..., cliente_fiscal_id=..., custodio_id=...,
           ubicacion=..., notas=..., avisar_cliente=...) -> None:
    """Corrige los datos de un certificado (lo que no se pasa no se toca). Titular, tipo, fechas y serie solo se editan si el certificado se apuntó a mano; si se importó de un archivo,
    esos datos salen del propio certificado y no se tocan. Cambiar la fecha de caducidad reinicia los avisos de esa fecha (cada fecha tiene los suyos)."""
    _exigir(usuario_id, tenant_id)
    sets, vals = [], []
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT * FROM certificados WHERE id = ? AND tenant_id = ?", (certificado_id, tenant_id)).fetchone()
        if c is None:
            raise ValueError("No existe ese certificado.")
        pasados = {"titular": titular, "tipo": tipo, "caduca": caduca, "emitido": emitido, "serie": serie}
        if c["verificado"] and any(v is not ... for v in pasados.values()):
            raise ValueError("Este certificado se importó de un archivo: su titular, tipo, fechas y serie salen del propio certificado y no se editan.")
        if titular is not ...:
            nombre = (titular or "").strip()[:200]
            if not nombre:
                raise ValueError("El titular no puede quedar vacío.")
            sets += ["sujeto = ?", "nombre_comun = ?"]; vals += [nombre, nombre]
        if tipo is not ...:
            if tipo not in TIPOS_CERTIFICADO:
                raise ValueError("Elige un tipo de certificado.")
            sets += ["tipo_certificado = ?", "emisor = ?"]; vals += [tipo, TIPOS_CERTIFICADO[tipo]["emisor"] or c["emisor"]]
            if TIPOS_CERTIFICADO[tipo]["titular"]:
                sets.append("tipo_titular = ?"); vals.append(TIPOS_CERTIFICADO[tipo]["titular"])
        ini = _fecha(emitido, "Fecha de emisión") if emitido is not ... else None
        fin = _fecha(caduca, "Fecha de caducidad", obligatoria=True) if caduca is not ... else None
        if emitido is not ...:
            sets.append("not_before = ?"); vals.append(fin_de_dia_utc(ini, tenant_id).replace("23:59:59", "00:00:00") if ini else None)
        if fin is not None:
            sets.append("not_after = ?"); vals.append(fin_de_dia_utc(fin, tenant_id))
            nuevo = _dt(fin_de_dia_utc(fin, tenant_id))
            if nuevo and c["not_before"] and nuevo < _dt(c["not_before"]) and emitido is ...:
                raise ValueError("La caducidad no puede ser anterior a la emisión.")
        if serie is not ...:
            sets.append("numero_serie = ?"); vals.append((serie or "").strip().lower().replace(":", "").replace(" ", "")[:80] or None)
        if nif is not ...:
            n = (nif or "").strip().upper().replace(" ", "").replace("-", "")
            if n and not _NIF.fullmatch(n):
                raise ValueError("El NIF/CIF/NIE no tiene un formato válido.")
            sets.append("nif_confirmado = ?"); vals.append(n or None)
        if cliente_fiscal_id is not ...:
            if cliente_fiscal_id and conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone() is None:
                raise ValueError("No existe ese cliente en tu despacho.")
            sets.append("cliente_titular_id = ?"); vals.append(cliente_fiscal_id or None)
        if custodio_id is not ...:
            if custodio_id:
                nucleo._usuario_de_tenant(conn, custodio_id, tenant_id, "El custodio")
            sets.append("custodio_id = ?"); vals.append(custodio_id or None)
        if ubicacion is not ...:
            sets.append("ubicacion_externa = ?"); vals.append(_sin_secretos(ubicacion, "Ubicación"))
        if notas is not ...:
            sets.append("notas = ?"); vals.append(_sin_secretos(notas, "Notas"))
        if avisar_cliente is not ...:
            sets.append("avisar_cliente = ?"); vals.append(None if avisar_cliente is None else int(bool(avisar_cliente)))
        if not sets:
            return
        conn.execute(f"UPDATE certificados SET {', '.join(sets)}, version = version + 1, actualizado_en = ? WHERE id = ?", [*vals, db.now_iso(), certificado_id])
        _evento(conn, tenant_id, certificado_id, usuario_id, "editado", {"campos": [x.split(" = ")[0] for x in sets]})
        conn.commit()
    finally:
        conn.close()


def renovado(tenant_id: int, usuario_id: int, certificado_id: int, nueva_caducidad, *, emitido=None, serie=None, funciona: bool = False) -> dict:
    """«Ya está renovado»: apunta el certificado nuevo con su caducidad y cierra la renovación en un paso, sin subir nada. Hereda titular, tipo, cliente, NIF, custodio y servicios del
    anterior (que pasa a «sustituido» con su historial). Si el anterior daba servicio a algún cliente, hay que confirmar que el nuevo funciona (`funciona`): queda anotado como confirmado
    a mano, sin prueba por servicio; para probarlos uno a uno está el proceso de renovación completo."""
    _exigir(usuario_id, tenant_id)
    ant = obtener(tenant_id, certificado_id)
    if ant is None:
        raise ValueError("No existe ese certificado.")
    if ant["estado_operativo"] in ("sustituido", "archivado"):
        raise ValueError("Ese certificado ya está sustituido o archivado.")
    fin = _fecha(nueva_caducidad, "Nueva caducidad", obligatoria=True)
    if fin_de_dia_utc(fin, tenant_id) <= (ant["not_after"] or ""):
        raise ValueError("La nueva caducidad tiene que ser posterior a la del certificado actual.")
    if ant["vinculos_activos"] and not funciona:
        raise ValueError(f"Este certificado da servicio a {ant['vinculos_activos']} uso(s): confirma que el nuevo funciona o usa el proceso de renovación completo, que los prueba uno a uno.")
    ini = _fecha(emitido, "Fecha de emisión")
    serie_txt = (serie or "").strip().lower().replace(":", "").replace(" ", "")[:80] or None
    reno = renovacion_activa(tenant_id, certificado_id)
    rid = reno["id"] if reno else abrir_renovacion(tenant_id, usuario_id, certificado_id)
    ahora = db.now_iso()
    not_after = fin_de_dia_utc(fin, tenant_id)
    huella = hashlib.sha256(f"manual|renovado|{certificado_id}|{not_after}|{serie_txt or ''}".encode()).hexdigest()
    conn = db.get_connection()
    try:
        existente = conn.execute("SELECT id FROM certificados WHERE tenant_id = ? AND huella_sha256 = ?", (tenant_id, huella)).fetchone()
        if existente:
            raise ValueError("Ese certificado renovado ya está apuntado.")
        cur = conn.execute(
            "INSERT INTO certificados (tenant_id, huella_sha256, verificado, origen, numero_serie, emisor, sujeto, nombre_comun, not_before, not_after, nif_confirmado, nif_sugerido, tipo_titular_sugerido, tipo_titular, "
            "tipo_certificado, cliente_titular_id, avisar_cliente, custodio_id, ubicacion_externa, notas, sustituye_a, creado_por, creado_en, actualizado_en) VALUES (?, ?, 0, 'renovacion', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, huella, serie_txt, ant["emisor"], ant["sujeto"], ant["nombre_comun"], fin_de_dia_utc(ini, tenant_id).replace("23:59:59", "00:00:00") if ini else None, not_after, ant["nif_confirmado"] or ant["nif_sugerido"],
             ant["tipo_titular_sugerido"], ant["tipo_titular"], ant["tipo_certificado"], ant["cliente_titular_id"], ant["avisar_cliente"], ant["custodio_id"], ant["ubicacion_externa"], ant["notas"],
             certificado_id, usuario_id, ahora, ahora))
        nuevo_id = cur.lastrowid
        conn.execute("UPDATE certificados_renovaciones SET nuevo_certificado_id = ? WHERE id = ?", (nuevo_id, rid))
        _evento(conn, tenant_id, certificado_id, usuario_id, "renovacion_rapida", {"nuevo_certificado_id": nuevo_id, "caduca": fin.isoformat(), "confirmado_a_mano": bool(ant["vinculos_activos"])})
        conn.commit()
    finally:
        conn.close()
    # La renovación recorre sus fases como siempre (así la auditoría y el cierre son los de siempre); los servicios se dan por probados con lo confirmado a mano.
    if renovacion_activa(tenant_id, certificado_id)["fase"] == "sin_iniciar":
        avanzar_renovacion(tenant_id, usuario_id, rid, "en_gestion")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE certificados_renovaciones SET fase = 'obtenido' WHERE id = ?", (rid,))
        conn.commit()
    finally:
        conn.close()
    avanzar_renovacion(tenant_id, usuario_id, rid, "validado")
    for v in vinculos(tenant_id, certificado_id, solo_activos=True):
        registrar_implantacion(tenant_id, usuario_id, rid, v["id"], "correcta", "Confirmado a mano al marcar el certificado como renovado")
    avanzar_renovacion(tenant_id, usuario_id, rid, "implantado", confirmar_sin_servicios=True)
    avanzar_renovacion(tenant_id, usuario_id, rid, "cerrado")
    return {"id": nuevo_id, "anterior_id": certificado_id}


# --- Resumen para el panel -------------------------------------------------------------------------------------------------------------------------
def resumen(tenant_id: int, ahora: datetime | None = None) -> dict:
    """Cuántos certificados hay en cada situación (los que están en uso): para las tarjetas de la pantalla."""
    r = {"total": 0, "caducados": 0, "mes": 0, "tres_meses": 0, "vigentes": 0, "sin_fecha": 0, "sin_cliente": 0}
    for c in listar(tenant_id, ahora=ahora):
        r["total"] += 1
        d = c["dias_restantes"]
        if c["temporal"] == "desconocido" or d is None:
            r["sin_fecha"] += 1
        elif c["temporal"] == "caducado":
            r["caducados"] += 1
        elif d <= 30:
            r["mes"] += 1
        elif d <= 90:
            r["tres_meses"] += 1
        else:
            r["vigentes"] += 1
        if not c["cliente_titular_id"]:
            r["sin_cliente"] += 1
    return r


def texto_dias(d: int | None) -> str:
    """«hoy», «mañana», «en 12 días», «ayer», «hace 3 días» (en español: lo traducen las pantallas con su propio texto)."""
    if d is None:
        return ""
    if d == 0:
        return "hoy"
    if d == 1:
        return "mañana"
    if d > 1:
        return f"en {d} días"
    return "ayer" if d == -1 else f"hace {-d} días"


# --- Avisos y portal del cliente (configurables por el despacho) -------------------------------------------------------------------------------
MARCAS_PLANTILLA = ("cliente", "tipo", "caduca", "dias", "cuando", "despacho", "instrucciones", "enlace")
MAX_AVISOS_ANTES, MAX_AVISOS_DESPUES = 6, 4


def config(tenant_id: int) -> dict:
    """Cómo informa el despacho a sus clientes de la caducidad de SU certificado. Todo apagado por defecto: ni se avisa ni se enseña nada al cliente hasta que el despacho lo active."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM certificados_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    base = {"avisar_cliente": False, "mostrar_en_portal": False, "dias_antes": [60, 30, 15, 7], "dias_despues": [3], "asunto": "", "cuerpo": "", "instrucciones": ""}
    if f is None:
        return base
    try:
        antes, despues = db._lista_de_dias(f["dias_antes"], 0, 365, 99), sorted(db._lista_de_dias(f["dias_despues"], 1, 90, 99))
    except ValueError:
        antes, despues = base["dias_antes"], base["dias_despues"]
    return {"avisar_cliente": bool(f["avisar_cliente"]), "mostrar_en_portal": bool(f["mostrar_en_portal"]), "dias_antes": antes, "dias_despues": despues,
            "asunto": f["asunto"] or "", "cuerpo": f["cuerpo"] or "", "instrucciones": f["instrucciones"] or ""}


def guardar_config(tenant_id: int, usuario_id: int, *, avisar_cliente: bool, mostrar_en_portal: bool, dias_antes, dias_despues, asunto: str = "", cuerpo: str = "", instrucciones: str = "") -> dict:
    """Solo la dirección del despacho: manda correos a sus clientes. `dias_antes`: de 0 (el mismo día) a 365, hasta 6 avisos; `dias_despues`: de 1 a 90, hasta 4."""
    from . import acceso
    u = db.obtener_usuario(usuario_id)
    if u is None or u["tenant_id"] != tenant_id or not acceso.es_directivo(usuario_id):
        raise ValueError("Solo la dirección del despacho (supervisores) puede cambiar los avisos a clientes.")
    antes = db._lista_de_dias(dias_antes, 0, 365, MAX_AVISOS_ANTES)
    despues = sorted(db._lista_de_dias(dias_despues, 1, 90, MAX_AVISOS_DESPUES))
    asunto, cuerpo, instrucciones = (asunto or "").strip()[:150], (cuerpo or "").strip()[:2000], (instrucciones or "").strip()[:600]
    if bool(asunto) != bool(cuerpo):
        raise ValueError("Para usar tu propio texto rellena el asunto y el mensaje (o deja los dos vacíos).")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO certificados_config (tenant_id, avisar_cliente, mostrar_en_portal, dias_antes, dias_despues, asunto, cuerpo, instrucciones) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(tenant_id) DO UPDATE SET avisar_cliente = excluded.avisar_cliente, mostrar_en_portal = excluded.mostrar_en_portal, dias_antes = excluded.dias_antes, "
                     "dias_despues = excluded.dias_despues, asunto = excluded.asunto, cuerpo = excluded.cuerpo, instrucciones = excluded.instrucciones",
                     (tenant_id, int(bool(avisar_cliente)), int(bool(mostrar_en_portal)), ",".join(map(str, antes)), ",".join(map(str, despues)), asunto, cuerpo, instrucciones))
        from . import auditoria
        auditoria.registrar(tenant_id, usuario_id, "certificado.config_avisos", "despacho", tenant_id, {"avisar_cliente": bool(avisar_cliente), "mostrar_en_portal": bool(mostrar_en_portal), "dias_antes": antes, "dias_despues": despues}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return config(tenant_id)


def _informa_al_cliente(c: dict) -> bool:
    """¿Se informa al cliente de este certificado? Lo decide cada certificado («nunca» lo excluye) y, si no, el ajuste del despacho."""
    return bool(c.get("cliente_titular_id")) and c.get("avisar_cliente") != 0


def estado_para_cliente(c: dict, cfg: dict) -> str:
    """`caducado`, `pronto` (dentro del primer aviso) o `vigente`: lo que entiende el cliente."""
    if c["temporal"] == "caducado":
        return "caducado"
    d = c["dias_restantes"]
    return "pronto" if d is not None and d <= max([60, *cfg["dias_antes"]]) else "vigente"


def visibles_para_cliente(cliente_fiscal_id: int, ahora: datetime | None = None) -> list[dict]:
    """Los certificados de ESTE cliente que su despacho decide enseñarle en su portal (con el ajuste activo y sin haberlo excluido)."""
    conn = db.get_connection()
    try:
        cl = conn.execute("SELECT tenant_id FROM clientes_fiscales WHERE id = ? AND papelera_en IS NULL", (cliente_fiscal_id,)).fetchone()
    finally:
        conn.close()
    if cl is None:
        return []
    cfg = config(cl["tenant_id"])
    if not cfg["mostrar_en_portal"]:
        return []
    res = []
    for c in listar(cl["tenant_id"], cliente_fiscal_id=cliente_fiscal_id, ahora=ahora):
        if _informa_al_cliente(c) and c["temporal"] != "desconocido":
            res.append({"id": c["id"], "tipo": c["tipo_certificado"] or "otro", "titular": c["nombre_comun"] or c["sujeto"], "caduca_el": c["caduca_el"], "dias": c["dias_restantes"],
                        "estado": estado_para_cliente(c, cfg), "ayuda_solicitada": bool(c["ayuda_solicitada_en"])})
    return res


def valores_plantilla(c: dict, cliente_nombre: str, gestoria: str, cfg: dict, enlace: str | None) -> dict:
    d = c["dias_restantes"] or 0
    return {"cliente": cliente_nombre, "tipo": str((TIPOS_CERTIFICADO.get(c["tipo_certificado"] or "otro") or TIPOS_CERTIFICADO["otro"])["nombre"]), "caduca": c["caduca_el"] or "", "dias": str(abs(d)),
            "cuando": texto_dias(d), "despacho": gestoria, "instrucciones": cfg["instrucciones"], "enlace": enlace or ""}


def _enviar_a_cliente(c: dict, cfg: dict, gestoria: str) -> None:
    """Un correo al cliente (en su idioma, con el texto del despacho si lo tiene). Lanza si no se puede enviar."""
    from . import notificaciones_email, portal_recordatorios
    cliente = db.obtener_cliente_fiscal_por_id(c["cliente_titular_id"])
    with portal_recordatorios._en_idioma(cliente["idioma"] if cliente is not None and "idioma" in cliente.keys() else "es"):
        notificaciones_email.enviar_aviso_certificado(
            (c["cliente_email"] or "").strip(), c["cliente_nombre"] or "", str((TIPOS_CERTIFICADO.get(c["tipo_certificado"] or "otro") or TIPOS_CERTIFICADO["otro"])["nombre"]),
            c["caduca_el"] or "", c["dias_restantes"] or 0, portal_recordatorios.url_portal() if cfg["mostrar_en_portal"] else None, gestoria, cfg["instrucciones"],
            plantilla=(cfg["asunto"], cfg["cuerpo"]) if cfg["asunto"] and cfg["cuerpo"] else None,
            tenant_id=cliente["tenant_id"] if cliente is not None else None)


def _gestoria(tenant_id: int) -> str:
    t = db.obtener_tenant(tenant_id)
    return (t["nombre"] if t is not None else "") or ""


def avisar_clientes(tenant_id: int | None = None, ahora: datetime | None = None) -> dict:
    """Una pasada: avisa por correo a los clientes cuyo certificado se acerca a su caducidad (o ya ha caducado), según la configuración de su despacho. Un aviso por certificado, fecha de
    caducidad y antelación; si el certificado se apunta ya dentro de un umbral, solo el vigente (los anteriores quedan «omitidos»). No avisa si el cliente no tiene correo, si el
    certificado se excluyó, si el cliente pidió ayuda, o si la renovación ya tiene el certificado nuevo."""
    from . import notificaciones_email
    ahora = ahora or _ahora()
    res = {"clientes": 0, "omitidos": 0, "fallidos": 0}
    if not notificaciones_email.configurado():
        return res
    conn = db.get_connection()
    try:
        tenants = [f["tenant_id"] for f in conn.execute("SELECT tenant_id FROM certificados_config WHERE avisar_cliente = 1" + (" AND tenant_id = ?" if tenant_id else ""), (tenant_id,) if tenant_id else ())]
    finally:
        conn.close()
    for tid in tenants:
        cfg = config(tid)
        gestoria = _gestoria(tid)
        for c in listar(tid, ahora=ahora):
            if not _informa_al_cliente(c) or not (c.get("cliente_email") or "").strip() or c["ayuda_solicitada_en"] or c["renovacion"] in ("obtenido", "validado", "implantado") or c["dias_restantes"] is None:
                continue
            d = c["dias_restantes"]
            if c["temporal"] == "caducado":
                cruzados = [-t for t in cfg["dias_despues"] if -d >= t]
                actual = min(cruzados) if cruzados else None                              # el más reciente (mayor t) = el más negativo
                previos = [t for t in cfg["dias_antes"]]
            else:
                cruzados = [t for t in cfg["dias_antes"] if d <= t]
                actual, previos = (min(cruzados) if cruzados else None), []
            conn = db.get_connection()
            try:
                for t in [*previos, *cruzados]:
                    if t != actual and not conn.execute("SELECT 1 FROM certificados_avisos_cliente WHERE certificado_id = ? AND dias = ? AND version_fecha = ?", (c["id"], t, c["not_after"])).fetchone():
                        conn.execute("INSERT INTO certificados_avisos_cliente (tenant_id, certificado_id, dias, version_fecha, estado, creado_en) VALUES (?, ?, ?, ?, 'omitido', ?)", (tid, c["id"], t, c["not_after"], db.now_iso()))
                        res["omitidos"] += 1
                conn.commit()
                if actual is None:
                    continue
                previo = conn.execute("SELECT estado FROM certificados_avisos_cliente WHERE certificado_id = ? AND dias = ? AND version_fecha = ?", (c["id"], actual, c["not_after"])).fetchone()
                if previo and previo["estado"] != "fallido":
                    continue
                estado, detalle = "enviado", None
                try:
                    _enviar_a_cliente(c, cfg, gestoria)
                except Exception as e:  # noqa: BLE001  (un cliente con el buzón roto no frena al resto; se reintenta)
                    estado, detalle = "fallido", f"{type(e).__name__}: {e}"[:300]
                    res["fallidos"] += 1
                conn.execute("INSERT INTO certificados_avisos_cliente (tenant_id, certificado_id, dias, version_fecha, estado, detalle, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?) "
                             "ON CONFLICT(certificado_id, dias, version_fecha) DO UPDATE SET estado = excluded.estado, detalle = excluded.detalle, creado_en = excluded.creado_en",
                             (tid, c["id"], actual, c["not_after"], estado, detalle, db.now_iso()))
                if estado == "enviado":
                    res["clientes"] += 1
                    _evento(conn, tid, c["id"], None, "aviso_cliente", {"dias": actual})
                conn.commit()
            finally:
                conn.close()
    return res


def enviar_aviso_ahora(tenant_id: int, usuario_id: int, certificado_id: int) -> None:
    """Manda ya el aviso al cliente de este certificado (sin esperar a su fecha), por ejemplo tras hablar con él. Queda anotado."""
    from . import notificaciones_email
    _exigir(usuario_id, tenant_id)
    c = obtener(tenant_id, certificado_id)
    if c is None:
        raise ValueError("No existe ese certificado.")
    if not c["cliente_titular_id"]:
        raise ValueError("Este certificado no está asociado a un cliente.")
    if not (c.get("cliente_email") or "").strip():
        raise ValueError("El cliente no tiene correo en su ficha: añádelo para poder avisarle.")
    if not notificaciones_email.configurado():
        raise ValueError("El correo saliente no está configurado en el servidor.")
    _enviar_a_cliente(c, config(tenant_id), _gestoria(tenant_id))
    conn = db.get_connection()
    try:
        _evento(conn, tenant_id, certificado_id, usuario_id, "aviso_cliente_manual", {"dias": c["dias_restantes"]})
        conn.commit()
    finally:
        conn.close()


def pedir_ayuda(cliente_fiscal_id: int, certificado_id: int) -> bool:
    """El cliente, desde su portal, pide ayuda para renovar. Abre la renovación si no la hay, avisa al custodio y a la dirección, y deja de insistirle. Devuelve False si no procede."""
    visibles = {c["id"]: c for c in visibles_para_cliente(cliente_fiscal_id)}
    if certificado_id not in visibles:
        return False
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT * FROM certificados WHERE id = ?", (certificado_id,)).fetchone()
        conn.execute("UPDATE certificados SET ayuda_solicitada_en = COALESCE(ayuda_solicitada_en, ?), version = version + 1 WHERE id = ?", (db.now_iso(), certificado_id))
        _evento(conn, c["tenant_id"], certificado_id, None, "ayuda_solicitada_por_el_cliente", {"cliente_fiscal_id": cliente_fiscal_id})
        conn.commit()
        tid, custodio = c["tenant_id"], c["custodio_id"]
    finally:
        conn.close()
    if renovacion_activa(tid, certificado_id) is None:
        try:
            abrir_renovacion(tid, 0, certificado_id, automatica=True)
        except ValueError:
            pass
    try:
        from . import acceso, notificaciones
        cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
        destinatarios = list(dict.fromkeys(([custodio] if custodio else []) + [u for u in db.usuarios_de_tenant(tid) if db.es_supervisor_tenant(u)]))
        for u in destinatarios:
            notificaciones.crear_y_enviar(u, "certificado", "Un cliente pide ayuda con su certificado", f"{cliente['nombre'] if cliente else ''} quiere ayuda para renovar su certificado digital.", url=f"/certificados/{certificado_id}",
                                          datos={"tipo": "certificado", "certificado_id": certificado_id})
    except Exception:  # noqa: BLE001
        pass
    return True


def avisos_del_cliente(tenant_id: int, certificado_id: int, limite: int = 20) -> list[dict]:
    """Los avisos que se han mandado (o intentado) al cliente por este certificado, los más recientes primero."""
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT dias, version_fecha, estado, detalle, creado_en FROM certificados_avisos_cliente WHERE tenant_id = ? AND certificado_id = ? ORDER BY id DESC LIMIT ?",
                                              (tenant_id, certificado_id, limite))]
    finally:
        conn.close()


def vista_previa(tenant_id: int, cfg: dict | None = None) -> dict:
    """El correo tal como lo verá un cliente (con datos de ejemplo), en español."""
    from . import notificaciones_email
    cfg = cfg or config(tenant_id)
    ejemplo = {"cliente": "Marta Puig", "tipo": str(TIPOS_CERTIFICADO["fnmt_persona_fisica"]["nombre"]), "caduca": (date.today() + timedelta(days=30)).isoformat(), "dias": "30", "cuando": "en 30 días",
               "despacho": _gestoria(tenant_id) or "Tu despacho", "instrucciones": cfg["instrucciones"], "enlace": "https://…/portal"}
    if cfg["asunto"] and cfg["cuerpo"]:
        return {"asunto": notificaciones_email.rellenar_plantilla(cfg["asunto"], ejemplo), "cuerpo": notificaciones_email.rellenar_plantilla(cfg["cuerpo"], ejemplo)}
    asunto, cuerpo = notificaciones_email.textos_aviso_certificado(ejemplo["cliente"], ejemplo["tipo"], ejemplo["caduca"], 30, ejemplo["despacho"], cfg["instrucciones"], tiene_enlace=True)
    return {"asunto": asunto, "cuerpo": "\n\n".join(cuerpo)}


INTERVALO_SEGUNDOS = 6 * 3600


def bucle() -> None:
    """Hilo del servidor: revisa los avisos de caducidad y abre las renovaciones. Es idempotente, así que repetir la pasada o reiniciar el servicio no duplica nada."""
    import time
    from . import salud
    salud.registrar_ok("certificados_avisos", INTERVALO_SEGUNDOS * 2, "arrancado")
    time.sleep(120)
    while True:
        try:
            r = revisar_avisos()
            c = avisar_clientes()
            r["fallidos"] += c["fallidos"]
            salud.registrar_ok("certificados_avisos", INTERVALO_SEGUNDOS * 2, f"{r['avisos']} avisos, {r['renovaciones']} renovaciones, {c['clientes']} avisos a clientes")
            if r["fallidos"]:
                salud.registrar_error("certificados_avisos", INTERVALO_SEGUNDOS * 2, f"{r['fallidos']} avisos no se han podido enviar (se reintentan en la próxima pasada)")
        except Exception as e:  # noqa: BLE001
            salud.registrar_error("certificados_avisos", INTERVALO_SEGUNDOS * 2, f"{type(e).__name__}: {e}")
        time.sleep(INTERVALO_SEGUNDOS)
