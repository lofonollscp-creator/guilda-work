"""Cliente de Meilisearch (buscador unificado, ver HOSTING.md) —
licencia MIT (Community Edition), instancia compartida con aislamiento
real por **tenant token**: un JWT firmado por Guilda Work con un filtro
`usuario_id = <n>` embebido, que Meilisearch aplica siempre en AND con
cualquier filtro adicional que mande el cliente — verificado en vivo
contra un contenedor real que es imposible de saltar (intentar buscar
`usuario_id = <otro>` con el token de un usuario da 0 resultados, nunca
los del otro, porque queda como `(otro) AND (el propio)`).

## Por qué `usuario_id` y no `tenant_id`

El registro de actividad propio de Guilda Work (notas, tareas con
duración, correo) ya está delimitado por `usuario_id`, no por tenant —
un tenant puede tener varios usuarios, cada uno con su propio registro
privado (ver `db.py:historial`, filtrado siempre por `usuario_id`). El
buscador respeta ese mismo límite ya existente, no inventa uno nuevo.

## Diseño

Un único índice (`registro_actividad`) para notas + tareas + correo,
cada documento con un campo `tipo` para distinguirlos y un `id` prefijado
por tipo (`nota-7`, `tarea-3`, `mensaje-42`) para que nunca choquen entre
sí. El frontend llama a Meilisearch **directamente** con el tenant token
(sin pasar por Flask) para buscar — patrón estándar de tenant tokens,
evita cargar el backend con cada tecla pulsada; este módulo solo indexa
(con la clave maestra, nunca expuesta al cliente) y genera el token.

Aprovisionamiento sin pasos manuales: la clave de búsqueda usada para
firmar los tenant tokens se crea sola la primera vez que hace falta (ver
`_asegurar_clave_busqueda`), con la clave maestra — nada que pegar a
mano en el backoffice.

Mismo criterio que el resto de `app/*.py`: solo `urllib` de la librería
estándar (el JWT se firma a mano, mismo código que `app/jitsi.py` —
HS256 verificado de forma cruzada con un contenedor real de
Meilisearch durante el desarrollo).

## Búsqueda semántica (RAG) — vectores "userProvided"

Verificado en vivo (Ollama + Meilisearch reales) antes de escribir esto:
un embedder `{"source": "userProvided", "dimensions": 768}` en
`PATCH /indexes/{idx}/settings/embedders` funciona tal cual (confirmado
que, a diferencia de filterable-attributes en su día, aquí PATCH sí
aplica el cambio, no hace falta PUT); cada documento lleva su vector ya
calculado (`app/embeddings.py`, Ollama+`nomic-embed-text`, 768
dimensiones) en `_vectors.default`; y — el punto que de verdad
importaba verificar — el filtro `usuario_id` del tenant token se sigue
aplicando en búsqueda HÍBRIDA exactamente igual que en búsqueda por
palabra clave: probado con una consulta semánticamente mucho más
cercana al documento de OTRO usuario, que con el tenant token propio
sigue devolviendo solo lo del usuario dueño del token (nunca lo ajeno,
aunque sea el mejor resultado semántico posible) — la sustitución de
`filter` que ya evita un tenant token para búsqueda de texto aplica
igual aquí, es el mismo mecanismo por debajo.

Si `app/embeddings.py:generar_embedding()` devuelve `None` (Ollama no
disponible), el documento se indexa igual, solo que sin vector — sigue
siendo buscable por palabra clave, se degrada, no falla."""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

from . import embeddings

MEILISEARCH_URL = os.environ.get("MEILISEARCH_URL", "http://127.0.0.1:8029")
MEILISEARCH_MASTER_KEY = os.environ.get("MEILISEARCH_MASTER_KEY")
INDICE = "registro_actividad"
DIMENSIONES_EMBEDDING = 768
TIMEOUT_SEGUNDOS = 10

_DESCRIPCION_CLAVE_BUSQUEDA = "Guilda Work - tenant tokens de búsqueda"

