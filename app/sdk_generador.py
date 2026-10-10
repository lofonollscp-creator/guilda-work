"""Genera, a partir del documento OpenAPI de la propia API (`app/openapi.py`), un cliente de Python, un cliente de TypeScript y una
colección de Postman. Siempre salen del contrato vivo, así que nunca se quedan atrás: cada vez que se descargan reflejan las rutas
y los campos que hay en ese momento.

- **Python** (`guilda_work.py`): un solo fichero, solo biblioteca estándar. Reintenta con retroceso, respeta `Retry-After`, manda
  `Idempotency-Key` en los POST para que un reintento no duplique, mapea los errores a una excepción con `codigo` y `request_id`,
  pagina y sincroniza, y trae la verificación de la firma de los webhooks.
- **TypeScript** (`guilda-work.ts`): un solo fichero con `fetch` (Node 18+, navegadores, Deno, Bun), tipos de todas las entidades.
- **Postman** (`guilda-work.postman_collection.json`): carpetas por tema, variables `base_url` y `token`, ejemplos, y un script que
  guarda el token al hacer login y pone `Idempotency-Key` en los POST."""
from __future__ import annotations

import json
import keyword
import re
import textwrap

# --- Utilidades comunes -------------------------------------------------------------------------------------------------------

_METODOS = ("get", "post", "put", "delete", "patch")


def operaciones(spec: dict) -> list[dict]:
    """Lista plana de operaciones con lo que necesitan los tres generadores."""
    resultado = []
    for ruta, metodos in spec["paths"].items():
        for metodo, op in metodos.items():
            if metodo not in _METODOS:
                continue
            parametros = [p for p in op.get("parameters", []) if "$ref" not in p]
            exito = sorted(int(c) for c in op["responses"] if c.startswith("2"))
            codigo = exito[0] if exito else 200
            contenido = op["responses"].get(str(codigo), {}).get("content", {})
            resultado.append({
                "id": op["operationId"], "metodo": metodo.upper(), "ruta": ruta.removeprefix("/api/v1"), "resumen": op["summary"], "descripcion": op.get("description", ""),
                "etiqueta": op["tags"][0], "area": op.get("x-area", "libre"), "publica": not op.get("security"),
                "ruta_params": [p for p in parametros if p["in"] == "path"], "consulta": [p for p in parametros if p["in"] == "query"],
                "cuerpo": op.get("requestBody"), "codigo_exito": codigo, "respuesta": contenido, "paginada": any(p["name"] == "limit" for p in parametros if p["in"] == "query"),
                "ejemplo_peticion": ((op.get("requestBody") or {}).get("content", {}).get("application/json", {}) or {}).get("example"),
                "ejemplo_respuesta": next((c.get("example") for c in contenido.values() if "example" in c), None),
            })
    return resultado


def _resolver(esquema: dict, spec: dict) -> dict:
    while isinstance(esquema, dict) and "$ref" in esquema:
        nodo = spec
        for parte in esquema["$ref"].lstrip("#/").split("/"):
            nodo = nodo[parte]
        esquema = nodo
    return esquema


def _ident_py(nombre: str) -> str:
    limpio = re.sub(r"\W", "_", nombre)
    if not limpio or limpio[0].isdigit():
        limpio = "_" + limpio
    return limpio + "_" if keyword.iskeyword(limpio) else limpio


def _camel(nombre: str) -> str:
    partes = nombre.split("_")
    return partes[0] + "".join(p[:1].upper() + p[1:] for p in partes[1:])


def _pascal(nombre: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\W]+", nombre) if p)


def _campos_cuerpo(op: dict, spec: dict) -> tuple[dict, list[str], dict, bool]:
    """(propiedades JSON, obligatorios, archivos {nombre: varios?}, es_multipart_unico)."""
    if not op["cuerpo"]:
        return {}, [], {}, False
    contenido = op["cuerpo"]["content"]
    json_esq = contenido.get("application/json", {}).get("schema")
    multi = contenido.get("multipart/form-data", {}).get("schema")
    propiedades, requeridos = {}, []
    if json_esq:
        json_esq = _resolver(json_esq, spec)
        propiedades = dict(json_esq.get("properties", {})); requeridos = list(json_esq.get("required", []))
    archivos = {}
    if multi:
        for n, e in _resolver(multi, spec).get("properties", {}).items():
            e = _resolver(e, spec)
            es_lista = e.get("type") == "array"
            hijo = _resolver(e.get("items", {}), spec) if es_lista else e
            if hijo.get("format") == "binary":
                archivos[n] = es_lista
            elif not json_esq:
                propiedades[n] = e
        if not json_esq:
            requeridos = list(_resolver(multi, spec).get("required", []))
    return propiedades, requeridos, archivos, bool(multi and not json_esq)


# =====================================================================================================================================
# Python
# =====================================================================================================================================

