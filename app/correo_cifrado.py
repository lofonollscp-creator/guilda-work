"""Correo cifrado con la clave del despacho (PLAN_MAESTRO.md §8.1; opcional: se activa por despacho desde *Seguridad del despacho*).

Cómo funciona (mismo cifrado de sobre que los documentos, app/cifrado_despacho.py):
  - Un mensaje entra **en claro** y pasa por todo lo que ocurre «al entrar» —reglas, categorías, vínculo con el cliente, archivado de adjuntos— exactamente
    como sin cifrado. **Como último paso se sella** con la clave PÚBLICA del despacho: no hace falta desbloqueo, así que el correo que llega de madrugada
    también se cifra. Los datos sensibles se guardan en un único bloque cifrado (`datos`, con su `sobre`) y lo que el nivel no deja en claro se vacía de sus columnas.
  - Los **niveles** (cada despacho elige uno y puede cambiarlo) deciden qué se queda en claro **en reposo**; no quitan ninguna función:

        | dato                                         | Laxo     | Medio    | Estricto |
        | cuerpo, HTML y contenido de adjuntos         | cifrado  | cifrado  | cifrado  |
        | asunto y nombre de los adjuntos              | en claro | cifrado  | cifrado  |
        | remitente, destinatarios y copia             | en claro | en claro | cifrado  |
        | categoría y cliente vinculados               | en claro | en claro | cifrado  |
        | fecha, carpeta, leído, destacado, tamaños    | en claro | en claro | en claro |

    El bloque cifrado lleva SIEMPRE una copia de todo, así que subir de nivel solo vacía columnas (sin clave) y bajarlo necesita el despacho desbloqueado.
  - **Leer** exige la clave privada: sesión desbloqueada o una concesión (API, MCP, aplicaciones OAuth). Sin ella los campos protegidos salen vacíos y el mensaje
    lleva `protegido = True` (la interfaz, la API y el asistente lo cuentan; nunca se devuelve como si no hubiera nada).
  - **Buscar**: lo cifrado ya no puede estar en el índice de texto completo (que guardaría el contenido en claro), así que en un despacho con correo cifrado la
    búsqueda se hace **en memoria** sobre los mensajes descifrados, que se conservan solo mientras haya clave (se olvidan al bloquear).
  - Los índices externos (Meilisearch, embeddings) dejan de recibir el correo de ese despacho, y se retira lo que ya tuvieran.

Límites (decirlo en la política de privacidad): el mensaje existe en claro un instante al entrar (y en el WAL de SQLite hasta el siguiente vaciado); lo que
una persona guarda o envía fuera del correo —un asunto copiado a un expediente, un borrador, un envío programado— no se cifra aquí; el `Message-ID` y las cabeceras
de hilo quedan en claro; en Medio y Estricto la clave de conversación es un HMAC opaco (con la clave del servidor, no la del despacho)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import bd as _bd
from . import cifrado_despacho as cd
from . import db

NIVELES = cd.NIVELES
CAMPOS_TEXTO = ("asunto", "remitente", "destinatarios", "cc", "cuerpo_texto", "cuerpo_html")
LIMITE_MEMORIA = 100000         # mensajes que se consideran como máximo en una búsqueda en memoria (≈ 3 KB cada uno en la caché ligera)


def politica(nivel: str) -> tuple[frozenset[str], bool]:
    """(columnas de texto que se vacían, ¿se ocultan categoría y cliente?) para un nivel."""
    columnas = {"cuerpo_texto", "cuerpo_html"}
    if nivel in ("medio", "estricto"):
        columnas.add("asunto")
    if nivel == "estricto":
        columnas |= {"remitente", "destinatarios", "cc"}
    return frozenset(columnas), nivel == "estricto"


def nombre_adjunto_cifrado(nivel: str) -> bool:
    return nivel in ("medio", "estricto")


# --- configuración (con caché corta) --------------------------------------------------------------------------------------------------------------------
_cache_cfg: dict[int, tuple[float, dict | None]] = {}
_cache_cuenta: dict[int, tuple[float, int | None]] = {}
_cache_alguno: list = [0.0, False]
_TTL = 5.0


def olvidar_configuracion() -> None:
    _cache_cfg.clear(); _cache_cuenta.clear(); _cache_alguno[0] = 0.0


def hay_alguno() -> bool:
    """¿Algún despacho tiene el correo cifrado? Si no, todo este módulo se salta sin tocar nada."""
    ahora = time.monotonic()
    if ahora - _cache_alguno[0] > _TTL:
        conn = db.get_connection()
        try:
            _cache_alguno[1] = conn.execute("SELECT 1 FROM cifrado_despacho WHERE correo_activo = 1 LIMIT 1").fetchone() is not None
        finally:
            conn.close()
        _cache_alguno[0] = ahora
    return _cache_alguno[1]


def configuracion(tenant_id: int | None) -> dict | None:
    """{tenant_id, nivel, publica} si el despacho tiene el correo cifrado activado; si no, None."""
    if tenant_id is None or not hay_alguno():
        return None
    ahora = time.monotonic()
    c = _cache_cfg.get(tenant_id)
    if c and ahora - c[0] < _TTL:
        return c[1]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT tenant_id, nivel, publica FROM cifrado_despacho WHERE tenant_id = ? AND correo_activo = 1", (tenant_id,)).fetchone()
    finally:
        conn.close()
    cfg = dict(f) if f else None
    _cache_cfg[tenant_id] = (ahora, cfg)
    return cfg


def tenant_de_cuenta(cuenta_id: int) -> int | None:
    ahora = time.monotonic()
    c = _cache_cuenta.get(cuenta_id)
    if c and ahora - c[0] < 30:
        return c[1]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT u.tenant_id FROM correo_cuentas c JOIN usuarios u ON u.id = c.usuario_id WHERE c.id = ?", (cuenta_id,)).fetchone()
    finally:
        conn.close()
    t = f["tenant_id"] if f else None
    _cache_cuenta[cuenta_id] = (ahora, t)
    return t


def config_de_cuenta(cuenta_id: int) -> dict | None:
    return configuracion(tenant_de_cuenta(cuenta_id)) if hay_alguno() else None


# --- clave de conversación opaca ----------------------------------------------------------------------------------------------------------------------------
def _clave_hilos(tenant_id: int) -> bytes:
    base = (os.environ.get("GUILDA_SECRET_KEY") or "clave-de-desarrollo-no-usar-en-produccion").encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"guilda-hilos-v1:" + str(tenant_id).encode()).derive(base)


def hilo_opaco(tenant_id: int, clave: str | None) -> str | None:
    """La clave de conversación (asunto normalizado + contraparte) no puede quedar en claro cuando el asunto va cifrado: se sustituye por un HMAC con la clave del servidor."""
    if not clave or clave.startswith("h:"):
        return clave
    return "h:" + hmac.new(_clave_hilos(tenant_id), clave.encode("utf-8"), hashlib.sha256).hexdigest()[:40]


def hilo_para_cuenta(cuenta_id: int, clave: str | None) -> str | None:
    """La clave que hay que usar para los mensajes NUEVOS de esta cuenta (opaca en Medio y Estricto)."""
    cfg = config_de_cuenta(cuenta_id)
    return hilo_opaco(cfg["tenant_id"], clave) if cfg and cfg["nivel"] != "laxo" else clave


# --- sellar -----------------------------------------------------------------------------------------------------------------------------------------------------
def _blob(publica_b64: str, datos: dict) -> tuple[bytes, str]:
    return cd.sellar_con_publica(base64.b64decode(publica_b64), json.dumps(datos, ensure_ascii=False).encode("utf-8"))


def _vaciar(columnas: frozenset[str], asociaciones: bool) -> dict:
    sets = {c: ("" if c in ("asunto", "remitente", "destinatarios", "cuerpo_texto") else None) for c in columnas}
    if asociaciones:
        sets.update(categoria_id=None, cliente_fiscal_id=None)
    return sets


def sellar_mensaje(mensaje_id: int, conn=None) -> bool:
    """Cifra un mensaje que está en claro (el último paso de «al entrar»). No necesita clave privada. Devuelve si lo ha sellado."""
    propia = conn is None
    conn = conn or db.get_connection()
    try:
        f = conn.execute("SELECT * FROM correo_mensajes WHERE id = ?", (mensaje_id,)).fetchone()
        if f is None or f["cifrado"] == 1:
            return False
        cfg = config_de_cuenta(f["cuenta_id"])
        if cfg is None:
            if f["cifrado"] == 2:         # entró «por sellar» pero el despacho ya no tiene el correo cifrado: vuelve a ser un mensaje normal (y entra en el índice)
                conn.execute("UPDATE correo_mensajes SET cifrado = 0 WHERE id = ?", (mensaje_id,)); conn.commit()
            return False
        datos = {c: f[c] for c in CAMPOS_TEXTO}
        datos.update(categoria_id=f["categoria_id"], cliente_fiscal_id=f["cliente_fiscal_id"])
        blob, sobre = _blob(cfg["publica"], datos)
        sets = _vaciar(*politica(cfg["nivel"]))
        sets["cifrado"], sets["sobre"], sets["datos"], sets["cifrado_nivel"] = 1, sobre, blob, cfg["nivel"]
        if cfg["nivel"] != "laxo":
            sets["hilo_clave"] = hilo_opaco(cfg["tenant_id"], f["hilo_clave"])
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute(f"UPDATE correo_mensajes SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", [*sets.values(), mensaje_id])
        _sellar_adjuntos(conn, mensaje_id, cfg)
        conn.commit()
        return True
    finally:
        if propia:
            conn.close()


def sellar_pendientes_de_cuenta(cuenta_id: int) -> int:
    """Red de seguridad: reintenta sellar lo que se quedó «por sellar» (`cifrado = 2`) porque algo falló al entrar. Normalmente no hay nada."""
    if config_de_cuenta(cuenta_id) is None:
        return 0
    conn = db.get_connection()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM correo_mensajes WHERE cuenta_id = ? AND cifrado = 2", (cuenta_id,))]
        return sum(1 for i in ids if sellar_mensaje(i, conn))
    finally:
        conn.close()


def vaciar_wal() -> None:
    """Cierra el WAL de SQLite: mientras no se vacía, conserva imágenes de las páginas con el mensaje en claro de antes de sellarlo. Se llama al acabar cada sincronización."""
    if hay_alguno():
        conn = db.get_connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        finally:
            conn.close()


def _sellar_adjuntos(conn, mensaje_id: int, cfg: dict) -> None:
    publica = base64.b64decode(cfg["publica"])
    for a in conn.execute("SELECT id, nombre_archivo, contenido FROM correo_adjuntos WHERE mensaje_id = ? AND cifrado = 0", (mensaje_id,)).fetchall():
        ct, sobre = cd.sellar_con_publica(publica, bytes(a["contenido"]))
        nombre = a["nombre_archivo"]
        nombre_cifrado = None
        if nombre_adjunto_cifrado(cfg["nivel"]):
            nct, nsobre = cd.sellar_con_publica(publica, nombre.encode("utf-8"))
            nombre_cifrado, nombre = json.dumps({"s": nsobre, "c": base64.b64encode(nct).decode()}), ""
        conn.execute("UPDATE correo_adjuntos SET contenido = ?, cifrado = 1, sobre = ?, nombre_cifrado = ?, nombre_archivo = ? WHERE id = ?", (ct, sobre, nombre_cifrado, nombre, a["id"]))


# --- abrir -------------------------------------------------------------------------------------------------------------------------------------------------------
_memoria: dict[int, dict[int, tuple[str, dict]]] = {}      # tenant -> {mensaje_id: (sobre, datos)}
_cerrojo = threading.Lock()


def olvidar(tenant_id: int | None) -> None:
    with _cerrojo:
        if tenant_id is None:
            _memoria.clear()
        else:
            _memoria.pop(tenant_id, None)


cd.al_bloquear(olvidar)


def _descifrar(privada: bytes, sobre: str, blob) -> dict:
    return json.loads(cd.abrir_con_privada(privada, bytes(blob), sobre).decode("utf-8"))


def _ligero(tenant_id: int, mensaje_id: int, sobre: str, blob, privada: bytes) -> dict:
    """Lo mínimo de un mensaje sellado para filtrarlo en memoria (cabeceras, texto normalizado y asociaciones), con caché mientras haya clave. NO guarda el HTML ni el cuerpo entero."""
    with _cerrojo:
        c = _memoria.get(tenant_id, {}).get(mensaje_id)
        if c and c[0] == sobre:
            return c[1]
    if blob is None:
        conn = db.get_connection()
        try:
            blob = conn.execute("SELECT datos FROM correo_mensajes WHERE id = ?", (mensaje_id,)).fetchone()["datos"]
        finally:
            conn.close()
    d = _descifrar(privada, sobre, blob)
    ligero = {k: d.get(k) for k in ("asunto", "remitente", "destinatarios", "cc", "categoria_id", "cliente_fiscal_id")}
    ligero["cuerpo_texto"] = (d.get("cuerpo_texto") or "")[:300]            # solo para la línea de vista previa
    ligero["_pajar"] = _norm(" ".join(str(d.get(c) or "") for c in ("asunto", "remitente", "destinatarios", "cuerpo_texto")))
    with _cerrojo:
        m = _memoria.setdefault(tenant_id, {})
        if len(m) >= LIMITE_MEMORIA + 1000:
            m.clear()
        m[mensaje_id] = (sobre, ligero)
    return ligero


def _bloque(mensaje_id: int):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT datos FROM correo_mensajes WHERE id = ?", (mensaje_id,)).fetchone()["datos"]
    finally:
        conn.close()


def _bloques_que_faltan(filas, extra: dict, privadas: dict, con_pajar: bool = False) -> dict[int, bytes]:
    """Lee de la base de datos, por lotes, los bloques cifrados de los mensajes que se van a descifrar y no están ya en la caché (una consulta por 500, no una por mensaje)."""
    por_tenant: dict[int, list[int]] = {}
    for f in filas:
        origen = extra.get(f["id"], f)
        if origen["cifrado"] != 1 or ("datos" in f.keys() and f["datos"] is not None):
            continue
        tenant = tenant_de_cuenta(origen["cuenta_id"])
        if tenant is None:
            continue
        if tenant not in privadas:
            privadas[tenant] = cd.privada_disponible(tenant)
            if privadas[tenant] is None:
                olvidar(tenant)
        if privadas[tenant] is None:
            continue
        if con_pajar:
            with _cerrojo:
                c = _memoria.get(tenant, {}).get(f["id"])
            if c and c[0] == origen["sobre"]:
                continue
        por_tenant.setdefault(tenant, []).append(f["id"])
    res: dict[int, bytes] = {}
    ids = [i for lista in por_tenant.values() for i in lista]
    if ids:
        conn = db.get_connection()
        try:
            for k in range(0, len(ids), 500):
                lote = ids[k:k + 500]
                for x in conn.execute(f"SELECT id, datos FROM correo_mensajes WHERE id IN ({','.join('?' * len(lote))})", lote):
                    res[x["id"]] = x["datos"]
        finally:
            conn.close()
    return res


def completar(filas, con_pajar: bool = False):
    """Rellena con su contenido real las filas de mensajes sellados (si hay clave) o las marca `protegido`. Sin correo cifrado devuelve las mismas filas como diccionarios
    con `protegido = False`. `con_pajar` es la versión LIGERA para filtrar en memoria: usa la caché, deja solo una vista previa del cuerpo y añade `_pajar` (texto normalizado;
    quien lo pide debe quitarlo y volver a pedir las filas que se queden con `completar` normal)."""
    if not hay_alguno():
        return [{**dict(f), "protegido": False} for f in filas]
    filas = list(filas)
    resultado = []
    faltan = [f["id"] for f in filas if "cifrado" not in f.keys() or "sobre" not in f.keys()]
    extra = {}
    if faltan:
        conn = db.get_connection()
        try:
            for i in range(0, len(faltan), 500):
                lote = faltan[i:i + 500]
                for x in conn.execute(f"SELECT id, cuenta_id, cifrado, cifrado_nivel, sobre FROM correo_mensajes WHERE id IN ({','.join('?' * len(lote))})", lote):
                    extra[x["id"]] = x
        finally:
            conn.close()
    privadas: dict[int, bytes | None] = {}                     # la clave se resuelve una vez por despacho y llamada, no por mensaje
    bloques = _bloques_que_faltan(filas, extra, privadas, con_pajar)
    for f in filas:
        d = dict(f)
        origen = extra.get(d["id"], d)
        sobre_origen, nivel_origen, cifrado_origen, cuenta_origen = origen["sobre"], origen["cifrado_nivel"], origen["cifrado"], origen["cuenta_id"]
        blob = d.pop("datos", None) or bloques.get(d["id"])
        d.pop("sobre", None)
        if cifrado_origen != 1:
            d.setdefault("protegido", False)
            resultado.append(d)
            continue
        tenant = tenant_de_cuenta(cuenta_origen)
        if tenant not in privadas:
            privadas[tenant] = cd.privada_disponible(tenant) if tenant is not None else None
            if privadas[tenant] is None and tenant is not None:
                olvidar(tenant)
        d["cifrado"], d["cifrado_nivel"] = 1, nivel_origen
        if privadas[tenant] is None:
            d["protegido"] = True
        else:
            if con_pajar:
                datos = _ligero(tenant, d["id"], sobre_origen, blob, privadas[tenant])
                d.update({k: v for k, v in datos.items() if k != "_pajar"})
                d["_pajar"] = datos["_pajar"]
            else:
                datos = _descifrar(privadas[tenant], sobre_origen, blob if blob is not None else _bloque(d["id"]))
                d.update({k: v for k, v in datos.items() if k in CAMPOS_TEXTO or k in ("categoria_id", "cliente_fiscal_id")})
            d["protegido"] = False
        resultado.append(d)
    return resultado


def completar_uno(fila):
    return None if fila is None else completar([fila])[0]


def exigir_clave(tenant_id: int) -> None:
    if cd.privada_disponible(tenant_id) is None:
        raise cd.DespachoBloqueado("El correo de este despacho está protegido con su clave: hay que desbloquearlo con la frase de paso.")


def abrir_adjunto(fila, con_contenido: bool = True):
    """Un adjunto con su nombre y contenido reales (si está sellado hace falta la clave: sin ella, `DespachoBloqueado` para el contenido; el nombre sale vacío)."""
    if fila is None or not fila["cifrado"]:
        return fila
    d = dict(fila)
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT m.cuenta_id FROM correo_mensajes m WHERE m.id = ?", (d["mensaje_id"],)).fetchone()
    finally:
        conn.close()
    tenant = tenant_de_cuenta(c["cuenta_id"]) if c else None
    privada = cd.privada_disponible(tenant) if tenant is not None else None
    if d.get("nombre_cifrado"):
        if privada is not None:
            n = json.loads(d["nombre_cifrado"])
            d["nombre_archivo"] = cd.abrir_con_privada(privada, base64.b64decode(n["c"]), n["s"]).decode("utf-8")
        else:
            d["nombre_archivo"], d["protegido"] = "", True
    if con_contenido and "contenido" in d:
        if privada is None:
            raise cd.DespachoBloqueado("El correo de este despacho está protegido con su clave: hay que desbloquearlo con la frase de paso.")
        d["contenido"] = cd.abrir_con_privada(privada, bytes(d["contenido"]), d["sobre"])
        cd.registrar_acceso(tenant, None, d["id"], cd.canal_actual() or "persona", "correo_adjuntos")
    d.pop("sobre", None)
    return d


# --- asociaciones (categoría y cliente) en Estricto, donde viven dentro del bloque cifrado -----------------------------------------------------------------------
def reescribir_asociacion(mensaje_id: int, **cambios) -> bool:
    """Cambia categoría o cliente de un mensaje sellado en Estricto (están dentro del bloque cifrado): hace falta la clave. Devuelve si se ha tocado el bloque
    (False = no era un caso de Estricto y quien llama debe escribir la columna como siempre)."""
    if not hay_alguno():
        return False
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, cuenta_id, cifrado, cifrado_nivel, sobre, datos FROM correo_mensajes WHERE id = ?", (mensaje_id,)).fetchone()
        if f is None or f["cifrado"] != 1 or f["cifrado_nivel"] != "estricto":
            return False
        tenant = tenant_de_cuenta(f["cuenta_id"])
        cfg = configuracion(tenant)
        privada = cd.privada_disponible(tenant)
        datos = _descifrar(privada, f["sobre"], f["datos"]) if privada is not None else None
        if datos is None or cfg is None:
            raise cd.DespachoBloqueado("Para cambiar la categoría o el cliente de un correo en un despacho de nivel Estricto hay que desbloquear los documentos con la frase de paso.")
        datos.update({k: v for k, v in cambios.items() if k in ("categoria_id", "cliente_fiscal_id")})
        blob, sobre = _blob(cfg["publica"], datos)
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute("UPDATE correo_mensajes SET datos = ?, sobre = ? WHERE id = ?", (blob, sobre, mensaje_id))
        conn.commit()
        olvidar(tenant)
        return True
    finally:
        conn.close()


# --- búsqueda en memoria ----------------------------------------------------------------------------------------------------------------------------------------
def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def coincide(m: dict, texto: str | None = None, remitente=None, destinatarios=None, asunto=None) -> bool:
    """Misma idea que el índice de texto completo: cada palabra buscada debe aparecer (sin mayúsculas ni acentos) en asunto, remitente, destinatarios o cuerpo."""
    if texto:
        pajar = m.get("_pajar")
        if pajar is None:
            pajar = _norm(" ".join(str(m.get(c) or "") for c in ("asunto", "remitente", "destinatarios", "cuerpo_texto")))
        if not all(p in pajar for p in _norm(texto).split()):
            return False
    for campo, valor in (("remitente", remitente), ("destinatarios", destinatarios), ("asunto", asunto)):
        if valor and _norm(valor) not in _norm(m.get(campo)):
            return False
    return True


_columnas_sin_datos: list = []


def columnas_sin_bloque() -> str:
    """Las columnas de `correo_mensajes` salvo el bloque cifrado: en una búsqueda en memoria no se vuelve a leer lo que ya está descifrado."""
    if not _columnas_sin_datos:
        conn = db.get_connection()
        try:
            _columnas_sin_datos.append(", ".join(r["name"] for r in conn.execute("PRAGMA table_info(correo_mensajes)") if r["name"] != "datos"))
        finally:
            conn.close()
    return _columnas_sin_datos[0]


def usa_memoria(cuenta_id: int, texto, remitente, destinatarios, asunto, categoria_id, cliente_fiscal_id) -> bool:
    """¿Hay que filtrar en memoria? Con correo cifrado, el texto y los campos de cabecera ya no se pueden consultar en SQL; categoría y cliente solo en Estricto."""
    cfg = config_de_cuenta(cuenta_id)
    if cfg is None:
        return False
    return bool(texto or remitente or destinatarios or asunto or (cfg["nivel"] == "estricto" and (categoria_id is not None or cliente_fiscal_id is not None)))


def candidatos_estricto(tenant_id: int | None = None, usuario_id: int | None = None) -> list[dict]:
    """Los mensajes sellados en Estricto (donde categoría y cliente no se pueden consultar en SQL), ya descifrados si hay clave. Por despacho o por persona."""
    if not hay_alguno():
        return []
    donde, p = ("u.tenant_id = ?", [tenant_id]) if tenant_id is not None else ("c.usuario_id = ?", [usuario_id])
    conn = db.get_connection()
    try:
        filas = conn.execute(
            f"SELECT {', '.join('m.' + c.strip() for c in columnas_sin_bloque().split(','))} FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id JOIN usuarios u ON u.id = c.usuario_id "
            f"WHERE {donde} AND m.cifrado = 1 AND m.cifrado_nivel = 'estricto' ORDER BY m.fecha DESC, m.id DESC LIMIT ?", [*p, LIMITE_MEMORIA]).fetchall()
    finally:
        conn.close()
    return completar(filas)


def buscar_para_usuario(usuario_id: int, texto: str, limite: int = 5) -> list[dict]:
    """Búsqueda por palabras en TODO el correo de una persona (todas sus cuentas y carpetas) para despachos con correo cifrado, con la forma de los resultados del buscador
    externo (que ya no recibe ese correo). Lo sellado sin clave disponible solo se encuentra por lo que el nivel deja en claro."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT m.* FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id WHERE c.usuario_id = ? ORDER BY m.fecha DESC, m.id DESC LIMIT ?",
                             (usuario_id, LIMITE_MEMORIA)).fetchall()
    finally:
        conn.close()
    res = []
    for m in completar(filas):
        if coincide(m, texto):
            res.append({"id": f"mensaje-{m['id']}", "tipo": "mensaje", "usuario_id": usuario_id, "creada_en": m.get("fecha"), "protegido": bool(m.get("protegido")),
                        "texto": f"{m.get('asunto') or ''} {m.get('cuerpo_texto') or ''}".strip()[:1000]})
            if len(res) >= limite:
                break
    return res


