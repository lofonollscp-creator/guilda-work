"""Cliente HTTP de los conectores jurídicos. Solo habla con dominios de la lista blanca del conector (nunca con una URL que venga de un modelo o de un documento), no sigue redirecciones a
otro dominio, limita el tamaño y el tiempo, y reintenta con espera exponencial y jitter respetando `Retry-After`. El transporte es inyectable para las pruebas."""
from __future__ import annotations

import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

AGENTE = "GuildaWork-juridico/1 (+https://guilda.cat)"
MAX_BYTES_POR_DEFECTO = 60 * 1024 * 1024
MAX_ESPERA_RETRY_AFTER = 120.0


class ErrorHTTP(Exception):
    """Fallo de transporte. `transitorio` = merece la pena reintentar más tarde."""

    def __init__(self, mensaje: str, *, transitorio: bool, estado: int | None = None):
        super().__init__(mensaje)
        self.transitorio = transitorio
        self.estado = estado


@dataclass
class Respuesta:
    estado: int
    cuerpo: bytes
    cabeceras: dict = field(default_factory=dict)
    url: str = ""


class _SinRedireccionAjena(urllib.request.HTTPRedirectHandler):
    def __init__(self, permitidos):
        self.permitidos = permitidos

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname not in self.permitidos or not newurl.startswith("https://"):
            raise urllib.error.HTTPError(newurl, 403, "Redirección a un dominio no permitido", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _transporte_real(url: str, cabeceras: dict, timeout: float, max_bytes: int, permitidos) -> tuple[int, dict, bytes]:
    abridor = urllib.request.build_opener(_SinRedireccionAjena(permitidos))
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE, **cabeceras}, method="GET")
    try:
        with abridor.open(peticion, timeout=timeout) as r:
            cuerpo = r.read(max_bytes + 1)
            if len(cuerpo) > max_bytes:
                raise ErrorHTTP(f"La respuesta supera el tamaño máximo ({max_bytes} bytes).", transitorio=False)
            return r.status, dict(r.headers.items()), cuerpo
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()) if e.headers else {}, (e.read(2048) if hasattr(e, "read") else b"")


class ClienteHTTP:
    def __init__(self, dominios_permitidos: set[str] | frozenset[str], *, timeout: float = 30.0, max_bytes: int = MAX_BYTES_POR_DEFECTO, reintentos: int = 3, espera_base: float = 1.0,
                 transporte=None, dormir=time.sleep):
        self.permitidos = frozenset(dominios_permitidos)
        self.timeout, self.max_bytes, self.reintentos, self.espera_base = timeout, max_bytes, reintentos, espera_base
        self._transporte = transporte
        self._dormir = dormir

    def comprobar_url(self, url: str) -> None:
        partes = urllib.parse.urlsplit(url or "")
        if partes.scheme != "https" or partes.hostname not in self.permitidos or partes.username or partes.password:
            raise ErrorHTTP("La URL no pertenece a un dominio permitido para este conector.", transitorio=False)

    def get(self, url: str, cabeceras: dict | None = None) -> Respuesta:
        """GET con reintentos. Devuelve la respuesta aunque sea un 4xx (el conector decide qué significa un 404); un 429/5xx o un fallo de red se reintentan y, agotados, lanzan `ErrorHTTP`."""
        self.comprobar_url(url)
        ultimo: ErrorHTTP | None = None
        for intento in range(self.reintentos + 1):
            try:
                if self._transporte is not None:
                    estado, cab, cuerpo = self._transporte(url, cabeceras or {}, self.timeout)
                else:
                    estado, cab, cuerpo = _transporte_real(url, cabeceras or {}, self.timeout, self.max_bytes, self.permitidos)
            except ErrorHTTP as e:
                if not e.transitorio:
                    raise
                ultimo = e
                cab = {}
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                ultimo = ErrorHTTP(f"Fallo de red: {e}", transitorio=True)
                cab = {}
            else:
                if estado == 429 or estado >= 500:
                    ultimo = ErrorHTTP(f"El servidor respondió {estado}.", transitorio=True, estado=estado)
                else:
                    return Respuesta(estado, cuerpo, {k.lower(): v for k, v in cab.items()}, url)
            if intento < self.reintentos:
                self._dormir(self._espera(intento, cab))
        raise ultimo or ErrorHTTP("Sin respuesta.", transitorio=True)

    def _espera(self, intento: int, cabeceras: dict) -> float:
        retry = {k.lower(): v for k, v in (cabeceras or {}).items()}.get("retry-after")
        if retry and str(retry).strip().isdigit():
            return min(float(retry), MAX_ESPERA_RETRY_AFTER)
        return self.espera_base * (2 ** intento) * (0.75 + random.random() / 2)