_PY_CABECERA = '''\
"""Cliente de Python de la API de Guilda Work (versión de la API: {version}). Generado a partir del contrato OpenAPI de tu instancia:
vuelve a descargarlo cuando la API se amplíe. Solo usa la biblioteca estándar (Python 3.9+).

    from guilda_work import Cliente

    g = Cliente(token="TU_TOKEN", base_url="{base_url}")
    nota = g.crear_nota(texto="Llamar al cliente", referencia_externa="CRM-881")
    for tarea in g.paginar(g.listar_tareas_outlook, estado="en_progreso"):
        print(tarea["asunto"])

Cada método devuelve directamente el `data` de la respuesta. Los errores lanzan `ErrorGuilda` (con `.codigo`, `.status`, `.request_id`).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Iterator, Optional

VERSION_API = "{version}"


class ErrorGuilda(Exception):
    """Respuesta de error de la API. Programa contra `codigo` (estable), no contra el texto."""

    def __init__(self, status: int, codigo: str, mensaje: str, campo: Optional[str] = None, request_id: Optional[str] = None, cuerpo: Any = None):
        super().__init__("[{status}] {codigo}: {mensaje}".format(status=status, codigo=codigo, mensaje=mensaje))
        self.status, self.codigo, self.mensaje, self.campo, self.request_id, self.cuerpo = status, codigo, mensaje, campo, request_id, cuerpo


class RespuestaInfo:
    """Metadatos de la última respuesta: `status`, `cabeceras`, `request_id`, `total` (X-Total-Count) y `reintentos` realizados."""

    def __init__(self, status: int = 0, cabeceras: Optional[dict] = None, reintentos: int = 0):
        self.status, self.cabeceras, self.reintentos = status, {{k.lower(): v for k, v in (cabeceras or {{}}).items()}}, reintentos
        self.request_id = self.cabeceras.get("x-request-id")
        total = self.cabeceras.get("x-total-count")
        self.total = int(total) if total and total.isdigit() else None


def verificar_firma_webhook(cuerpo: bytes, cabeceras: dict, secreto: str, tolerancia_segundos: int = 300) -> bool:
    """Comprueba la firma de un webhook de Guilda Work (`X-Guilda-Signature-V2`, con marca de tiempo anti-repetición).
    `cuerpo` es el cuerpo CRUDO recibido, tal cual. Devuelve False si no coincide o si la marca tiene más de `tolerancia_segundos`."""
    cab = {{k.lower(): v for k, v in cabeceras.items()}}
    firma = cab.get("x-guilda-signature-v2", "")
    partes = dict(p.split("=", 1) for p in firma.split(",") if "=" in p)
    if "t" not in partes or "v1" not in partes or not partes["t"].isdigit():
        return False
    if abs(time.time() - int(partes["t"])) > tolerancia_segundos:
        return False
    esperada = hmac.new(secreto.encode(), f"{{partes['t']}}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, partes["v1"])


class Cliente:
    """Cliente de la API. `transporte(metodo, url, cabeceras, datos, timeout) -> (status, cabeceras, cuerpo_bytes)` permite cambiar
    el transporte (pruebas, proxies); por defecto usa `urllib`."""

    def __init__(self, token: Optional[str] = None, base_url: str = "{base_url}", timeout: float = 30.0, reintentos: int = 3,
                 transporte: Optional[Callable] = None, usar_etag: bool = False, esperar: Callable[[float], None] = time.sleep):
        self.token, self.base_url, self.timeout, self.reintentos = token, base_url.rstrip("/"), timeout, max(0, reintentos)
        self._transporte, self._esperar = transporte or self._transporte_urllib, esperar
        self._usar_etag, self._cache_etag = usar_etag, {{}}
        self.ultima = RespuestaInfo()

    # -- transporte ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def _transporte_urllib(metodo, url, cabeceras, datos, timeout):
        req = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    @staticmethod
    def _multipart(campos: dict, archivos: dict) -> tuple[bytes, str]:
        frontera = "----guilda" + uuid.uuid4().hex
        trozos: list[bytes] = []
        for nombre, valor in campos.items():
            if valor is None:
                continue
            valor = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
            trozos.append(f'--{{frontera}}\\r\\nContent-Disposition: form-data; name="{{nombre}}"\\r\\n\\r\\n{{valor}}\\r\\n'.encode())
        for nombre, lista in (archivos or {{}}).items():
            for item in (lista if isinstance(lista, list) else [lista]):
                fichero, contenido = (item if isinstance(item, tuple) else (nombre, item))[:2]
                tipo = (item[2] if isinstance(item, tuple) and len(item) > 2 else None) or mimetypes.guess_type(fichero)[0] or "application/octet-stream"
                trozos.append(f'--{{frontera}}\\r\\nContent-Disposition: form-data; name="{{nombre}}"; filename="{{fichero}}"\\r\\nContent-Type: {{tipo}}\\r\\n\\r\\n'.encode() + bytes(contenido) + b"\\r\\n")
        trozos.append(f"--{{frontera}}--\\r\\n".encode())
        return b"".join(trozos), f"multipart/form-data; boundary={{frontera}}"

    def _llamar(self, metodo: str, ruta: str, *, consulta: Optional[dict] = None, json_cuerpo: Optional[dict] = None, campos: Optional[dict] = None,
                archivos: Optional[dict] = None, idempotencia: bool = False, idempotency_key: Optional[str] = None, publica: bool = False,
                binaria: bool = False, sobre: bool = True, flujo: bool = False):
        url = self.base_url + "/api/v1" + ruta
        if consulta:
            q = {{k: (("true" if v else "false") if isinstance(v, bool) else (",".join(map(str, v)) if isinstance(v, (list, tuple)) else v)) for k, v in consulta.items() if v is not None}}
            if q:
                url += "?" + urllib.parse.urlencode(q)
        cabeceras = {{"Accept": "application/json", "X-Request-Id": uuid.uuid4().hex, "User-Agent": f"guilda-work-python/{{VERSION_API}}"}}
        if self.token and not publica:
            cabeceras["Authorization"] = "Bearer " + self.token
        datos = None
        if archivos:
            datos, cabeceras["Content-Type"] = self._multipart(campos or {{}}, archivos)
        elif json_cuerpo is not None:
            datos, cabeceras["Content-Type"] = json.dumps(json_cuerpo, ensure_ascii=False).encode(), "application/json"
        if idempotencia:
            cabeceras["Idempotency-Key"] = idempotency_key or uuid.uuid4().hex     # misma clave en cada reintento: no se duplica
        etag = self._cache_etag.get(url) if (self._usar_etag and metodo == "GET") else None
        if etag:
            cabeceras["If-None-Match"] = etag[0]
        intento = 0
        while True:
            try:
                status, cab, cuerpo = self._transporte(metodo, url, cabeceras, datos, self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                if intento < self.reintentos and (metodo in ("GET", "PUT", "DELETE") or idempotencia):
                    intento += 1; self._esperar(min(2 ** intento * 0.5, 10)); continue
                raise
            if status == 429 and intento < self.reintentos:
                intento += 1
                espera = next((v for k, v in cab.items() if k.lower() == "retry-after"), "1")
                self._esperar(min(float(espera) if str(espera).replace(".", "").isdigit() else 1.0, 60)); continue
            if status in (502, 503, 504) and intento < self.reintentos and (metodo in ("GET", "PUT", "DELETE") or idempotencia):
                intento += 1; self._esperar(min(2 ** intento * 0.5, 10)); continue
            break
        self.ultima = RespuestaInfo(status, cab, intento)
        if status == 304 and etag:
            return etag[1]
        if status >= 400:
            try:
                e = json.loads(cuerpo.decode("utf-8") or "{{}}")
            except ValueError:
                e = {{}}
            raise ErrorGuilda(status, e.get("codigo", "error"), e.get("error", cuerpo[:200].decode("utf-8", "replace")), e.get("campo"), e.get("request_id") or self.ultima.request_id, e)
        if flujo:
            return self._eventos(cuerpo)
        if binaria:
            return cuerpo
        if not cuerpo:
            return None
        cargado = json.loads(cuerpo.decode("utf-8"))
        resultado = cargado.get("data") if (sobre and isinstance(cargado, dict) and "ok" in cargado) else cargado
        if self._usar_etag and metodo == "GET" and self.ultima.cabeceras.get("etag"):
            self._cache_etag[url] = (self.ultima.cabeceras["etag"], resultado)
        return resultado

    @staticmethod
    def _eventos(cuerpo: bytes) -> Iterator[dict]:
        for linea in cuerpo.decode("utf-8", "replace").splitlines():
            if linea.startswith("data:"):
                try:
                    yield json.loads(linea[5:].strip())
                except ValueError:
                    continue

    # -- ayudantes ------------------------------------------------------------------------------------------------------------
    def paginar(self, metodo: Callable, por_pagina: int = 200, **filtros) -> Iterator[Any]:
        """Recorre todas las páginas de un listado: `for x in g.paginar(g.listar_notas, q="iva")`."""
        desplazamiento = 0
        while True:
            pagina = metodo(limit=por_pagina, offset=desplazamiento, **filtros)
            for elemento in pagina or []:
                yield elemento
            if not pagina or len(pagina) < por_pagina:
                return
            desplazamiento += por_pagina

    def sincronizar_desde(self, cursor: Optional[int] = None) -> Iterator[dict]:
        """Itera los lotes de cambios desde `cursor` (o desde ahora si es None, devolviendo solo el cursor). Cada lote trae
        `cambios`, `eliminados` y `cursor`; guarda el último cursor para la próxima vez."""
        if cursor is None:
            yield self.sincronizar()
            return
        while True:
            lote = self.sincronizar(cursor=cursor)
            yield lote
            cursor = lote["cursor"]
            if not lote["hay_mas"] or lote["reiniciar"]:
                return

    # -- operaciones (generadas) -----------------------------------------------------------------------------------------------
'''


