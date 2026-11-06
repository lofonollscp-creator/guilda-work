"""Gasto de AWS en el panel de salud (K9): firma SigV4, lectura de Cost Explorer, caché y semáforo."""
import json
import re
from datetime import date, datetime

import pytest

from app import aws_costes as ac, salud

AHORA = datetime(2026, 11, 15, 12, 0)


class Respuesta:
    def __init__(self, cuerpo, estado=200):
        self._c, self.status_code, self.text = cuerpo, estado, json.dumps(cuerpo)

    def json(self):
        return self._c


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    ac._cache.clear()
    monkeypatch.setenv("GUILDA_AWS_COSTES_ACCESS_KEY", "AKIAEJEMPLO")
    monkeypatch.setenv("GUILDA_AWS_COSTES_SECRET_KEY", "secreto-de-prueba")
    monkeypatch.delenv("GUILDA_AWS_COSTES_UMBRAL_USD", raising=False)
    yield
    ac._cache.clear()


def _aws(monkeypatch, gastos, prevision=None, llamadas=None):
    def post(url, data=None, headers=None, timeout=None):
        if llamadas is not None:
            llamadas.append((headers["x-amz-target"], json.loads(data), headers))
        if headers["x-amz-target"].endswith("GetCostAndUsage"):
            return Respuesta({"ResultsByTime": [{"Groups": [{"Keys": [n], "Metrics": {"UnblendedCost": {"Amount": str(v)}}} for n, v in gastos.items()]}]})
        return Respuesta({"Total": {"Amount": str(prevision)}}) if prevision is not None else Respuesta({"message": "sin historial"}, 400)
    monkeypatch.setattr(ac.requests, "post", post)


def test_la_firma_es_sigv4_determinista_y_depende_del_cuerpo():
    cab = {"host": ac.HOST, "content-type": "application/x-amz-json-1.1", "x-amz-target": "AWSInsightsIndexService.GetCostAndUsage"}
    a = ac.firmar("POST", "/", b"{}", cab, "AKIAEJEMPLO", "secreto", AHORA)
    b = ac.firmar("POST", "/", b"{}", cab, "AKIAEJEMPLO", "secreto", AHORA)
    c = ac.firmar("POST", "/", b'{"x":1}', cab, "AKIAEJEMPLO", "secreto", AHORA)
    assert a == b and a["authorization"] != c["authorization"]
    assert re.fullmatch(r"AWS4-HMAC-SHA256 Credential=AKIAEJEMPLO/20261115/us-east-1/ce/aws4_request, SignedHeaders=content-type;host;x-amz-date;x-amz-target, Signature=[0-9a-f]{64}", a["authorization"])
    assert a["x-amz-date"] == "20261115T120000Z" and "secreto" not in json.dumps(a)
    d = ac.firmar("POST", "/", b"{}", cab, "AKIAEJEMPLO", "secreto", AHORA, sesion="TOKEN")
    assert d["x-amz-security-token"] == "TOKEN" and "x-amz-security-token" in d["authorization"]


def test_consulta_el_gasto_por_servicio_y_la_prevision(monkeypatch):
    llamadas = []
    _aws(monkeypatch, {"Amazon S3": 3.40, "AWS Lambda": 0.0, "Amazon CloudWatch": 1.10}, prevision=5.0, llamadas=llamadas)
    d = ac.consultar(date(2026, 11, 15))
    assert d == {"mes": "2026-11", "gasto_usd": 4.5, "previsto_usd": 9.5, "servicios": [("Amazon S3", 3.4), ("Amazon CloudWatch", 1.1)]}
    assert [l[0].split(".")[-1] for l in llamadas] == ["GetCostAndUsage", "GetCostForecast"]
    assert llamadas[0][1]["TimePeriod"] == {"Start": "2026-11-01", "End": "2026-11-16"} and llamadas[1][1]["TimePeriod"] == {"Start": "2026-11-16", "End": "2026-12-01"}


