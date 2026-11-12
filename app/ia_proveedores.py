"""Proveedores de IA con clave propia (OpenAI, Anthropic Claude, Google Gemini, Mistral, Ollama) además de OpenRouter, que sigue siendo el predeterminado.

El resto de la aplicación habla un solo formato, el de «chat completions» de OpenAI (mensajes, `tools`, `tool_calls`, partes `text` / `image_url` / `file`). Aquí se traduce a lo que entiende cada
proveedor y la respuesta vuelve en ese mismo formato, con el uso (`usage`) normalizado:

* `openai` (OpenAI, Gemini, Mistral, Ollama y todo lo compatible): el formato ya es el nuestro; solo cambia la URL, la autenticación y algún parámetro que ciertos modelos rechazan.
* `anthropic` (Claude): API nativa de mensajes. Se traducen mensajes, herramientas, imágenes y PDF (que Claude lee de forma nativa), y el streaming.

Los proveedores que no leen PDF reciben cada página como imagen (app/pdf_facturas.py). Ninguna función de aquí guarda claves ni toca la base de datos; los errores nunca llevan la clave."""
from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass

from flask_babel import lazy_gettext as _l

from .ia_errores import ErrorIA

TIMEOUT_SEGUNDOS = 30
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096


@dataclass(frozen=True)
class Proveedor:
    id: str
    nombre: str
    formato: str                          # «openai» o «anthropic»
    url_base: str
    pide_clave: bool = True
    pdf_nativo: bool = False              # lee el PDF tal cual; si no, se le mandan las páginas como imágenes
    region: str = "global"                # «global», «ue» (la empresa opera bajo derecho de la UE) o «local» (no sale de tu red)
    ejemplo_clave: str = ""
    modelos_sugeridos: tuple[str, ...] = ()
    ayuda: str = ""