def _tipo_py(esquema: dict, spec: dict) -> str:
    esquema = _resolver(esquema, spec)
    t = esquema.get("type")
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "array":
        return f"list[{_tipo_py(esquema.get('items', {}), spec)}]"
    if t == "object":
        return "dict"
    if t == "string":
        return "str"
    return "Any"


def _doc_py(op: dict, argumentos: list, archivos: dict) -> list:
    """Docstring: descripción de la ruta + lista de argumentos con su tipo, si son obligatorios y qué significan."""
    comillas = '"' * 3
    texto = (op["descripcion"] or op["resumen"]).replace("\\", "/").replace(comillas, "'" * 3).strip()
    lineas = []
    for parrafo in texto.split("\n\n"):
        lineas += textwrap.wrap(" ".join(parrafo.split()), 108) or [""]
        lineas.append("")
    if argumentos or archivos:
        lineas.append("Argumentos:")
        for nombre, tipo, obligatorio, descripcion in argumentos:
            envuelto = textwrap.wrap(f"{nombre} ({tipo}{', obligatorio' if obligatorio else ''}): {descripcion}".strip(": "), 104)
            lineas += ["  " + envuelto[0]] + ["      " + x for x in envuelto[1:]]
        for n, varios in archivos.items():
            lineas.append(f"  {n} (archivo{'s' if varios else ''}): `(nombre, bytes)` o `(nombre, bytes, tipo_mime)`" + (", o una lista de ellos." if varios else "."))
        lineas.append("")
    lineas.append(f"{op['metodo']} /api/v1{op['ruta']}  ·  área de token: {op['area']}  ·  éxito: {op['codigo_exito']}")
    return lineas