def test_sin_prevision_se_enseña_solo_lo_gastado_y_el_ultimo_dia_no_la_pide(monkeypatch):
    llamadas = []
    _aws(monkeypatch, {"Amazon S3": 1.0}, prevision=None, llamadas=llamadas)
    assert ac.consultar(date(2026, 11, 15))["previsto_usd"] is None
    llamadas.clear()
    assert ac.consultar(date(2026, 11, 30))["previsto_usd"] is None and [l[0].split(".")[-1] for l in llamadas] == ["GetCostAndUsage"]


def test_un_error_de_aws_se_convierte_en_error_legible(monkeypatch):
    monkeypatch.setattr(ac.requests, "post", lambda *a, **k: Respuesta({"message": "User is not authorized"}, 400))
    with pytest.raises(ac.ErrorCostes, match="400.*not authorized"):
        ac.consultar(date(2026, 11, 15))
    monkeypatch.delenv("GUILDA_AWS_COSTES_ACCESS_KEY")
    with pytest.raises(ac.ErrorCostes, match="Faltan"):
        ac.consultar()


def test_el_resultado_se_guarda_en_memoria(monkeypatch):
    llamadas = []
    _aws(monkeypatch, {"Amazon S3": 1.0}, prevision=1.0, llamadas=llamadas)
    ac.gasto(date(2026, 11, 15)); ac.gasto(date(2026, 11, 15))
    assert len(llamadas) == 2, "dos peticiones la primera vez (gasto y previsión) y ninguna la segunda"
    ac.gasto(date(2026, 11, 15), forzar=True)
    assert len(llamadas) == 4


@pytest.mark.parametrize("gasto, previsto, esperado", [(1.0, 2.0, "ok"), (41.0, None, "aviso"), (10.0, 45.0, "aviso"), (50.0, None, "excedido"), (10.0, 60.0, "excedido")])
def test_el_semaforo_usa_el_gasto_y_la_prevision(gasto, previsto, esperado):
    assert ac.nivel({"gasto_usd": gasto, "previsto_usd": previsto}, 50.0) == esperado


def test_el_umbral_sale_del_entorno(monkeypatch):
    assert ac.umbral_usd() == 50.0
    monkeypatch.setenv("GUILDA_AWS_COSTES_UMBRAL_USD", "120")
    assert ac.umbral_usd() == 120.0
    monkeypatch.setenv("GUILDA_AWS_COSTES_UMBRAL_USD", "mucho")
    assert ac.umbral_usd() == 50.0


def _item():
    return {i["clave"]: i for i in salud.panel(AHORA)}["aws_gasto"]


def test_el_panel_de_salud_muestra_gris_sin_claves_y_semaforo_con_ellas(monkeypatch):
    monkeypatch.delenv("GUILDA_AWS_COSTES_ACCESS_KEY")
    assert _item()["estado"] == salud.GRIS
    monkeypatch.setenv("GUILDA_AWS_COSTES_ACCESS_KEY", "AKIAEJEMPLO")
    _aws(monkeypatch, {"Amazon S3": 3.0}, prevision=4.0)
    i = _item()
    assert i["estado"] == salud.VERDE and "3.00 USD gastados" in i["detalle"] and "previsión a fin de mes: 7.00" in i["detalle"] and "Amazon S3 3.00" in i["detalle"]
    ac._cache.clear()
    monkeypatch.setenv("GUILDA_AWS_COSTES_UMBRAL_USD", "5")
    assert _item()["estado"] == salud.ROJO


def test_si_aws_no_responde_el_panel_no_se_rompe(monkeypatch):
    monkeypatch.setattr(ac.requests, "post", lambda *a, **k: (_ for _ in ()).throw(ac.requests.ConnectionError("sin red")))
    i = _item()
    assert i["estado"] == salud.AMBAR and "No se ha podido consultar" in i["detalle"]
