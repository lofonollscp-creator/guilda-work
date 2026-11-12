"""scripts/auditar_exposicion.py (AA4/AA5): la lógica pura —cabeceras, puertos, ufw, CrowdSec— y su reflejo en el panel Salud."""
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

from app import db, salud

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("auditar_exposicion", RAIZ / "scripts" / "auditar_exposicion.py")
ae = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ae)
AHORA = datetime(2026, 11, 12, 12, 0)


def test_hosts_del_caddyfile():
    txt = "(seguridad) {\n\theader x\n}\nguildawork.com {\n}\nwww.guildawork.com {\n}\napp.guildawork.com {\n\timport seguridad\n}\n"
    assert ae.hosts_del_caddyfile(txt) == ["app.guildawork.com", "guildawork.com", "www.guildawork.com"]


def test_cabeceras():
    bien = {"strict-transport-security": "max-age=1", "x-content-type-options": "nosniff"}
    assert ae.evaluar_cabeceras(bien) == []
    assert ae.evaluar_cabeceras({}) == ["sin HSTS", "sin nosniff"]
    assert ae.evaluar_cabeceras({**bien, "server": "Apache/2.4.68"}) == ["publica server: Apache/2.4.68"]


SS = """tcp LISTEN 0 4096 0.0.0.0:443 0.0.0.0:* users:(("caddy",pid=1,fd=3))
tcp LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:* users:(("python",pid=2,fd=3))
tcp LISTEN 0 2048 0.0.0.0:8017 0.0.0.0:* users:(("python",pid=3,fd=9))
tcp LISTEN 0 4096 *:7881 *:* users:(("livekit-server",pid=4,fd=4))
tcp LISTEN 0 4096 [::]:22 [::]:* users:(("sshd",pid=5,fd=3))
udp UNCONN 0 0 0.0.0.0:1194 0.0.0.0:* users:(("docker-proxy",pid=6,fd=7))
"""
UFW = "Status: active\n\nTo Action From\n-- ------ ----\n22 ALLOW Anywhere\n443 ALLOW Anywhere\n7881/tcp ALLOW Anywhere\n50000:50100/udp ALLOW Anywhere\n"


def test_puertos_publicos_ignoran_lo_que_solo_escucha_en_local():
    assert set(ae.puertos_publicos(SS)) == {443, 8017, 7881, 22, 1194}


def test_ufw_y_alcanzables_frente_a_filtrados():
    activo, permitidos = ae.puertos_permitidos_ufw(UFW)
    assert activo and {22, 443, 7881, 50000, 50100, 50050} <= permitidos and 8017 not in permitidos
    alc, filt = ae.puertos_inesperados(ae.puertos_publicos(SS), {22, 443, 1194, 7881}, activo, permitidos)
    assert alc == [] and filt == ["8017 (python)"]
    alc, filt = ae.puertos_inesperados(ae.puertos_publicos(SS), {22, 443, 1194, 7881}, False, set())        # sin cortafuegos todo escucha = alcanzable
    assert alc == ["8017 (python)"] and filt == []
    assert ae.puertos_permitidos_ufw("Status: inactive") == (False, set())


def test_crowdsec_detecta_la_ip_propia():
    d = [{"value": "1.2.3.4", "scenario": "crowdsecurity/ssh-bf", "type": "ban"}, {"value": "9.9.9.9", "scenario": "x/http-crawl", "type": "ban"}, {"value": "9.9.9.9", "scenario": "x/http-crawl", "type": "captcha"}]
    r = ae.evaluar_crowdsec(d, {"1.2.3.4"})
    assert r["activas"] == 2 and r["propias_baneadas"] == ["1.2.3.4"]


def _escribir(tmp_path, monkeypatch, **cambios):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    e = {"fecha": (AHORA - timedelta(minutes=30)).isoformat(), "hosts": [{"host": "a"}], "puertos_inesperados": [], "puertos_filtrados": [], "fallos": [],
         "crowdsec": {"activas": 6, "propias_baneadas": [], "por_escenario": {"crowdsecurity/ssh-bf": 2}}}
    e.update(cambios)
    (tmp_path / "exposicion_estado.json").write_text(json.dumps(e), encoding="utf-8")


def test_panel_exposicion(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    assert salud._estado_exposicion(AHORA)["estado"] == salud.GRIS and salud._estado_crowdsec(AHORA)["estado"] == salud.GRIS
    _escribir(tmp_path, monkeypatch, puertos_filtrados=["8017 (python)"])
    r = salud._estado_exposicion(AHORA)
    assert r["estado"] == salud.VERDE and "8017" in r["detalle"]
    _escribir(tmp_path, monkeypatch, fallos=["app.x: sin HSTS"])
    assert salud._estado_exposicion(AHORA)["estado"] == salud.AMBAR
    _escribir(tmp_path, monkeypatch, fecha=(AHORA - timedelta(hours=9)).isoformat())
    assert salud._estado_exposicion(AHORA)["estado"] == salud.AMBAR


def test_panel_crowdsec(tmp_path, monkeypatch):
    _escribir(tmp_path, monkeypatch)
    assert salud._estado_crowdsec(AHORA)["estado"] == salud.VERDE
    _escribir(tmp_path, monkeypatch, crowdsec={"activas": 3, "propias_baneadas": ["62.1.1.1"], "por_escenario": {}})
    r = salud._estado_crowdsec(AHORA)
    assert r["estado"] == salud.ROJO and "62.1.1.1" in r["detalle"]
    _escribir(tmp_path, monkeypatch, crowdsec={"error": "cscli falló"})
    assert salud._estado_crowdsec(AHORA)["estado"] == salud.AMBAR