def _metodo_py(op: dict, spec: dict) -> str:
    propiedades, requeridos, archivos, _ = _campos_cuerpo(op, spec)
    usados = {_ident_py(p["name"]) for p in op["ruta_params"]}
    asignacion = {}      # nombre python -> (clave real, "q" consulta | "c" cuerpo | "f" archivo)
    argumentos = []
    firma_pos = []
    for p in op["ruta_params"]:
        firma_pos.append(f"{_ident_py(p['name'])}: {_tipo_py(p['schema'], spec)}")
        argumentos.append((_ident_py(p["name"]), _tipo_py(p["schema"], spec), True, p.get("description", "")))
    kw_req, kw_opc = [], []

    def añadir(nombre_api, esquema, donde, obligatorio, descripcion):
        nombre = _ident_py(nombre_api)
        if nombre in usados:
            nombre = _ident_py(nombre_api + "_" + ("consulta" if donde == "q" else "cuerpo"))
        usados.add(nombre)
        asignacion[nombre] = (nombre_api, donde)
        tipo = _tipo_py(esquema, spec)
        (kw_req if obligatorio else kw_opc).append(f"{nombre}: {tipo}" if obligatorio else f"{nombre}: Optional[{tipo}] = None")
        argumentos.append((nombre, tipo, obligatorio, descripcion or _resolver(esquema, spec).get("description", "")))

    for n, e in propiedades.items():
        if n not in archivos:
            añadir(n, e, "c", n in requeridos, _resolver(e, spec).get("description", ""))
    for p in op["consulta"]:
        añadir(p["name"], p["schema"], "q", False, p.get("description", ""))
    for n in archivos:
        kw_opc.append(f"{_ident_py(n)}: Optional[Any] = None")
        asignacion[_ident_py(n)] = (n, "f")
    es_post = op["metodo"] == "POST" and op["id"] not in {"enviar_mensaje_ia_stream", "confirmar_ia_stream"}
    if es_post:
        kw_opc.append("idempotency_key: Optional[str] = None")
        argumentos.append(("idempotency_key", "str", False, "cadena única para reintentar sin duplicar (si no la das, se genera una por llamada y se reutiliza en los reintentos)."))
    firma = ", ".join(["self"] + firma_pos + (["*"] + kw_req + kw_opc if (kw_req or kw_opc) else []))
    ruta = op["ruta"]
    for p in op["ruta_params"]:
        ruta = ruta.replace("{" + p["name"] + "}", "{urllib.parse.quote(str(" + _ident_py(p["name"]) + "), safe='')}")
    ruta_py = f'f"{ruta}"' if "{" in ruta else f'"{ruta}"'
    cuerpo_doc = _doc_py(op, argumentos, {_ident_py(n): v for n, v in archivos.items()})
    comillas = '"' * 3
    lineas = [f"    def {op['id']}({firma}) -> Any:", "        " + comillas + cuerpo_doc[0]]
    lineas += [("        " + d) if d else "" for d in cuerpo_doc[1:]] + ["        " + comillas]
    q_items = ", ".join(f'"{asignacion[n][0]}": {n}' for n in asignacion if asignacion[n][1] == "q")
    c_items = ", ".join(f'"{asignacion[n][0]}": {n}' for n in asignacion if asignacion[n][1] == "c")
    f_items = ", ".join(f'"{asignacion[n][0]}": {n}' for n in asignacion if asignacion[n][1] == "f")
    args = [f'"{op["metodo"]}"', ruta_py]
    if q_items:
        args.append(f"consulta={{{q_items}}}")
    hay_cuerpo = bool(c_items) or (op["cuerpo"] and "application/json" in op["cuerpo"]["content"])
    if f_items:
        lineas.append(f"        _archivos = {{k: v for k, v in {{{f_items}}}.items() if v is not None}}")
        lineas.append(f"        _campos = {{k: v for k, v in {{{c_items}}}.items() if v is not None}}")
        args += ["campos=_campos", "archivos=_archivos or None"]
    elif hay_cuerpo:
        lineas.append(f"        _cuerpo = {{k: v for k, v in {{{c_items}}}.items() if v is not None}}")
        args.append("json_cuerpo=_cuerpo")
    if es_post:
        args += ["idempotencia=True", "idempotency_key=idempotency_key"]
    if op["publica"]:
        args.append("publica=True")
    mime = next(iter(op["respuesta"]), "")
    if mime == "text/event-stream":
        args.append("flujo=True")
    elif mime and mime != "application/json":
        args.append("binaria=True")
    elif op["id"] == "openapi_json":
        args.append("sobre=False")
    llamada = f"self._llamar({', '.join(args)})"
    if op["id"] in ("login", "registro"):
        lineas += [f"        sesion = {llamada}", '        if sesion and sesion.get("token"):', '            self.token = sesion["token"]', "        return sesion"]
    else:
        lineas.append(f"        return {llamada}")
    return "\n".join(lineas) + "\n"


def generar_python(spec: dict, base_url: str = "https://app.guildawork.com") -> str:
    cabecera = _PY_CABECERA.replace("{version}", spec["info"]["version"]).replace("{base_url}", base_url)
    # las llaves dobles del texto base se escribieron para str.format: se resuelven aquí sin usar format (que chocaría con las f-strings internas)
    cabecera = cabecera.replace("{{", "{").replace("}}", "}")
    cuerpo = []
    for etiqueta in sorted({o["etiqueta"] for o in operaciones(spec)}):
        cuerpo.append(f"    # --- {etiqueta} " + "-" * max(4, 100 - len(etiqueta)))
        for op in sorted((o for o in operaciones(spec) if o["etiqueta"] == etiqueta), key=lambda o: (o["ruta"], o["metodo"])):
            cuerpo.append(_metodo_py(op, spec))
    return cabecera + "\n".join(cuerpo)


# =====================================================================================================================================
# TypeScript
# =====================================================================================================================================

