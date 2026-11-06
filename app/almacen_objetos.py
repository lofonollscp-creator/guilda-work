"""Almacén de objetos para el contenido de los documentos: los PDF, fotos y adjuntos salen de la base de datos y viven en un almacenamiento compatible con S3 (AWS S3, un proveedor europeo con API S3, MinIO…) o en una carpeta del servidor.

**Qué cambia y qué no.** Las tablas siguen igual y la columna `contenido` sigue existiendo: lo que se guarda fuera se deja vacío en la fila y queda anotado en `objetos_almacenados` (qué fila, qué clave, cuántos bytes y su SHA-256). Quien lee
un documento pasa por `contenido()`, que mira la columna y, si está vacía y la fila está anotada, lo trae del almacén; el resto del código no se entera de dónde vive. Lo que se guarda es EXACTAMENTE lo que había en la columna: si el despacho
tiene el cifrado activado, ya va sellado con su clave, y en el almacén solo hay datos ilegibles.

**Nunca se pierde nada.** Si el almacén no responde al guardar, el contenido se queda en la base como siempre. Al migrar lo existente (`scripts/migrar_a_objetos.py`) cada objeto se lee de vuelta y se compara su SHA-256 ANTES de vaciar la columna.
Con la variable `GUILDA_OBJETOS` sin definir todo funciona como hasta ahora.

Configuración (variables de entorno):
- `GUILDA_OBJETOS`: `s3` o `fichero` (vacío = desactivado).
- `fichero`: `GUILDA_OBJETOS_DIR` (carpeta; con permisos solo del servicio y en las copias de seguridad).
- `s3`: `GUILDA_S3_BUCKET`, `GUILDA_S3_ACCESS_KEY`, `GUILDA_S3_SECRET_KEY`, y opcionalmente `GUILDA_S3_ENDPOINT` (por defecto `s3.amazonaws.com`), `GUILDA_S3_REGION`, `GUILDA_S3_SECURE` (1/0), `GUILDA_S3_PREFIJO`,
  `GUILDA_S3_RETENCION_DIAS` y `GUILDA_S3_RETENCION_MODO` (`GOVERNANCE` por defecto, o `COMPLIANCE`) para el bloqueo de borrado (el bucket debe crearse con Object Lock).
  Lo ideal es que la aplicación use unas credenciales que puedan escribir y leer pero NO borrar (el borrado de huérfanos lo hace el script con otras).

Claves: `<prefijo>t<despacho>/<tabla>/<id de la fila>-<12 primeros caracteres del SHA-256>`: cada versión de un contenido es un objeto distinto, así que reescribir (sellar, rotar claves) nunca pisa el anterior hasta que la transacción de la base
confirma; los que dejan de estar anotados los recoge `scripts/migrar_a_objetos.py limpiar`."""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from . import db

