"""Tests del cliente de Uptime Kuma (app/uptime_kuma.py) — solo lectura,
se mockea uptime_kuma._obtener_metrics con texto Prometheus de ejemplo,
sin un Uptime Kuma de verdad."""
from app import uptime_kuma

_METRICS_EJEMPLO = """
# HELP monitor_status Monitor status
# TYPE monitor_status gauge
monitor_status{monitor_name="Guilda Work",monitor_type="http",monitor_url="http://host.docker.internal:8000"} 1
monitor_status{monitor_name="Kratos",monitor_type="http",monitor_url="http://kratos:4433"} 0
# HELP monitor_response_time Monitor response time
# TYPE monitor_response_time gauge
monitor_response_time{monitor_name="Guilda Work",monitor_type="http"} 42.5
"""


def test_listar_monitores_sin_api_key_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(uptime_kuma, "UPTIME_KUMA_API_KEY", None)
    assert uptime_kuma.listar_monitores() == []


def test_listar_monitores_parsea_estado_y_tiempo_respuesta(monkeypatch):
    monkeypatch.setattr(uptime_kuma, "UPTIME_KUMA_API_KEY", "clave")
    monkeypatch.setattr(uptime_kuma, "_obtener_metrics", lambda: _METRICS_EJEMPLO)

    resultado = {m["nombre"]: m for m in uptime_kuma.listar_monitores()}

    assert resultado["Guilda Work"]["estado"] == "activo"
    assert resultado["Guilda Work"]["tiempo_respuesta_ms"] == 42.5
    assert resultado["Kratos"]["estado"] == "caido"
    assert "tiempo_respuesta_ms" not in resultado["Kratos"]