PROVEEDORES: dict[str, Proveedor] = {p.id: p for p in (
    Proveedor("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", pdf_nativo=True, ejemplo_clave="sk-or-…",
              ayuda=_l("El predeterminado: incluye modelos gratuitos. Las claves de OpenRouter personales siguen funcionando como hasta ahora.")),
    Proveedor("openai", "OpenAI (ChatGPT)", "openai", "https://api.openai.com/v1", pdf_nativo=True, ejemplo_clave="sk-…",
              modelos_sugeridos=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"), ayuda=_l("Necesita un modelo con visión (gpt-4o o posterior) para leer facturas.")),
    Proveedor("anthropic", "Anthropic (Claude)", "anthropic", "https://api.anthropic.com/v1", pdf_nativo=True, ejemplo_clave="sk-ant-…",
              modelos_sugeridos=("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"), ayuda=_l("Claude lee PDF e imágenes de forma nativa: muy buena opción para facturas.")),
    Proveedor("gemini", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai", ejemplo_clave="AIza…",
              modelos_sugeridos=("gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"), ayuda=_l("Las páginas de los PDF se envían como imágenes.")),
    Proveedor("mistral", "Mistral", "openai", "https://api.mistral.ai/v1", region="ue",
              modelos_sugeridos=("pixtral-large-latest", "mistral-small-latest", "mistral-large-latest"), ayuda=_l("Empresa europea. Para facturas usa un modelo con visión (Pixtral).")),
    Proveedor("ollama", "Ollama (local)", "openai", "http://localhost:11434/v1", pide_clave=False, region="local",
              modelos_sugeridos=("llama3.2-vision", "qwen2.5vl", "llama3.1"), ayuda=_l("Un modelo en tu propia red: los datos no salen de ella. Indica la dirección de tu servidor Ollama.")),
)}
ORDEN = tuple(PROVEEDORES)

# Códigos HTTP que indican que el problema es de ESA clave (sin crédito, inválida, límite alcanzado): vale la pena probar la siguiente.
CODIGOS_DE_CLAVE = {401, 402, 403, 429}


def obtener(proveedor_id: str) -> Proveedor:
    try:
        return PROVEEDORES[proveedor_id]
    except KeyError:
        raise ValueError("Proveedor de IA no válido.") from None


def enmascarar(clave: str) -> str:
    """«sk-ab…9f3a»: lo bastante para reconocer la clave sin poder usarla."""
    c = (clave or "").strip()
    return "…" if len(c) <= 8 else f"{c[:3]}…{c[-4:]}"


def limpiar(texto: str, claves: list[str]) -> str:
    """Quita las claves (y cualquier cosa con forma de clave) de un texto que va a pantalla o al registro."""
    for c in claves or []:
        if c and len(c) >= 6:
            texto = texto.replace(c, "***")
    return re.sub(r"\b(sk-[A-Za-z0-9_\-]{12,}|AIza[A-Za-z0-9_\-]{20,}|gsk_[A-Za-z0-9]{20,})", "***", texto)


def url_valida(url: str) -> str:
    """La URL base de un servidor propio (Ollama o compatible), sin barra final. `ValueError` si no es http(s)."""
    u = (url or "").strip().rstrip("/")
    if not re.match(r"^https?://[^\s/]+(/[^\s]*)?$", u):
        raise ValueError("La dirección del servidor no es válida (por ejemplo http://localhost:11434/v1).")
    return u


# --- HTTP ---------------------------------------------------------------------------------------------------------------------------------------------------

def _destinos_internos() -> set[str]:
    """`host:puerto` que sí se pueden alcanzar aunque sean de la red interna (por defecto, el Ollama del propio servidor)."""
    bruto = os.environ.get("GUILDA_IA_DESTINOS_INTERNOS", "localhost:11434,127.0.0.1:11434")
    return {d.strip().lower() for d in bruto.split(",") if d.strip()}


def comprobar_destino(url: str) -> None:
    """Evita que la URL de un servidor propio sirva para sondear la red interna (SSRF: Kratos/Hydra admin en 127.0.0.1, la red de Docker,
    los metadatos de la nube). Solo pasan direcciones públicas o las de `GUILDA_IA_DESTINOS_INTERNOS`. Un nombre que no resuelve se deja
    pasar: la conexión fallará sola. `ErrorIA` si el destino no es público."""
    partes = urllib.parse.urlsplit(url)
    host = (partes.hostname or "").lower()
    try:
        puerto = partes.port or (443 if partes.scheme == "https" else 80)
    except ValueError:
        raise ErrorIA("La dirección del servidor no es válida.") from None
    if f"{host}:{puerto}" in _destinos_internos():
        return
    try:
        direcciones = {r[4][0] for r in socket.getaddrinfo(host, puerto, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        return
    for d in direcciones:
        if not ipaddress.ip_address(d.split("%")[0]).is_global:
            raise ErrorIA("La dirección del servidor apunta a una red no pública: no se consulta.")


def _conectar_seguro(host: str, puerto: int, timeout) -> socket.socket:
    """Resuelve el nombre UNA vez, comprueba que todas las direcciones son públicas (o están en la lista de excepciones) y conecta a una de esas
    mismas direcciones: un DNS que cambie de respuesta entre la comprobación y la conexión (rebinding) ya no sirve."""
    interno = f"{host.lower()}:{puerto}" in _destinos_internos()
    direcciones = [r[4] for r in socket.getaddrinfo(host, puerto, type=socket.SOCK_STREAM)]
    if not interno and any(not ipaddress.ip_address(d[0].split("%")[0]).is_global for d in direcciones):
        raise ErrorIA("La dirección del servidor apunta a una red no pública: no se consulta.")
    ultimo: OSError | None = None
    for d in direcciones:
        try:
            return socket.create_connection((d[0], puerto), timeout)
        except OSError as e:
            ultimo = e
    raise ultimo or OSError("sin direcciones")


class _ConexionHttp(http.client.HTTPConnection):
    def connect(self):
        self.sock = _conectar_seguro(self.host, self.port, self.timeout)


class _ConexionHttps(http.client.HTTPSConnection):
    def connect(self):
        sock = _conectar_seguro(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _ManejadorHttp(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_ConexionHttp, req)


class _ManejadorHttps(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_ConexionHttps, req, context=ssl.create_default_context())


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """Un 302 no puede llevar la petición a un destino que no se ha comprobado."""

    def redirect_request(self, *a, **k):
        return None


_abridor = urllib.request.build_opener(_SinRedirecciones, _ManejadorHttp, _ManejadorHttps)


def _cabeceras(prov: Proveedor, clave: str) -> dict:
    h = {"Content-Type": "application/json"}
    if prov.formato == "anthropic":
        h.update({"x-api-key": clave, "anthropic-version": ANTHROPIC_VERSION})
    elif clave:
        h["Authorization"] = f"Bearer {clave}"
    return h


def _http_json(url: str, payload: dict | None, cabeceras: dict, timeout: int, claves: list[str], nombre: str, metodo: str = "POST") -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    comprobar_destino(url)
    req = urllib.request.Request(url, data=data, method=metodo, headers=cabeceras)
    try:
        with _abridor.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = limpiar(e.read().decode("utf-8", errors="replace"), claves)[:600]
        raise ErrorIA(f"{nombre} devolvió un error ({e.code}): {detalle}", codigo_http=e.code) from e
    except urllib.error.URLError as e:
        raise ErrorIA(f"No se ha podido conectar con {nombre}. Detalle: {limpiar(str(e.reason), claves)}") from e
    except TimeoutError as e:
        raise ErrorIA(f"Tiempo de espera agotado al contactar con {nombre}.") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise ErrorIA(f"Respuesta inválida de {nombre}: {limpiar(str(e), claves)}") from e


def _abrir_stream(url: str, payload: dict, cabeceras: dict, claves: list[str], nombre: str):
    comprobar_destino(url)
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers={**cabeceras, "Accept": "text/event-stream"})
    try:
        return _abridor.open(req, timeout=TIMEOUT_SEGUNDOS)
    except urllib.error.HTTPError as e:
        raise ErrorIA(f"{nombre} devolvió un error ({e.code}): {limpiar(e.read().decode('utf-8', errors='replace'), claves)[:600]}", codigo_http=e.code) from e
    except urllib.error.URLError as e:
        raise ErrorIA(f"No se ha podido conectar con {nombre}. Detalle: {limpiar(str(e.reason), claves)}") from e
    except TimeoutError as e:
        raise ErrorIA(f"Tiempo de espera agotado al contactar con {nombre}.") from e


def _eventos_sse(resp) -> Iterator[dict]:
    """Cada `data: {...}` ya como dict (las líneas `event:`, los comentarios de keep-alive y `[DONE]` se ignoran)."""
    try:
        for linea in resp:
            linea = linea.decode("utf-8").strip()
            if not linea.startswith("data:"):
                continue
            contenido = linea[5:].strip()
            if contenido == "[DONE]":
                return
            try:
                yield json.loads(contenido)
            except json.JSONDecodeError:
                continue
    finally:
        resp.close()


# --- Partes con archivos ------------------------------------------------------------------------------------------------------------------------------------

_DATA_URL = re.compile(r"^data:([^;,]+)(?:;[^,]*)?;base64,(.*)$", re.S)


def _trozos_data_url(url: str) -> tuple[str, str] | None:
    m = _DATA_URL.match(url or "")
    return (m.group(1).lower(), m.group(2)) if m else None


def _pdf_a_imagenes(partes: list[dict]) -> list[dict]:
    """Cambia cada parte PDF por las imágenes de sus páginas (para proveedores que no leen PDF). Si no se puede renderizar, se deja tal cual y el proveedor dirá que no lo admite."""
    from . import pdf_facturas
    salida = []
    for p in partes:
        if p.get("type") == "file":
            datos = _trozos_data_url((p.get("file") or {}).get("file_data", ""))
            if datos and datos[0] == "application/pdf":
                imagenes = pdf_facturas.paginas_a_imagenes(base64.b64decode(datos[1]))
                if imagenes:
                    salida += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode("ascii")}} for i in imagenes]
                    continue
        salida.append(p)
    return salida


