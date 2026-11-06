"""Gasto de AWS del mes en el panel de salud, con aviso al pasar un umbral. Habla con AWS Cost Explorer (la API firma las peticiones con SigV4; aquí va firmada a mano con `requests`) usando una
clave **solo de lectura de costes** (`GUILDA_AWS_COSTES_ACCESS_KEY` / `GUILDA_AWS_COSTES_SECRET_KEY`: permisos `ce:GetCostAndUsage` y `ce:GetCostForecast` y nada más). Cost Explorer cobra por
petición, así que el resultado se guarda en memoria unas horas. Sin claves no hace nada (el panel lo muestra en gris)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from datetime import date, datetime, timedelta

import requests

HOST = "ce.us-east-1.amazonaws.com"             # Cost Explorer vive en us-east-1 sea cual sea la región de los recursos
REGION = "us-east-1"
SERVICIO = "ce"
TTL_SEGUNDOS = 6 * 3600
UMBRAL_DEFECTO_USD = 50.0
AMBAR_PCT = 80

_cache: dict = {}
_cerrojo = threading.Lock()


class ErrorCostes(Exception):
    pass


def configurado() -> bool:
    return bool(os.environ.get("GUILDA_AWS_COSTES_ACCESS_KEY") and os.environ.get("GUILDA_AWS_COSTES_SECRET_KEY"))


def umbral_usd() -> float:
    try:
        return float(os.environ.get("GUILDA_AWS_COSTES_UMBRAL_USD", "") or UMBRAL_DEFECTO_USD)
    except ValueError:
        return UMBRAL_DEFECTO_USD


def _hmac(clave: bytes, texto: str) -> bytes:
    return hmac.new(clave, texto.encode(), hashlib.sha256).digest()


def firmar(metodo: str, ruta: str, cuerpo: bytes, cabeceras: dict, acceso: str, secreto: str, ahora: datetime, sesion: str | None = None) -> dict:
    """Cabeceras de una petición firmada con AWS Signature Version 4 (host, `x-amz-date`, `x-amz-target`, … y `Authorization`)."""
    fecha_hora, fecha = ahora.strftime("%Y%m%dT%H%M%SZ"), ahora.strftime("%Y%m%d")
    h = {k.lower(): str(v).strip() for k, v in cabeceras.items()}
    h["x-amz-date"] = fecha_hora
    if sesion:
        h["x-amz-security-token"] = sesion
    nombres = sorted(h)
    canonicas = "".join(f"{n}:{h[n]}\n" for n in nombres)
    firmadas = ";".join(nombres)
    peticion = "\n".join([metodo, ruta, "", canonicas, firmadas, hashlib.sha256(cuerpo).hexdigest()])
    ambito = f"{fecha}/{REGION}/{SERVICIO}/aws4_request"
    a_firmar = "\n".join(["AWS4-HMAC-SHA256", fecha_hora, ambito, hashlib.sha256(peticion.encode()).hexdigest()])
    clave = _hmac(_hmac(_hmac(_hmac(("AWS4" + secreto).encode(), fecha), REGION), SERVICIO), "aws4_request")
    firma = hmac.new(clave, a_firmar.encode(), hashlib.sha256).hexdigest()
    h["authorization"] = f"AWS4-HMAC-SHA256 Credential={acceso}/{ambito}, SignedHeaders={firmadas}, Signature={firma}"
    return h


def _llamar(operacion: str, cuerpo: dict, ahora: datetime | None = None) -> dict:
    acceso, secreto = os.environ.get("GUILDA_AWS_COSTES_ACCESS_KEY", ""), os.environ.get("GUILDA_AWS_COSTES_SECRET_KEY", "")
    if not (acceso and secreto):
        raise ErrorCostes("Faltan las claves de costes de AWS.")
    datos = json.dumps(cuerpo).encode()
    cabeceras = firmar("POST", "/", datos, {"host": HOST, "content-type": "application/x-amz-json-1.1", "x-amz-target": f"AWSInsightsIndexService.{operacion}"}, acceso, secreto,
                       ahora or datetime.utcnow(), os.environ.get("GUILDA_AWS_COSTES_SESSION_TOKEN") or None)
    try:
        r = requests.post(f"https://{HOST}/", data=datos, headers=cabeceras, timeout=15)
    except requests.RequestException as e:
        raise ErrorCostes(f"No se pudo hablar con AWS: {e.__class__.__name__}") from None
    if r.status_code != 200:
        try:
            mensaje = r.json().get("message") or r.json().get("Message") or r.text[:120]
        except ValueError:
            mensaje = r.text[:120]
        raise ErrorCostes(f"AWS respondió {r.status_code}: {mensaje}")
    return r.json()


def consultar(hoy: date | None = None) -> dict:
    """{mes, gasto_usd, previsto_usd (o None), servicios: [(nombre, usd)] los 5 mayores}. Lanza ErrorCostes si no se puede."""
    hoy = hoy or date.today()
    inicio, fin = hoy.replace(day=1), hoy + timedelta(days=1)
    gastos = _llamar("GetCostAndUsage", {"TimePeriod": {"Start": inicio.isoformat(), "End": fin.isoformat()}, "Granularity": "MONTHLY", "Metrics": ["UnblendedCost"],
                                          "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}]})
    por_servicio: dict[str, float] = {}
    for periodo in gastos.get("ResultsByTime", []):
        for g in periodo.get("Groups", []):
            por_servicio[g["Keys"][0]] = por_servicio.get(g["Keys"][0], 0.0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
    total = round(sum(por_servicio.values()), 2)
    previsto = None
    siguiente_mes = (inicio + timedelta(days=32)).replace(day=1)
    if hoy < siguiente_mes - timedelta(days=1):
        try:
            p = _llamar("GetCostForecast", {"TimePeriod": {"Start": fin.isoformat(), "End": siguiente_mes.isoformat()}, "Granularity": "MONTHLY", "Metric": "UNBLENDED_COST"})
            previsto = round(total + float(p["Total"]["Amount"]), 2)
        except (ErrorCostes, KeyError, ValueError):
            previsto = None                                       # la previsión necesita historial: sin ella se enseña solo lo gastado
    top = sorted(((n, round(v, 2)) for n, v in por_servicio.items() if v > 0), key=lambda x: -x[1])[:5]
    return {"mes": inicio.strftime("%Y-%m"), "gasto_usd": total, "previsto_usd": previsto, "servicios": top}


def gasto(hoy: date | None = None, forzar: bool = False) -> dict:
    """Lo mismo que `consultar`, guardado en memoria `TTL_SEGUNDOS` (cada petición a Cost Explorer cuesta dinero)."""
    with _cerrojo:
        hallado = _cache.get("datos")
        if hallado and not forzar and time.monotonic() - hallado[0] < TTL_SEGUNDOS and hallado[1]["mes"] == (hoy or date.today()).strftime("%Y-%m"):
            return hallado[1]
    datos = consultar(hoy)
    with _cerrojo:
        _cache["datos"] = (time.monotonic(), datos)
    return datos


def nivel(datos: dict, umbral: float | None = None) -> str:
    """'ok', 'aviso' (el gasto o la previsión pasan del 80 % del umbral) o 'excedido' (el gasto ya lo pasa o la previsión lo pasa)."""
    umbral = umbral if umbral is not None else umbral_usd()
    peor = max(datos["gasto_usd"], datos["previsto_usd"] or 0)
    if datos["gasto_usd"] >= umbral or (datos["previsto_usd"] or 0) >= umbral:
        return "excedido"
    return "aviso" if peor >= umbral * AMBAR_PCT / 100 else "ok"