_TS_CABECERA = """\
/**
 * Cliente de TypeScript de la API de Guilda Work (versión de la API: __VERSION__). Generado del contrato OpenAPI de tu instancia:
 * vuelve a descargarlo cuando la API se amplíe. Un solo fichero, sin dependencias: usa `fetch` (Node 18+, navegadores, Deno, Bun).
 *
 *     import { GuildaWork } from "./guilda-work";
 *     const g = new GuildaWork({ token: "TU_TOKEN", baseUrl: "__BASE_URL__" });
 *     const nota = await g.crearNota({ texto: "Llamar al cliente", referencia_externa: "CRM-881" });
 *     for await (const t of g.paginar((limit, offset) => g.listarTareasOutlook({ limit, offset }))) console.log(t.asunto);
 *
 * Cada método devuelve el `data` de la respuesta. Los errores lanzan `ErrorGuilda` (con `.codigo`, `.status`, `.requestId`).
 * Los POST llevan `Idempotency-Key` y se reintentan sin duplicar. Los argumentos de camino van primero, luego el cuerpo y luego la consulta.
 */

export const VERSION_API = "__VERSION__";

export class ErrorGuilda extends Error {
  constructor(public status: number, public codigo: string, mensaje: string, public campo?: string, public requestId?: string, public cuerpo?: unknown) {
    super(`[${status}] ${codigo}: ${mensaje}`);
    this.name = "ErrorGuilda";
  }
}

export interface RespuestaInfo { status: number; cabeceras: Record<string, string>; requestId?: string; total?: number; reintentos: number }

export type Archivo = Blob | { nombre: string; contenido: Uint8Array | Blob; tipo?: string };

export interface OpcionesCliente {
  token?: string;
  baseUrl?: string;
  /** Implementación de fetch (por defecto la global). */
  fetch?: typeof fetch;
  reintentos?: number;
  timeoutMs?: number;
  usarEtag?: boolean;
  /** Espera entre reintentos (inyectable en pruebas). */
  esperar?: (ms: number) => Promise<void>;
}

interface OpcionesLlamada {
  consulta?: Record<string, unknown>;
  cuerpo?: unknown;
  campos?: Record<string, unknown>;
  archivos?: Record<string, Archivo | Archivo[]>;
  idempotente?: boolean;
  idempotencyKey?: string;
  publica?: boolean;
  binaria?: boolean;
  flujo?: boolean;
  sobre?: boolean;
}

/** Comprueba la firma de un webhook de Guilda Work (`X-Guilda-Signature-V2`, con marca de tiempo anti-repetición). `cuerpo` es el cuerpo CRUDO recibido. */
export async function verificarFirmaWebhook(cuerpo: string | Uint8Array, cabeceras: Record<string, string>, secreto: string, toleranciaSegundos = 300): Promise<boolean> {
  const cab: Record<string, string> = {};
  for (const [k, v] of Object.entries(cabeceras)) cab[k.toLowerCase()] = v;
  const partes: Record<string, string> = {};
  for (const trozo of (cab["x-guilda-signature-v2"] ?? "").split(",")) {
    const i = trozo.indexOf("=");
    if (i > 0) partes[trozo.slice(0, i)] = trozo.slice(i + 1);
  }
  if (!partes.t || !partes.v1 || !/^\\d+$/.test(partes.t)) return false;
  if (Math.abs(Date.now() / 1000 - Number(partes.t)) > toleranciaSegundos) return false;
  const enc = new TextEncoder();
  const datos = typeof cuerpo === "string" ? enc.encode(cuerpo) : cuerpo;
  const clave = await crypto.subtle.importKey("raw", enc.encode(secreto), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const prefijo = enc.encode(`${partes.t}.`);
  const mensaje = new Uint8Array(prefijo.length + datos.length);
  mensaje.set(prefijo); mensaje.set(datos, prefijo.length);
  const firma = new Uint8Array(await crypto.subtle.sign("HMAC", clave, mensaje));
  const esperada = Array.from(firma).map((b) => b.toString(16).padStart(2, "0")).join("");
  return esperada.length === partes.v1.length && esperada === partes.v1;
}

function uuid(): string {
  return (globalThis.crypto && "randomUUID" in globalThis.crypto) ? globalThis.crypto.randomUUID().replace(/-/g, "") : Math.random().toString(16).slice(2) + Date.now().toString(16);
}

export class GuildaWork {
  token?: string;
  baseUrl: string;
  ultima: RespuestaInfo = { status: 0, cabeceras: {}, reintentos: 0 };
  private _fetch: typeof fetch;
  private _reintentos: number;
  private _timeoutMs: number;
  private _usarEtag: boolean;
  private _etags = new Map<string, { etag: string; datos: unknown }>();
  private _esperar: (ms: number) => Promise<void>;

  constructor(o: OpcionesCliente = {}) {
    this.token = o.token;
    this.baseUrl = (o.baseUrl ?? "__BASE_URL__").replace(/\\/+$/, "");
    this._fetch = o.fetch ?? ((...a) => fetch(...a));
    this._reintentos = Math.max(0, o.reintentos ?? 3);
    this._timeoutMs = o.timeoutMs ?? 30000;
    this._usarEtag = o.usarEtag ?? false;
    this._esperar = o.esperar ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  }

  private async llamar<T>(metodo: string, ruta: string, o: OpcionesLlamada = {}): Promise<T> {
    let url = `${this.baseUrl}/api/v1${ruta}`;
    if (o.consulta) {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(o.consulta)) if (v !== undefined && v !== null) q.set(k, Array.isArray(v) ? v.join(",") : String(v));
      if (q.toString()) url += `?${q}`;
    }
    const cabeceras: Record<string, string> = { Accept: "application/json", "X-Request-Id": uuid() };
    if (this.token && !o.publica) cabeceras["Authorization"] = `Bearer ${this.token}`;
    let cuerpo: BodyInit | undefined;
    if (o.archivos) {
      const f = new FormData();
      for (const [k, v] of Object.entries(o.campos ?? {})) if (v !== undefined && v !== null) f.append(k, typeof v === "string" ? v : JSON.stringify(v));
      for (const [k, v] of Object.entries(o.archivos)) {
        for (const a of Array.isArray(v) ? v : [v]) {
          if (a instanceof Blob) f.append(k, a);
          else f.append(k, a.contenido instanceof Blob ? a.contenido : new Blob([a.contenido as BlobPart], { type: a.tipo }), a.nombre);
        }
      }
      cuerpo = f;
    } else if (o.cuerpo !== undefined) {
      cuerpo = JSON.stringify(o.cuerpo);
      cabeceras["Content-Type"] = "application/json";
    }
    if (o.idempotente) cabeceras["Idempotency-Key"] = o.idempotencyKey ?? uuid();   // la misma clave en cada reintento: no se duplica
    const guardado = this._usarEtag && metodo === "GET" ? this._etags.get(url) : undefined;
    if (guardado) cabeceras["If-None-Match"] = guardado.etag;
    let intento = 0;
    for (;;) {
      let r: Response;
      try {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), this._timeoutMs);
        try { r = await this._fetch(url, { method: metodo, headers: cabeceras, body: cuerpo, signal: ctl.signal }); } finally { clearTimeout(t); }
      } catch (e) {
        if (intento < this._reintentos && (["GET", "PUT", "DELETE"].includes(metodo) || o.idempotente)) { intento++; await this._esperar(Math.min(2 ** intento * 500, 10000)); continue; }
        throw e;
      }
      if (r.status === 429 && intento < this._reintentos) {
        intento++; const espera = Number(r.headers.get("retry-after") ?? "1");
        await this._esperar(Math.min(Number.isFinite(espera) ? espera : 1, 60) * 1000); continue;
      }
      if ([502, 503, 504].includes(r.status) && intento < this._reintentos && (["GET", "PUT", "DELETE"].includes(metodo) || o.idempotente)) { intento++; await this._esperar(Math.min(2 ** intento * 500, 10000)); continue; }
      const cab: Record<string, string> = {};
      r.headers.forEach((v, k) => { cab[k.toLowerCase()] = v; });
      const total = cab["x-total-count"];
      this.ultima = { status: r.status, cabeceras: cab, requestId: cab["x-request-id"], total: total && /^\\d+$/.test(total) ? Number(total) : undefined, reintentos: intento };
      if (r.status === 304 && guardado) return guardado.datos as T;
      if (r.status >= 400) {
        const e = (await r.json().catch(() => ({}))) as { codigo?: string; error?: string; campo?: string; request_id?: string };
        throw new ErrorGuilda(r.status, e.codigo ?? "error", e.error ?? r.statusText, e.campo, e.request_id ?? this.ultima.requestId, e);
      }
      if (o.binaria) return new Uint8Array(await r.arrayBuffer()) as unknown as T;
      if (o.flujo) {
        const texto = await r.text();
        return texto.split("\\n").filter((l) => l.startsWith("data:")).map((l) => { try { return JSON.parse(l.slice(5)); } catch { return undefined; } }).filter((x) => x !== undefined) as unknown as T;
      }
      const texto = await r.text();
      if (!texto) return undefined as T;
      const json = JSON.parse(texto);
      const resultado = (o.sobre !== false && json && typeof json === "object" && "ok" in json ? json.data : json) as T;
      if (this._usarEtag && metodo === "GET" && cab["etag"]) this._etags.set(url, { etag: cab["etag"], datos: resultado });
      return resultado;
    }
  }

  /** Recorre todas las páginas de un listado: `for await (const x of g.paginar((limit, offset) => g.listarNotas({ limit, offset })))`. */
  async *paginar<T>(pagina: (limit: number, offset: number) => Promise<T[]>, porPagina = 200): AsyncGenerator<T> {
    for (let offset = 0; ; offset += porPagina) {
      const filas = (await pagina(porPagina, offset)) ?? [];
      for (const f of filas) yield f;
      if (filas.length < porPagina) return;
    }
  }

  // -- operaciones (generadas) ---------------------------------------------------------------------------------------------------
"""