def _preparar_mensajes(prov: Proveedor, mensajes: list[dict]) -> list[dict]:
    """Los mensajes tal como los entiende este proveedor (solo cambia algo si algún mensaje lleva un PDF y el proveedor no lo lee)."""
    if prov.pdf_nativo:
        return mensajes
    return [{**m, "content": _pdf_a_imagenes(m["content"])} if isinstance(m.get("content"), list) else m for m in mensajes]


# --- Formato OpenAI -----------------------------------------------------------------------------------------------------------------------------------------

_RAZONADORES = re.compile(r"^(o\d|gpt-5)", re.I)         # los modelos de razonamiento de OpenAI rechazan `temperature` y piden `max_completion_tokens`


def _payload_openai(prov: Proveedor, modelo: str, payload: dict, stream: bool) -> dict:
    p = {**payload, "model": modelo, "messages": _preparar_mensajes(prov, payload["messages"])}
    if prov.id == "openai" and _RAZONADORES.match(modelo):
        p.pop("temperature", None)
        if "max_tokens" in p:
            p["max_completion_tokens"] = p.pop("max_tokens")
    if not p.get("tools"):
        p.pop("tools", None)
    if stream and prov.id != "ollama":
        p["stream"] = True
        p["stream_options"] = {"include_usage": True}
    elif stream:
        p["stream"] = True
    return p