logger = logging.getLogger("guilda")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS objetos_almacenados (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    tabla TEXT NOT NULL,
    fila_id INTEGER NOT NULL,
    clave TEXT NOT NULL,
    almacen TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    verificado_en TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_objetos_fila ON objetos_almacenados(tenant_id, tabla, fila_id);
CREATE INDEX IF NOT EXISTS idx_objetos_clave ON objetos_almacenados(clave);
"""

# Las tablas cuyo contenido se puede llevar al almacén: (columna del despacho, tipo MIME). Cada una necesita lectura y escritura pasando por `contenido()` / `ofrecer()` / `preparar()`.
TABLAS = {
    "cliente_documentos": {"mime": "tipo_mime"},
    "documentos": {"mime": "tipo_mime"},
    "vencimientos_fiscales_documentos": {"mime": "tipo_mime"},
    "correo_adjuntos": {"mime": "tipo_mime"},
}
# Cómo averiguar el despacho de cada fila: (JOIN necesario, expresión del tenant). Lo usan scripts/migrar_a_objetos.py y el panel del backoffice.
DESPACHO = {
    "cliente_documentos": ("", "t.tenant_id"),
    "documentos": ("", "t.tenant_id"),
    "vencimientos_fiscales_documentos": ("JOIN vencimientos_fiscales v ON v.id = t.vencimiento_id", "v.tenant_id"),
    "correo_adjuntos": ("JOIN correo_mensajes m ON m.id = t.mensaje_id JOIN correo_cuentas c ON c.id = m.cuenta_id JOIN usuarios u ON u.id = c.usuario_id", "u.tenant_id"),
}
assert set(DESPACHO) == set(TABLAS), "cada tabla del almacén necesita su forma de saber el despacho"
_CLAVE_SEGURA = re.compile(r"^[A-Za-z0-9_./-]{1,512}$")


class ErrorAlmacenObjetos(Exception):
    pass


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


class Almacen(Protocol):
    nombre: str

    def poner(self, clave: str, datos: bytes, tipo_mime: str | None = None) -> None: ...
    def leer(self, clave: str) -> bytes: ...
    def tamano(self, clave: str) -> int | None: ...
    def borrar(self, clave: str) -> None: ...
    def listar(self, prefijo: str) -> list[tuple[str, int, float]]: ...     # (clave, bytes, fecha de modificación en segundos)


def _clave_valida(clave: str) -> str:
    if not _CLAVE_SEGURA.match(clave or "") or ".." in clave.split("/") or clave.startswith("/"):
        raise ErrorAlmacenObjetos(f"Clave de objeto no válida: {clave!r}")
    return clave


class AlmacenFichero:
    """Una carpeta del servidor (también para pruebas). Escribe a un fichero temporal y lo renombra: nunca queda un objeto a medias."""
    nombre = "fichero"

    def __init__(self, carpeta: str | Path):
        self.carpeta = Path(carpeta)

    def _ruta(self, clave: str) -> Path:
        ruta = (self.carpeta / _clave_valida(clave)).resolve()
        if self.carpeta.resolve() not in ruta.parents:
            raise ErrorAlmacenObjetos("La clave sale de la carpeta del almacén.")
        return ruta

    def poner(self, clave, datos, tipo_mime=None):
        ruta = self._ruta(clave)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(ruta.name + ".tmp")
        try:
            temporal.write_bytes(datos)
            os.chmod(temporal, 0o600)
            os.replace(temporal, ruta)
        except OSError as e:
            raise ErrorAlmacenObjetos(f"No se pudo escribir el objeto: {e}") from e

    def leer(self, clave):
        try:
            return self._ruta(clave).read_bytes()
        except OSError as e:
            raise ErrorAlmacenObjetos(f"No se pudo leer el objeto: {e}") from e

    def tamano(self, clave):
        try:
            return self._ruta(clave).stat().st_size
        except FileNotFoundError:
            return None
        except OSError as e:
            raise ErrorAlmacenObjetos(f"No se pudo consultar el objeto: {e}") from e

    def listar(self, prefijo):
        raiz = self.carpeta.resolve()
        base = (raiz / prefijo).resolve() if prefijo else raiz
        if raiz != base and raiz not in base.parents:
            return []
        return [(str(r.relative_to(raiz)), r.stat().st_size, r.stat().st_mtime) for r in sorted(base.rglob("*")) if r.is_file() and not r.name.endswith(".tmp")]

    def borrar(self, clave):
        try:
            self._ruta(clave).unlink(missing_ok=True)
        except OSError as e:
            raise ErrorAlmacenObjetos(f"No se pudo borrar el objeto: {e}") from e


class AlmacenS3:
    """Cualquier almacenamiento con API S3, con el SDK `minio` (que firma las peticiones con AWS Signature V4 y habla con AWS S3 igual que con MinIO)."""
    nombre = "s3"

    def __init__(self, bucket: str, acceso: str, secreto: str, endpoint: str = "s3.amazonaws.com", region: str | None = None, seguro: bool = True, prefijo: str = "",
                 retencion_dias: int = 0, retencion_modo: str = "GOVERNANCE", cliente=None):
        self.bucket, self.prefijo = bucket, prefijo
        self.retencion_dias, self.retencion_modo = retencion_dias, retencion_modo.upper()
        if cliente is None:
            try:
                from minio import Minio
            except ImportError as e:
                raise ErrorAlmacenObjetos("Falta el paquete «minio» para usar el almacén S3 (pip install minio).") from e
            cliente = Minio(endpoint, access_key=acceso, secret_key=secreto, region=region or None, secure=seguro)
        self.cliente = cliente

    def _k(self, clave: str) -> str:
        return self.prefijo + _clave_valida(clave)

    def poner(self, clave, datos, tipo_mime=None):
        argumentos = {}
        if self.retencion_dias > 0:
            from minio.retention import Retention
            argumentos["retention"] = Retention(self.retencion_modo, datetime.now(timezone.utc) + timedelta(days=self.retencion_dias))
        try:
            self.cliente.put_object(self.bucket, self._k(clave), io.BytesIO(datos), len(datos), content_type=tipo_mime or "application/octet-stream", **argumentos)
        except Exception as e:  # noqa: BLE001 -- el SDK lanza S3Error, urllib3, etc.
            raise ErrorAlmacenObjetos(f"No se pudo guardar el objeto en S3: {e}") from e

    def leer(self, clave):
        respuesta = None
        try:
            respuesta = self.cliente.get_object(self.bucket, self._k(clave))
            return respuesta.read()
        except Exception as e:  # noqa: BLE001
            raise ErrorAlmacenObjetos(f"No se pudo leer el objeto de S3: {e}") from e
        finally:
            if respuesta is not None:
                respuesta.close()
                respuesta.release_conn()

    def tamano(self, clave):
        try:
            return self.cliente.stat_object(self.bucket, self._k(clave)).size
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", "") in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return None
            raise ErrorAlmacenObjetos(f"No se pudo consultar el objeto en S3: {e}") from e

    def listar(self, prefijo):
        try:
            return [(o.object_name[len(self.prefijo):], o.size or 0, o.last_modified.timestamp() if o.last_modified else 0.0)
                    for o in self.cliente.list_objects(self.bucket, prefix=self.prefijo + prefijo, recursive=True) if not o.is_dir]
        except Exception as e:  # noqa: BLE001
            raise ErrorAlmacenObjetos(f"No se pudo listar el almacén S3: {e}") from e

    def borrar(self, clave):
        try:
            self.cliente.remove_object(self.bucket, self._k(clave))
        except Exception as e:  # noqa: BLE001
            raise ErrorAlmacenObjetos(f"No se pudo borrar el objeto de S3: {e}") from e


# --- Configuración ---------------------------------------------------------------------------------------------------------------------------------------

_instalado: Almacen | None = None
_instalado_fijo = False


def fijar_almacen(almacen: Almacen | None, *, fijo: bool = True) -> None:
    """Instala un almacén concreto (pruebas, scripts). `None` con `fijo=False` vuelve a leer la configuración del entorno."""
    global _instalado, _instalado_fijo
    _instalado, _instalado_fijo = almacen, fijo


def _desde_entorno() -> Almacen | None:
    tipo = os.environ.get("GUILDA_OBJETOS", "").strip().lower()
    if not tipo:
        return None
    if tipo == "fichero":
        carpeta = os.environ.get("GUILDA_OBJETOS_DIR", "").strip()
        if not carpeta:
            raise ErrorAlmacenObjetos("GUILDA_OBJETOS=fichero necesita GUILDA_OBJETOS_DIR.")
        return AlmacenFichero(carpeta)
    if tipo == "s3":
        e = os.environ.get
        faltan = [v for v in ("GUILDA_S3_BUCKET", "GUILDA_S3_ACCESS_KEY", "GUILDA_S3_SECRET_KEY") if not e(v)]
        if faltan:
            raise ErrorAlmacenObjetos("Faltan variables para el almacén S3: " + ", ".join(faltan))
        return AlmacenS3(e("GUILDA_S3_BUCKET"), e("GUILDA_S3_ACCESS_KEY"), e("GUILDA_S3_SECRET_KEY"), endpoint=e("GUILDA_S3_ENDPOINT", "s3.amazonaws.com"), region=e("GUILDA_S3_REGION") or None,
                         seguro=e("GUILDA_S3_SECURE", "1") not in ("0", "false", "no"), prefijo=e("GUILDA_S3_PREFIJO", ""), retencion_dias=int(e("GUILDA_S3_RETENCION_DIAS", "0") or 0),
                         retencion_modo=e("GUILDA_S3_RETENCION_MODO", "GOVERNANCE"))
    raise ErrorAlmacenObjetos(f"GUILDA_OBJETOS desconocido: {tipo!r} (usa «s3» o «fichero»).")


def almacen() -> Almacen | None:
    """El almacén configurado, o None si está desactivado. Si la configuración está mal, lanza `ErrorAlmacenObjetos` (para que se vea, no para que se guarde todo en la base sin avisar)."""
    global _instalado
    if _instalado_fijo:
        return _instalado
    if _instalado is None:
        _instalado = _desde_entorno()
    return _instalado


def activo() -> bool:
    try:
        return almacen() is not None
    except ErrorAlmacenObjetos:
        return False


def _necesario() -> Almacen:
    a = almacen()
    if a is None:
        raise ErrorAlmacenObjetos("El contenido de este documento está en el almacén de objetos, pero GUILDA_OBJETOS no está configurado en este servidor.")
    return a


# --- Registro ----------------------------------------------------------------------------------------------------------------------------------------------

def prefijo_de(tenant_id: int | None = None) -> str:
    return f"t{int(tenant_id)}/" if tenant_id is not None else ""


def clave_de(tenant_id: int, tabla: str, fila_id: int, sha256: str) -> str:
    return f"{prefijo_de(tenant_id)}{tabla}/{int(fila_id)}-{sha256[:12]}"


def _anotado(conn, tabla: str, fila_id: int):
    return conn.execute("SELECT * FROM objetos_almacenados WHERE tabla = ? AND fila_id = ?", (tabla, fila_id)).fetchone()


def esta_fuera(tabla: str, fila_id: int, conn=None) -> bool:
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        return _anotado(conn, tabla, fila_id) is not None
    finally:
        if propia:
            conn.close()


def contenido(tabla: str, fila_id: int, blob, conn=None) -> bytes:
    """El contenido tal como está guardado (sellado o no) de una fila de `tabla`: el de la columna si lo hay y, si está vacía y la fila está anotada, el del almacén (comprobando su SHA-256)."""
    if blob:
        return bytes(blob)
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        r = _anotado(conn, tabla, fila_id)
    finally:
        if propia:
            conn.close()
    if r is None:
        return b""
    datos = _necesario().leer(r["clave"])
    if hashlib.sha256(datos).hexdigest() != r["sha256"]:
        raise ErrorAlmacenObjetos(f"El objeto {r['clave']} no coincide con su huella: no se entrega.")
    return datos


def hidratar(tabla: str, fila):
    """La misma fila (como diccionario) con `contenido` traído del almacén si hace falta; sin tocar nada si la fila lo lleva en la columna."""
    if fila is None or fila["contenido"]:
        return fila
    d = {k: fila[k] for k in fila.keys()}
    d["contenido"] = contenido(tabla, fila["id"], fila["contenido"])
    return d


def _tamano_ok(a: Almacen, clave: str, esperado: int) -> bool:
    try:
        return a.tamano(clave) == esperado
    except ErrorAlmacenObjetos:
        return False


def _registrar(conn, tenant_id: int, tabla: str, fila_id: int, clave: str, almacen_nombre: str, datos: bytes) -> None:
    sha = hashlib.sha256(datos).hexdigest()
    ahora = db.now_iso()
    previo = _anotado(conn, tabla, fila_id)
    if previo is None:
        conn.execute("INSERT INTO objetos_almacenados (tenant_id, tabla, fila_id, clave, almacen, tamano_bytes, sha256, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (tenant_id, tabla, fila_id, clave, almacen_nombre, len(datos), sha, ahora))
    else:
        conn.execute("UPDATE objetos_almacenados SET clave = ?, almacen = ?, tamano_bytes = ?, sha256 = ?, creado_en = ?, verificado_en = NULL WHERE id = ?", (clave, almacen_nombre, len(datos), sha, ahora, previo["id"]))


def ofrecer(conn, tenant_id: int, tabla: str, fila_id: int, datos: bytes, tipo_mime: str | None = None) -> bool:
    """Tras insertar una fila con su contenido en la columna: lo lleva al almacén y deja la columna vacía (en la misma transacción de `conn`, que confirma quien llama). Devuelve True si salió.
    Si no hay almacén, o falla, el contenido se queda en la base: nunca se pierde. No se mueve lo vacío."""
    if tabla not in TABLAS or not datos:
        return False
    try:
        a = almacen()
        if a is None:
            return False
        clave = clave_de(tenant_id, tabla, fila_id, hashlib.sha256(datos).hexdigest())
        a.poner(clave, datos, tipo_mime)
        if not _tamano_ok(a, clave, len(datos)):
            raise ErrorAlmacenObjetos("El almacén no confirma el tamaño del objeto guardado.")
    except ErrorAlmacenObjetos as e:
        logger.error("Almacén de objetos: el contenido de %s #%s se queda en la base (%s)", tabla, fila_id, e)
        return False
    _registrar(conn, tenant_id, tabla, fila_id, clave, a.nombre, datos)
    conn.execute(f"UPDATE {tabla} SET contenido = ? WHERE id = ?", (b"", fila_id))
    return True


def preparar(conn, tenant_id: int | None, tabla: str, fila_id: int, datos: bytes, tipo_mime: str | None = None) -> bytes:
    """Para quien REESCRIBE el contenido de una fila existente (sellar, descifrar, rotar claves): si la fila ya vive en el almacén, lo reescribe allí y devuelve `b""` (lo que debe ir a la columna);
    si no, devuelve `datos` sin tocar nada. Si el almacén falla, lanza `ErrorAlmacenObjetos` (reescribir algo sellado en otro sitio y perderlo sería peor que no reescribirlo)."""
    previo = _anotado(conn, tabla, fila_id)
    if previo is None:
        return datos
    a = _necesario()
    clave = clave_de(previo["tenant_id"], tabla, fila_id, hashlib.sha256(datos).hexdigest())      # una clave nueva: si la transacción de quien llama no llega a confirmar, el objeto anterior sigue intacto
    a.poner(clave, datos, tipo_mime)
    if not _tamano_ok(a, clave, len(datos)):
        raise ErrorAlmacenObjetos("El almacén no confirma el tamaño del objeto reescrito.")
    _registrar(conn, previo["tenant_id"], tabla, fila_id, clave, a.nombre, datos)
    return b""


def quitar(conn, tabla: str, fila_id: int, borrar_objeto: bool = True) -> bool:
    """Olvida el objeto de una fila (y lo borra del almacén, si deja). Lo usan los borrados de documentos y el script de limpieza."""
    r = _anotado(conn, tabla, fila_id)
    if r is None:
        return False
    if borrar_objeto:
        try:
            _necesario().borrar(r["clave"])
        except ErrorAlmacenObjetos as e:
            logger.error("Almacén de objetos: no se pudo borrar %s (%s)", r["clave"], e)
            return False
    conn.execute("DELETE FROM objetos_almacenados WHERE id = ?", (r["id"],))
    return True


def resumen(conn=None) -> dict:
    """Cuántos objetos hay fuera y cuánto ocupan, por tabla."""
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        filas = conn.execute("SELECT tabla, COUNT(*) AS n, COALESCE(SUM(tamano_bytes), 0) AS bytes FROM objetos_almacenados GROUP BY tabla ORDER BY tabla").fetchall()
    finally:
        if propia:
            conn.close()
    return {f["tabla"]: {"objetos": f["n"], "bytes": f["bytes"]} for f in filas}