def _ts_clave(nombre: str) -> str:
    return nombre if re.fullmatch(r"[A-Za-z_$][\w$]*", nombre) else json.dumps(nombre)


def _ts_tipo(esquema: dict, nivel: int = 0) -> str:
    if not isinstance(esquema, dict) or not esquema:
        return "unknown"
    if "$ref" in esquema:
        return esquema["$ref"].split("/")[-1]
    if "allOf" in esquema:
        return " & ".join(_ts_tipo(s, nivel) for s in esquema["allOf"])
    base: str
    if "enum" in esquema:
        base = " | ".join(json.dumps(v) for v in esquema["enum"])
    else:
        t = esquema.get("type")
        if t in ("integer", "number"):
            base = "number"
        elif t == "boolean":
            base = "boolean"
        elif t == "string":
            base = "Blob | Uint8Array" if esquema.get("format") == "binary" else "string"
        elif t == "array":
            interior = _ts_tipo(esquema.get("items", {}), nivel + 1)
            base = f"({interior})[]" if ("|" in interior or "&" in interior) else f"{interior}[]"
        elif t == "object" or "properties" in esquema:
            requeridos = set(esquema.get("required", []))
            props = esquema.get("properties", {})
            if props:
                relleno = "  " * (nivel + 1)
                trozos = [f"{relleno}{_ts_clave(n)}{'' if n in requeridos else '?'}: {_ts_tipo(e, nivel + 1)};" for n, e in props.items()]
                if esquema.get("additionalProperties", True) is not False:
                    trozos.append(f"{relleno}[clave: string]: unknown;")
                base = "{\n" + "\n".join(trozos) + "\n" + "  " * nivel + "}"
            elif isinstance(esquema.get("additionalProperties"), dict):
                base = f"{{ [clave: string]: {_ts_tipo(esquema['additionalProperties'], nivel + 1)} }}"
            else:
                base = "{ [clave: string]: unknown }"
        else:
            base = "unknown"
    return f"({base}) | null" if esquema.get("nullable") and "|" in base else (f"{base} | null" if esquema.get("nullable") else base)


def _ts_dato_de_respuesta(op: dict, spec: dict) -> str:
    mime = next(iter(op["respuesta"]), "")
    if mime == "text/event-stream":
        return "unknown[]"
    if mime and mime != "application/json":
        return "Uint8Array"
    esquema = next((c["schema"] for c in op["respuesta"].values()), {})
    if op["id"] == "openapi_json":
        return "Record<string, unknown>"
    dato = _resolver(esquema, spec).get("properties", {}).get("data")
    return _ts_tipo(dato) if dato is not None else "void"