# Cacheados en memoria del proceso tras la primera llamada — evita releer
# /keys o volver a fijar los atributos filtrables en cada indexación.
_clave_busqueda_cache: dict | None = None
_indice_listo = False


class ErrorBusqueda(Exception):
    """Error legible para mostrar cuando Meilisearch falla."""


def _peticion(endpoint: str, *, clave: str, metodo: str = "GET", cuerpo: dict | list | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(
        f"{MEILISEARCH_URL}{endpoint}", data=datos, method=metodo,
        headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read()
            return json.loads(cuerpo_resp) if cuerpo_resp else None
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        raise ErrorBusqueda(f"Meilisearch ha rechazado la petición a {endpoint} (HTTP {e.code}): {detalle}") from e
    except urllib.error.URLError as e:
        raise ErrorBusqueda(
            f"No se ha podido conectar con Meilisearch ({MEILISEARCH_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorBusqueda(f"Tiempo de espera agotado al contactar con Meilisearch ({MEILISEARCH_URL}).")


def _asegurar_indice() -> None:
    global _indice_listo
    if _indice_listo:
        return
    try:
        _peticion("/indexes", clave=MEILISEARCH_MASTER_KEY, metodo="POST", cuerpo={"uid": INDICE, "primaryKey": "id"})
    except ErrorBusqueda as e:
        if "index_already_exists" not in str(e):
            raise
    _peticion(f"/indexes/{INDICE}/settings/filterable-attributes", clave=MEILISEARCH_MASTER_KEY, metodo="PUT", cuerpo=["usuario_id", "tipo"])
    _peticion(
        f"/indexes/{INDICE}/settings/embedders", clave=MEILISEARCH_MASTER_KEY, metodo="PATCH",
        cuerpo={"default": {"source": "userProvided", "dimensions": DIMENSIONES_EMBEDDING}},
    )
    _indice_listo = True


def _asegurar_clave_busqueda() -> dict:
    """Crea (si no existe ya) una clave de API de solo-búsqueda,
    limitada a este índice — la clave que de verdad firma los tenant
    tokens, nunca la maestra."""
    global _clave_busqueda_cache
    if _clave_busqueda_cache is not None:
        return _clave_busqueda_cache
    existentes = _peticion("/keys", clave=MEILISEARCH_MASTER_KEY)
    for clave in existentes.get("results", []):
        if clave.get("description") == _DESCRIPCION_CLAVE_BUSQUEDA:
            _clave_busqueda_cache = {"uid": clave["uid"], "key": clave["key"]}
            return _clave_busqueda_cache
    creada = _peticion(
        "/keys", clave=MEILISEARCH_MASTER_KEY, metodo="POST",
        cuerpo={"description": _DESCRIPCION_CLAVE_BUSQUEDA, "actions": ["search"], "indexes": [INDICE], "expiresAt": None},
    )
    _clave_busqueda_cache = {"uid": creada["uid"], "key": creada["key"]}
    return _clave_busqueda_cache


def _base64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def _firmar_jwt(payload: dict, secreto: str) -> str:
    """HS256 a mano, mismo código que app/jitsi.py — sin depender de
    PyJWT (no es una dependencia del proyecto)."""
    cabecera = {"alg": "HS256", "typ": "JWT"}
    segmento_cabecera = _base64url(json.dumps(cabecera, separators=(",", ":")).encode("utf-8"))
    segmento_payload = _base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    firmante = f"{segmento_cabecera}.{segmento_payload}".encode("ascii")
    firma = hmac.new(secreto.encode("utf-8"), firmante, hashlib.sha256).digest()
    return f"{segmento_cabecera}.{segmento_payload}.{_base64url(firma)}"


def generar_token_busqueda(usuario_id: int, minutos_validez: int = 60) -> str:
    """Tenant token de Meilisearch, válido solo para buscar dentro de
    los documentos de este usuario. Si MEILISEARCH_MASTER_KEY no está
    configurada, lanza ErrorBusqueda (el buscador es opcional, mismo
    criterio que el resto de integraciones)."""
    if not MEILISEARCH_MASTER_KEY:
        raise ErrorBusqueda("MEILISEARCH_MASTER_KEY no está configurada.")
    clave = _asegurar_clave_busqueda()
    payload = {
        "searchRules": {INDICE: {"filter": f"usuario_id = {usuario_id}"}},
        "apiKeyUid": clave["uid"],
        "exp": int(time.time()) + minutos_validez * 60,
    }
    return _firmar_jwt(payload, clave["key"])


def _indexar(documento: dict) -> None:
    if not MEILISEARCH_MASTER_KEY:
        return
    _asegurar_indice()
    vector = embeddings.generar_embedding(documento["texto"])
    if vector is not None:
        documento = {**documento, "_vectors": {"default": vector}}
    _peticion(f"/indexes/{INDICE}/documents", clave=MEILISEARCH_MASTER_KEY, metodo="POST", cuerpo=[documento])


def indexar_nota(nota: dict) -> None:
    _indexar({
        "id": f"nota-{nota['id']}",
        "tipo": "nota",
        "usuario_id": nota["usuario_id"],
        "texto": nota["texto"],
        "creada_en": nota["creada_en"],
        "categoria_id": nota.get("categoria_id"),
    })


def indexar_tarea(tarea: dict) -> None:
    _indexar({
        "id": f"tarea-{tarea['id']}",
        "tipo": "tarea",
        "usuario_id": tarea["usuario_id"],
        "texto": tarea["nombre"],
        "creada_en": tarea.get("inicio_en"),
        "categoria_id": tarea.get("categoria_id"),
    })


def indexar_mensaje(mensaje: dict, usuario_id: int) -> None:
    """`correo_mensajes` no tiene columna `usuario_id` propia (solo
    `cuenta_id`, y la cuenta sí pertenece a un usuario) — quien llama ya
    sabe de qué usuario es la cuenta que está sincronizando, así que se
    pasa explícito en vez de repetir aquí la misma consulta a
    `correo_cuentas`."""
    _indexar({
        "id": f"mensaje-{mensaje['id']}",
        "tipo": "mensaje",
        "usuario_id": usuario_id,
        "texto": f"{mensaje.get('asunto', '')} {mensaje.get('cuerpo_texto', '') or ''}".strip(),
        "creada_en": mensaje.get("fecha"),
    })


def eliminar_del_indice(tipo: str, id_: int) -> None:
    if not MEILISEARCH_MASTER_KEY:
        return
    _peticion(f"/indexes/{INDICE}/documents/{tipo}-{id_}", clave=MEILISEARCH_MASTER_KEY, metodo="DELETE")


def buscar_hibrido(usuario_id: int, texto: str, limite: int = 5) -> list[dict]:
    """Búsqueda híbrida (palabra clave + semántica) — a diferencia de
    `generar_token_busqueda()`, esto se ejecuta del lado del servidor
    (necesita calcular el embedding de `texto` con Ollama, solo
    alcanzable desde aquí, ver app/embeddings.py) en vez de que el
    navegador llame a Meilisearch directamente, excepción deliberada al
    patrón de app/static/busqueda.js (ver HOSTING.md). Reutiliza
    `generar_token_busqueda()` (no la clave maestra) para heredar el
    mismo aislamiento por `usuario_id` ya verificado en vivo, en vez de
    construir el filtro a mano aquí.

    Devuelve [] (no lanza) si Meilisearch u Ollama no están disponibles
    — es una mejora sobre la búsqueda por palabra clave existente,
    nunca debe romper nada más."""
    if not MEILISEARCH_MASTER_KEY:
        return []
    vector = embeddings.generar_embedding(texto)
    if vector is None:
        return []
    token = generar_token_busqueda(usuario_id, minutos_validez=2)
    cuerpo = {
        "q": texto,
        "hybrid": {"embedder": "default", "semanticRatio": 0.5},
        "vector": vector,
        "limit": limite,
    }
    resultado = _peticion(f"/indexes/{INDICE}/search", clave=token, metodo="POST", cuerpo=cuerpo)
    return resultado.get("hits", []) if resultado else []