def _usage_openai(respuesta: dict) -> dict:
    u = respuesta.get("usage") or {}
    return {"prompt_tokens": int(u.get("prompt_tokens") or 0), "completion_tokens": int(u.get("completion_tokens") or 0), **({"cost": u["cost"]} if isinstance(u.get("cost"), (int, float)) else {})}


# --- Formato Anthropic --------------------------------------------------------------------------------------------------------------------------------------

def _bloques_usuario(contenido) -> list[dict]:
    if isinstance(contenido, str):
        return [{"type": "text", "text": contenido}] if contenido else []
    bloques = []
    for p in contenido or []:
        tipo = p.get("type")
        if tipo == "text":
            if p.get("text"):
                bloques.append({"type": "text", "text": p["text"]})
        elif tipo == "image_url":
            url = (p.get("image_url") or {}).get("url", "")
            datos = _trozos_data_url(url)
            bloques.append({"type": "image", "source": {"type": "base64", "media_type": datos[0], "data": datos[1]} if datos else {"type": "url", "url": url}})
        elif tipo == "file":
            datos = _trozos_data_url((p.get("file") or {}).get("file_data", ""))
            if datos:
                bloques.append({"type": "document", "source": {"type": "base64", "media_type": datos[0], "data": datos[1]}})
    return bloques