# --- activar, cambiar de nivel, desactivar ------------------------------------------------------------------------------------------------------------------------
def estado(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT correo_activo FROM cifrado_despacho WHERE tenant_id = ?", (tenant_id,)).fetchone()
        base = "FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id JOIN usuarios u ON u.id = c.usuario_id WHERE u.tenant_id = ?"
        total = conn.execute(f"SELECT COUNT(*) {base}", (tenant_id,)).fetchone()[0]
        sellados = conn.execute(f"SELECT COUNT(*) {base} AND m.cifrado = 1", (tenant_id,)).fetchone()[0]
    finally:
        conn.close()
    return {"activo": bool(f and f["correo_activo"]), "total": total, "sellados": sellados, "pendientes": total - sellados}


def _ids(conn, tenant_id: int, solo_sin_sellar: bool = False, solo_sellados: bool = False) -> list[int]:
    extra = " AND m.cifrado != 1" if solo_sin_sellar else (" AND m.cifrado = 1" if solo_sellados else "")
    return [r[0] for r in conn.execute(f"SELECT m.id FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id JOIN usuarios u ON u.id = c.usuario_id WHERE u.tenant_id = ?{extra} ORDER BY m.id", (tenant_id,))]


def sellar_todo(tenant_id: int) -> int:
    """Sella el correo que ya había (no necesita clave privada). Vacía el WAL y reconstruye el índice de texto, que si no conservaría palabras del contenido."""
    olvidar_configuracion()
    conn = db.get_connection()
    try:
        conn.execute("PRAGMA secure_delete = ON")
        hechos = sum(1 for i in _ids(conn, tenant_id, solo_sin_sellar=True) if sellar_mensaje(i, conn))
        _depurar_indice(conn)
        return hechos
    finally:
        conn.close()


def _depurar_indice(conn) -> None:
    if _bd.existe_tabla(conn, 'correo_fts'):
        conn.execute("INSERT INTO correo_fts(correo_fts) VALUES ('rebuild')")
        conn.execute("INSERT INTO correo_fts(correo_fts) VALUES ('optimize')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()


def retirar_de_indices_externos(tenant_id: int) -> int:
    """Quita del buscador externo (Meilisearch y sus embeddings) el correo ya indexado de este despacho. Mejor esfuerzo: si el servicio no responde, se detiene."""
    from . import busqueda
    conn = db.get_connection()
    try:
        ids = _ids(conn, tenant_id)
    finally:
        conn.close()
    quitados = 0
    for i in ids:
        try:
            busqueda.eliminar_del_indice("mensaje", i)
            quitados += 1
        except busqueda.ErrorBusqueda:
            break
    return quitados


def activar(tenant_id: int, usuario_id: int, nivel: str | None = None) -> dict:
    """Activa el correo cifrado en un despacho que ya tiene el cifrado de documentos (misma clave). El nivel se puede fijar aquí. No necesita desbloqueo."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT nivel, correo_activo FROM cifrado_despacho WHERE tenant_id = ?", (tenant_id,)).fetchone()
        if f is None:
            raise ValueError("Primero hay que activar el cifrado de documentos del despacho: el correo usa la misma clave.")
        if f["correo_activo"]:
            raise ValueError("El correo cifrado ya está activado.")
        if nivel is not None and nivel not in NIVELES:
            raise ValueError("Nivel de reserva no válido.")
        conn.execute("UPDATE cifrado_despacho SET correo_activo = 1, correo_activado_en = ? WHERE tenant_id = ?", (db.now_iso(), tenant_id))
        conn.commit()
        anterior = f["nivel"]
    finally:
        conn.close()
    olvidar_configuracion()
    if nivel is not None and nivel != anterior:
        cd.cambiar_nivel(tenant_id, usuario_id, nivel)
    sellados = sellar_todo(tenant_id)
    cd.sellar_historial_ia(tenant_id)
    return {"sellados": sellados, "retirados_del_buscador": retirar_de_indices_externos(tenant_id)}


def cambiar_nivel(tenant_id: int, usuario_id: int, nivel: str) -> int:
    """Cambia el nivel de reserva del despacho (ver `cifrado_despacho.cambiar_nivel`). Devuelve cuántos mensajes de correo se han tocado."""
    return cd.cambiar_nivel(tenant_id, usuario_id, nivel)["correos"]


def _reaplicar_nivel(tenant_id: int) -> int:
    cfg = configuracion(tenant_id)
    conn = db.get_connection()
    tocados = 0
    try:
        conn.execute("PRAGMA secure_delete = ON")
        columnas, asociaciones = politica(cfg["nivel"])
        for i in _ids(conn, tenant_id, solo_sellados=True):
            f = conn.execute("SELECT * FROM correo_mensajes WHERE id = ?", (i,)).fetchone()
            datos = json.loads(cd.abrir_con_privada(cd.privada_disponible(tenant_id), bytes(f["datos"]), f["sobre"]).decode()) if f["cifrado_nivel"] != cfg["nivel"] and _necesita_clave(f["cifrado_nivel"], cfg["nivel"]) else None
            sets = {"cifrado_nivel": cfg["nivel"]}
            for c in CAMPOS_TEXTO:                                  # columnas que el nivel nuevo deja en claro: se restauran (solo si se baja de nivel)
                if c in columnas:
                    sets.update(_vaciar(frozenset({c}), False))
                elif datos is not None and c not in ("cuerpo_texto", "cuerpo_html"):
                    sets[c] = datos[c]
            if asociaciones:
                sets.update(categoria_id=None, cliente_fiscal_id=None)
            elif datos is not None:
                sets.update(categoria_id=datos.get("categoria_id"), cliente_fiscal_id=datos.get("cliente_fiscal_id"))
            if datos is not None and cfg["nivel"] == "laxo" and f["hilo_clave"] and f["hilo_clave"].startswith("h:"):
                from . import db as _db
                cuenta = conn.execute("SELECT usuario FROM correo_cuentas WHERE id = ?", (f["cuenta_id"],)).fetchone()
                sets["hilo_clave"] = _db._clave_hilo_por_asunto(datos["asunto"], datos["remitente"], datos["destinatarios"], _db._direccion_simple(cuenta["usuario"]))
            elif cfg["nivel"] != "laxo":
                sets["hilo_clave"] = hilo_opaco(tenant_id, f["hilo_clave"])
            conn.execute(f"UPDATE correo_mensajes SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", [*sets.values(), i])
            _reaplicar_nombres_adjuntos(conn, i, cfg, tenant_id)
            tocados += 1
        _depurar_indice(conn)
    finally:
        conn.close()
    olvidar(tenant_id)
    return tocados


def _necesita_clave(anterior: str, nuevo: str) -> bool:
    return NIVELES.index(nuevo) < NIVELES.index(anterior)


def _reaplicar_nombres_adjuntos(conn, mensaje_id: int, cfg: dict, tenant_id: int) -> None:
    publica = base64.b64decode(cfg["publica"])
    for a in conn.execute("SELECT id, nombre_archivo, nombre_cifrado FROM correo_adjuntos WHERE mensaje_id = ? AND cifrado = 1", (mensaje_id,)).fetchall():
        if nombre_adjunto_cifrado(cfg["nivel"]) and not a["nombre_cifrado"]:
            nct, nsobre = cd.sellar_con_publica(publica, a["nombre_archivo"].encode("utf-8"))
            conn.execute("UPDATE correo_adjuntos SET nombre_cifrado = ?, nombre_archivo = '' WHERE id = ?", (json.dumps({"s": nsobre, "c": base64.b64encode(nct).decode()}), a["id"]))
        elif not nombre_adjunto_cifrado(cfg["nivel"]) and a["nombre_cifrado"]:
            n = json.loads(a["nombre_cifrado"])
            nombre = cd.abrir_con_privada(cd.privada_disponible(tenant_id), base64.b64decode(n["c"]), n["s"]).decode("utf-8")
            conn.execute("UPDATE correo_adjuntos SET nombre_cifrado = NULL, nombre_archivo = ? WHERE id = ?", (nombre, a["id"]))


def desactivar(tenant_id: int, usuario_id: int) -> int:
    """Desactiva el correo cifrado: descifra todo lo sellado y lo deja en claro. Exige el despacho desbloqueado. Devuelve cuántos mensajes."""
    if cd.privada_disponible(tenant_id) is None:
        raise cd.DespachoBloqueado("Para desactivar el correo cifrado hay que desbloquear antes los documentos con la frase de paso.")
    conn = db.get_connection()
    hechos = 0
    try:
        conn.execute("PRAGMA secure_delete = ON")
        privada = cd.privada_disponible(tenant_id)
        for i in _ids(conn, tenant_id, solo_sellados=True):
            f = conn.execute("SELECT * FROM correo_mensajes WHERE id = ?", (i,)).fetchone()
            datos = json.loads(cd.abrir_con_privada(privada, bytes(f["datos"]), f["sobre"]).decode())
            sets = {c: datos[c] for c in CAMPOS_TEXTO}
            sets.update(categoria_id=datos.get("categoria_id"), cliente_fiscal_id=datos.get("cliente_fiscal_id"), cifrado=0, sobre=None, datos=None, cifrado_nivel=None)
            cuenta = conn.execute("SELECT usuario FROM correo_cuentas WHERE id = ?", (f["cuenta_id"],)).fetchone()
            if f["hilo_clave"] and f["hilo_clave"].startswith("h:"):
                sets["hilo_clave"] = db._clave_hilo_por_asunto(datos["asunto"], datos["remitente"], datos["destinatarios"], db._direccion_simple(cuenta["usuario"]))
            conn.execute(f"UPDATE correo_mensajes SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", [*sets.values(), i])
            for a in conn.execute("SELECT * FROM correo_adjuntos WHERE mensaje_id = ? AND cifrado = 1", (i,)).fetchall():
                nombre = a["nombre_archivo"]
                if a["nombre_cifrado"]:
                    n = json.loads(a["nombre_cifrado"])
                    nombre = cd.abrir_con_privada(privada, base64.b64decode(n["c"]), n["s"]).decode("utf-8")
                conn.execute("UPDATE correo_adjuntos SET contenido = ?, cifrado = 0, sobre = NULL, nombre_cifrado = NULL, nombre_archivo = ? WHERE id = ?",
                             (cd.abrir_con_privada(privada, bytes(a["contenido"]), a["sobre"]), nombre, a["id"]))
            hechos += 1
        conn.execute("UPDATE cifrado_despacho SET correo_activo = 0 WHERE tenant_id = ?", (tenant_id,))
        conn.commit()
        _depurar_indice(conn)
    finally:
        conn.close()
    olvidar_configuracion()
    olvidar(tenant_id)
    return hechos


def resellar(conn, tenant_id: int, abrir_antiguo, sellar_nuevo) -> int:
    """Rotación de la clave del despacho: vuelve a cifrar bloques y adjuntos del correo, dentro de la transacción de quien llama."""
    hechos = 0
    for f in conn.execute("SELECT m.id, m.datos, m.sobre FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id JOIN usuarios u ON u.id = c.usuario_id WHERE u.tenant_id = ? AND m.cifrado = 1", (tenant_id,)).fetchall():
        nuevo, sobre = sellar_nuevo(abrir_antiguo(bytes(f["datos"]), f["sobre"]))
        conn.execute("UPDATE correo_mensajes SET datos = ?, sobre = ? WHERE id = ?", (nuevo, sobre, f["id"]))
        hechos += 1
    for a in conn.execute("SELECT a.id, a.contenido, a.sobre, a.nombre_cifrado FROM correo_adjuntos a JOIN correo_mensajes m ON m.id = a.mensaje_id JOIN correo_cuentas c ON c.id = m.cuenta_id JOIN usuarios u ON u.id = c.usuario_id WHERE u.tenant_id = ? AND a.cifrado = 1", (tenant_id,)).fetchall():
        nuevo, sobre = sellar_nuevo(abrir_antiguo(bytes(a["contenido"]), a["sobre"]))
        nombre = a["nombre_cifrado"]
        if nombre:
            n = json.loads(nombre)
            nn, ns = sellar_nuevo(abrir_antiguo(base64.b64decode(n["c"]), n["s"]))
            nombre = json.dumps({"s": ns, "c": base64.b64encode(nn).decode()})
        conn.execute("UPDATE correo_adjuntos SET contenido = ?, sobre = ?, nombre_cifrado = ? WHERE id = ?", (nuevo, sobre, nombre, a["id"]))
        hechos += 1
    return hechos