def generar_typescript(spec: dict, base_url: str = "https://app.guildawork.com") -> str:
    salida = [_TS_CABECERA.replace("__VERSION__", spec["info"]["version"]).replace("__BASE_URL__", base_url).replace("\\\\", "\\")]
    cuerpo_metodos, tipos_op = [], []
    for etiqueta in sorted({o["etiqueta"] for o in operaciones(spec)}):
        cuerpo_metodos.append(f"\n  // --- {etiqueta} " + "-" * max(4, 100 - len(etiqueta)))
        for op in sorted((o for o in operaciones(spec) if o["etiqueta"] == etiqueta), key=lambda o: (o["ruta"], o["metodo"])):
            nombre, pascal = _camel(op["id"]), _pascal(op["id"])
            propiedades, requeridos, archivos, _ = _campos_cuerpo(op, spec)
            pos = [f"{_camel(_ident_py(p['name']).rstrip('_'))}: {'number' if p['schema'].get('type') == 'integer' else 'string'}" for p in op["ruta_params"]]
            ruta = op["ruta"]
            for p in op["ruta_params"]:
                ruta = ruta.replace("{" + p["name"] + "}", "${encodeURIComponent(String(" + _camel(_ident_py(p["name"]).rstrip("_")) + "))}")
            params = list(pos)
            llamada = [f'"{op["metodo"]}"', f"`{ruta}`" if "${" in ruta else f'"{ruta}"']
            propias = {n: e for n, e in propiedades.items() if n not in archivos}
            if propias:
                lineas = [f"  {_ts_clave(n)}{'' if n in requeridos else '?'}: {_ts_tipo(e, 1)};" for n, e in propias.items()]
                tipos_op.append(f"/** Cuerpo de `{op['id']}`. */\nexport interface {pascal}Cuerpo {{\n" + "\n".join(lineas) + "\n}")
                params.append(f"cuerpo: {pascal}Cuerpo" if requeridos else f"cuerpo: {pascal}Cuerpo = {{}}")
            consulta = [p for p in op["consulta"]]
            if consulta:
                lineas = [f"  {_ts_clave(p['name'])}?: {_ts_tipo(p['schema'], 1)};" + (f"  // {p['description'][:80]}" if p.get("description") else "") for p in consulta]
                tipos_op.append(f"/** Parámetros de consulta de `{op['id']}`. */\nexport interface {pascal}Consulta {{\n" + "\n".join(lineas) + "\n}")
                params.append(f"consulta: {pascal}Consulta = {{}}")
            es_post = op["metodo"] == "POST" and op["id"] not in {"enviar_mensaje_ia_stream", "confirmar_ia_stream"}
            extra = []
            if archivos:
                extra.append("archivos?: Record<string, Archivo | Archivo[]>")
            if es_post:
                extra.append("idempotencyKey?: string")
            if extra:
                params.append("extra: { " + "; ".join(extra) + " } = {}")
            opciones = []
            if consulta:
                opciones.append("consulta: consulta as unknown as Record<string, unknown>")
            if propias and not archivos:
                opciones.append("cuerpo")
            if archivos:
                opciones += ["campos: " + ("cuerpo as unknown as Record<string, unknown>" if propias else "{}"), "archivos: extra.archivos"]
            if es_post:
                opciones += ["idempotente: true", "idempotencyKey: extra.idempotencyKey"]
            if op["publica"]:
                opciones.append("publica: true")
            mime = next(iter(op["respuesta"]), "")
            if mime == "text/event-stream":
                opciones.append("flujo: true")
            elif mime and mime != "application/json":
                opciones.append("binaria: true")
            elif op["id"] == "openapi_json":
                opciones.append("sobre: false")
            retorno = _ts_dato_de_respuesta(op, spec)
            doc = (op["descripcion"] or op["resumen"]).replace("*/", "* /").strip()
            doc_lineas = ["  /**"] + [("   * " + l).rstrip() for l in doc.splitlines()] + ["   *", f"   * `{op['metodo']} /api/v1{op['ruta']}` · área de token: {op['area']} · éxito: {op['codigo_exito']}", "   */"]
            cuerpo_llamada = f"this.llamar<{retorno}>({', '.join(llamada)}{', { ' + ', '.join(opciones) + ' }' if opciones else ''})"
            if op["id"] in ("login", "registro"):
                firma = f"  async {nombre}({', '.join(params)}): Promise<{retorno}> {{"
                cuerpo = [f"    const sesion = await {cuerpo_llamada};", '    if (sesion && (sesion as { token?: string }).token) this.token = (sesion as { token: string }).token;', "    return sesion;"]
            else:
                firma = f"  async {nombre}({', '.join(params)}): Promise<{retorno}> {{"
                cuerpo = [f"    return {cuerpo_llamada};"]
            cuerpo_metodos += doc_lineas + [firma] + cuerpo + ["  }", ""]
    # tipos de las entidades
    tipos_entidades = []
    for nombre, esquema in sorted(spec["components"]["schemas"].items()):
        if esquema.get("type") == "object" and "properties" in esquema and "allOf" not in esquema:
            requeridos = set(esquema.get("required", []))
            lineas = [f"  {_ts_clave(n)}{'' if n in requeridos else '?'}: {_ts_tipo(e, 1)};" for n, e in esquema["properties"].items()]
            if esquema.get("additionalProperties", True) is not False:
                lineas.append("  [clave: string]: unknown;")
            tipos_entidades.append(f"export interface {nombre} {{\n" + "\n".join(lineas) + "\n}")
        else:
            tipos_entidades.append(f"export type {nombre} = {_ts_tipo(esquema)};")
    return "\n".join(salida[:1]) + "\n".join(cuerpo_metodos) + "}\n\n// ===== Entidades =====\n\n" + "\n\n".join(tipos_entidades) + "\n\n// ===== Cuerpos y consultas de cada operación =====\n\n" + "\n\n".join(tipos_op) + "\n"


# =====================================================================================================================================
# Postman
# =====================================================================================================================================