def _a_anthropic(payload: dict, modelo: str) -> dict:
    sistema, mensajes = [], []

    def anadir(rol: str, bloques: list[dict]) -> None:
        if not bloques:
            return
        if mensajes and mensajes[-1]["role"] == rol:                       # Claude exige alternar roles: lo consecutivo se junta
            mensajes[-1]["content"] += bloques
        else:
            mensajes.append({"role": rol, "content": list(bloques)})

    for m in payload["messages"]:
        rol = m.get("role")
        if rol == "system":
            sistema.append(m["content"] if isinstance(m["content"], str) else " ".join(p.get("text", "") for p in m["content"]))
        elif rol == "user":
            anadir("user", _bloques_usuario(m.get("content")))
        elif rol == "assistant":
            bloques = _bloques_usuario(m.get("content")) if m.get("content") else []
            for tc in m.get("tool_calls") or []:
                try:
                    entrada = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    entrada = {}
                bloques.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"], "input": entrada if isinstance(entrada, dict) else {}})
            anadir("assistant", bloques)
        elif rol == "tool":
            anadir("user", [{"type": "tool_result", "tool_use_id": m.get("tool_call_id"), "content": m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"), ensure_ascii=False)}])
    if mensajes and mensajes[0]["role"] != "user":
        mensajes.insert(0, {"role": "user", "content": [{"type": "text", "text": "(continúa)"}]})
    p = {"model": modelo, "max_tokens": int(payload.get("max_tokens") or ANTHROPIC_MAX_TOKENS), "messages": mensajes}
    if sistema:
        p["system"] = "\n\n".join(s for s in sistema if s)
    if payload.get("temperature") is not None:
        p["temperature"] = payload["temperature"]
    herramientas = [{"name": t["function"]["name"], "description": t["function"].get("description", ""), "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                    for t in payload.get("tools") or [] if t.get("type") == "function"]
    if herramientas:
        p["tools"] = herramientas
    return p


def _de_anthropic(respuesta: dict) -> dict:
    texto, llamadas = [], []
    for b in respuesta.get("content") or []:
        if b.get("type") == "text":
            texto.append(b.get("text", ""))
        elif b.get("type") == "tool_use":
            llamadas.append({"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}})
    mensaje = {"role": "assistant", "content": "".join(texto) or None}
    if llamadas:
        mensaje["tool_calls"] = llamadas
    u = respuesta.get("usage") or {}
    entrada = int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
    return {"choices": [{"message": mensaje, "finish_reason": "tool_calls" if llamadas else "stop"}], "usage": {"prompt_tokens": entrada, "completion_tokens": int(u.get("output_tokens") or 0)}}


def _chunks_de_anthropic(eventos: Iterator[dict]) -> Iterator[dict]:
    """Los eventos de streaming de Claude como trozos con la forma de OpenAI (`choices[0].delta`), más un trozo final solo con `usage`."""
    indice_de_bloque: dict[int, int] = {}                  # índice de bloque de Claude -> índice de tool_call
    entrada = salida = 0
    for e in eventos:
        tipo = e.get("type")
        if tipo == "message_start":
            u = (e.get("message") or {}).get("usage") or {}
            entrada = int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
            salida = int(u.get("output_tokens") or 0)
        elif tipo == "content_block_start":
            b = e.get("content_block") or {}
            if b.get("type") == "tool_use":
                indice_de_bloque[e["index"]] = len(indice_de_bloque)
                yield {"choices": [{"delta": {"tool_calls": [{"index": indice_de_bloque[e["index"]], "id": b.get("id", ""), "function": {"name": b.get("name", ""), "arguments": ""}}]}}]}
        elif tipo == "content_block_delta":
            d = e.get("delta") or {}
            if d.get("type") == "text_delta":
                yield {"choices": [{"delta": {"content": d.get("text", "")}}]}
            elif d.get("type") == "input_json_delta" and e.get("index") in indice_de_bloque:
                yield {"choices": [{"delta": {"tool_calls": [{"index": indice_de_bloque[e["index"]], "function": {"arguments": d.get("partial_json", "")}}]}}]}
        elif tipo == "message_delta":
            salida = int((e.get("usage") or {}).get("output_tokens") or salida)
        elif tipo == "error":
            raise ErrorIA("Claude cortó la respuesta: " + str((e.get("error") or {}).get("message", "error")))
    yield {"usage": {"prompt_tokens": entrada, "completion_tokens": salida}}


# --- API pública --------------------------------------------------------------------------------------------------------------------------------------------

def _url_chat(prov: Proveedor, url_base: str | None) -> str:
    base = (url_base or prov.url_base).rstrip("/")
    return f"{base}/messages" if prov.formato == "anthropic" else f"{base}/chat/completions"


def llamar(proveedor_id: str, modelo: str, payload: dict, clave: str, url_base: str | None = None, timeout: int = TIMEOUT_SEGUNDOS) -> dict:
    """Una consulta con UNA clave. Devuelve la respuesta con forma de OpenAI (`choices[0].message`) y `usage` normalizado. `ErrorIA` (con `codigo_http`) si falla."""
    prov = obtener(proveedor_id)
    if prov.formato == "anthropic":
        r = _http_json(_url_chat(prov, url_base), _a_anthropic({**payload, "messages": _preparar_mensajes(prov, payload["messages"])}, modelo), _cabeceras(prov, clave), timeout, [clave], prov.nombre)
        return _de_anthropic(r)
    r = _http_json(_url_chat(prov, url_base), _payload_openai(prov, modelo, payload, False), _cabeceras(prov, clave), timeout, [clave], prov.nombre)
    r["usage"] = _usage_openai(r)
    return r


def llamar_stream(proveedor_id: str, modelo: str, payload: dict, clave: str, url_base: str | None = None) -> Iterator[dict]:
    """Como `llamar`, pero en streaming: trozos con la forma de OpenAI. El fallo de clave solo puede darse al abrir la conexión (se propaga como `ErrorIA` antes del primer trozo)."""
    prov = obtener(proveedor_id)
    if prov.formato == "anthropic":
        cuerpo = {**_a_anthropic({**payload, "messages": _preparar_mensajes(prov, payload["messages"])}, modelo), "stream": True}
        yield from _chunks_de_anthropic(_eventos_sse(_abrir_stream(_url_chat(prov, url_base), cuerpo, _cabeceras(prov, clave), [clave], prov.nombre)))
        return
    resp = _abrir_stream(_url_chat(prov, url_base), _payload_openai(prov, modelo, payload, True), _cabeceras(prov, clave), [clave], prov.nombre)
    for chunk in _eventos_sse(resp):
        if chunk.get("usage"):
            chunk["usage"] = _usage_openai(chunk)
        yield chunk


_NO_CHAT = re.compile(r"(embed|whisper|tts|dall-e|moderation|davinci|babbage|audio|realtime|transcribe|image|speech|rerank|ocr)", re.I)


def listar_modelos(proveedor_id: str, clave: str, url_base: str | None = None, timeout: int = 15) -> list[str]:
    """Los identificadores de modelo que ofrece el proveedor con esa clave (sin los de voz, imágenes o embeddings), ordenados."""
    prov = obtener(proveedor_id)
    base = (url_base or prov.url_base).rstrip("/")
    r = _http_json(f"{base}/models", None, _cabeceras(prov, clave), timeout, [clave], prov.nombre, metodo="GET")
    ids = {str(m.get("id") or "").removeprefix("models/") for m in r.get("data") or r.get("models") or [] if isinstance(m, dict)}
    return sorted(i for i in ids if i and not _NO_CHAT.search(i))


def probar(proveedor_id: str, modelo: str, clave: str, url_base: str | None = None) -> str:
    """Comprueba que la clave y el modelo funcionan con una consulta mínima. Devuelve «» si va bien o el motivo legible si no."""
    try:
        llamar(proveedor_id, modelo, {"messages": [{"role": "user", "content": "Responde solo: ok"}], "max_tokens": 16}, clave, url_base, timeout=20)
        return ""
    except ErrorIA as e:
        if e.codigo_http in (401, 403):
            return "El proveedor no acepta la clave (revisa que esté completa y activa)."
        if e.codigo_http == 402:
            return "La clave no tiene saldo o crédito."
        if e.codigo_http == 404:
            return "El modelo no existe para esa clave (revisa el nombre)."
        if e.codigo_http == 429:
            return "El proveedor ha limitado las consultas de esa clave; inténtalo en un rato."
        return str(e)[:300]