def _ejemplo_de_esquema(esquema: dict, spec: dict, profundidad: int = 0):
    """Valor de ejemplo sencillo para rellenar un cuerpo cuando no hay un ejemplo escrito."""
    esquema = _resolver(esquema, spec)
    if "example" in esquema:
        return esquema["example"]
    if "enum" in esquema:
        return esquema["enum"][0]
    t = esquema.get("type")
    if t == "integer":
        return 1
    if t == "number":
        return 1.5
    if t == "boolean":
        return True
    if t == "array":
        return [] if profundidad > 1 else [_ejemplo_de_esquema(esquema.get("items", {}), spec, profundidad + 1)]
    if t == "object":
        return {} if profundidad > 1 else {n: _ejemplo_de_esquema(e, spec, profundidad + 1) for n, e in list(esquema.get("properties", {}).items())[:8]}
    fmt = esquema.get("format")
    return {"date": "2026-10-20", "date-time": "2026-10-20T09:00:00", "email": "persona@ejemplo.com", "uri": "https://ejemplo.com/hook"}.get(fmt, "texto")


_SCRIPT_PREVIO = """\
// Cada POST lleva su propia Idempotency-Key (un reintento manual con la misma petición no duplica si la reutilizas) y todas las peticiones un X-Request-Id.
if (pm.request.method === "POST" && !pm.request.headers.has("Idempotency-Key")) {
  pm.request.headers.add({ key: "Idempotency-Key", value: pm.variables.replaceIn("{{$guid}}") });
}
if (!pm.request.headers.has("X-Request-Id")) {
  pm.request.headers.add({ key: "X-Request-Id", value: pm.variables.replaceIn("{{$guid}}").replace(/-/g, "") });
}
"""

_SCRIPT_TEST = """\
pm.test("Respuesta correcta", function () {
  pm.expect(pm.response.code).to.be.below(400);
  const t = pm.response.headers.get("Content-Type") || "";
  if (t.includes("application/json")) { pm.expect(pm.response.json().ok).to.eql(true); }
});
"""

_SCRIPT_TOKEN = """\
const cuerpo = pm.response.json();
if (cuerpo.ok && cuerpo.data && cuerpo.data.token) { pm.collectionVariables.set("token", cuerpo.data.token); }
"""


def generar_postman(spec: dict, base_url: str = "https://app.guildawork.com") -> dict:
    ops = operaciones(spec)
    carpetas = []
    for etiqueta in sorted({o["etiqueta"] for o in ops}):
        descripcion = next((t["description"] for t in spec.get("tags", []) if t["name"] == etiqueta), "")
        items = []
        for op in sorted((o for o in ops if o["etiqueta"] == etiqueta), key=lambda o: (o["ruta"], o["metodo"])):
            propiedades, requeridos, archivos, _ = _campos_cuerpo(op, spec)
            partes = [x for x in op["ruta"].split("/") if x]
            ruta_postman = [":" + x[1:-1] if x.startswith("{") else x for x in partes]
            variables = [{"key": p["name"], "value": "1", "description": p.get("description", "")} for p in op["ruta_params"]]
            consulta = [{"key": p["name"], "value": "", "disabled": True, "description": p.get("description", "")} for p in op["consulta"]]
            raw = "{{base_url}}/api/v1/" + "/".join(ruta_postman)
            peticion = {"method": op["metodo"], "header": [], "url": {"raw": raw, "host": ["{{base_url}}"], "path": ["api", "v1", *ruta_postman], "variable": variables, "query": consulta},
                        "description": "\n\n".join(x for x in (op["descripcion"] or op["resumen"], f"Área de token: `{op['area']}`.") if x)}
            contenido = (op["cuerpo"] or {}).get("content", {})
            if "application/json" in contenido:
                ejemplo = op["ejemplo_peticion"]
                if ejemplo is None:
                    ejemplo = {n: _ejemplo_de_esquema(e, spec) for n, e in propiedades.items() if n in requeridos} or {n: _ejemplo_de_esquema(e, spec) for n, e in list(propiedades.items())[:3]}
                peticion["header"].append({"key": "Content-Type", "value": "application/json"})
                peticion["body"] = {"mode": "raw", "raw": json.dumps(ejemplo, indent=2, ensure_ascii=False), "options": {"raw": {"language": "json"}}}
            elif "multipart/form-data" in contenido:
                filas = [{"key": n, "type": "file", "src": []} for n in archivos]
                filas += [{"key": n, "value": "", "type": "text", "description": _resolver(e, spec).get("description", "")} for n, e in propiedades.items() if n not in archivos]
                peticion["body"] = {"mode": "formdata", "formdata": filas}
            if op["publica"]:
                peticion["auth"] = {"type": "noauth"}
            respuestas = []
            if op["ejemplo_respuesta"] is not None:
                respuestas.append({"name": f"Ejemplo {op['codigo_exito']}", "originalRequest": peticion, "status": "OK" if op["codigo_exito"] == 200 else "Created" if op["codigo_exito"] == 201 else "Accepted",
                                   "code": op["codigo_exito"], "header": [{"key": "Content-Type", "value": "application/json"}],
                                   "body": json.dumps(op["ejemplo_respuesta"], indent=2, ensure_ascii=False)})
            eventos = []
            if "json" in next(iter(op["respuesta"]), "application/json"):
                eventos.append({"listen": "test", "script": {"type": "text/javascript", "exec": (_SCRIPT_TEST + (_SCRIPT_TOKEN if op["id"] in ("login", "registro") else "")).splitlines()}})
            items.append({"name": f"{op['resumen']}", "request": peticion, "response": respuestas, **({"event": eventos} if eventos else {}),
                          "id": op["id"]})
        carpetas.append({"name": etiqueta, "description": descripcion, "item": items})
    return {
        "info": {"name": "Guilda Work API", "description": spec["info"]["description"], "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                 "version": spec["info"]["version"]},
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
        "variable": [{"key": "base_url", "value": base_url, "type": "string"}, {"key": "token", "value": "", "type": "string",
                     "description": "Pega aquí tu token de API, o ejecuta «login» y se guarda solo."}],
        "event": [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": _SCRIPT_PREVIO.splitlines()}}],
        "item": carpetas,
    }
