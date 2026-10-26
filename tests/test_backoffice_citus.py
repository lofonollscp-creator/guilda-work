"""El backoffice contra un Citus REAL: ninguna de sus pantallas (GET) puede dar un error de servidor. Los tests normales del backoffice usan SQLite o PostgreSQL sin tablas de referencia, y no ven lo que Citus
rechaza (p. ej. subconsultas correlacionadas con una tabla de referencia en el FROM): la página «Despachos» estuvo rota en producción desde el paso a Citus sin que ningún test lo viera. Necesita GUILDA_TEST_PG_URL."""
import re

import pytest

from tests import pg_ayudas
from tests.test_citus import _sembrar, aplicacion_en_citus, citus, como_app  # noqa: F401  (fixtures y datos de siembra)

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
CLAVE = "clave-de-prueba-larga-123"


def _csrf(html: str) -> str:
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def bo_citus(tmp_path, monkeypatch, citus, aplicacion_en_citus):                                   # noqa: F811
    from backoffice import aprovisionamiento, auth
    from backoffice.main import create_app
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    monkeypatch.setattr(aprovisionamiento, "aprovisionar_usuario", lambda *a, **k: [])
    import psycopg
    from psycopg.conninfo import make_conninfo
    from app.bd import postgres as pg
    with psycopg.connect(citus, autocommit=True) as c:
        c.execute("ALTER ROLE guilda_backoffice PASSWORD 'prueba-backoffice'")                    # (la misma clave que usa tests/test_backoffice_pg.py: los roles son del servidor)
    pg.fijar_url(make_conninfo(citus, user="guilda_app", password="prueba-app"), make_conninfo(citus, user="guilda_plataforma", password="prueba-plataforma"),
                 make_conninfo(citus, user="guilda_backoffice", password="prueba-backoffice"))
    auth.crear_admin("jorge", CLAVE, "Jorge")
    _sembrar(citus)
    cliente = create_app(testing=True).test_client()
    token = _csrf(cliente.get("/login").get_data(as_text=True))
    assert cliente.post("/login", data={"usuario": "jorge", "contrasena": CLAVE, "_csrf": token}).status_code in (200, 302)
    return cliente


def test_ninguna_pantalla_del_backoffice_da_error_de_servidor_en_citus(bo_citus):
    from backoffice.main import create_app
    app = create_app(testing=True)
    valores = {"tenant_id": 1, "usuario_id": 10, "plan_id": 1, "extra_id": 1, "webhook_id": 1, "lead_id": 1, "solicitud_id": 1, "token_id": 1, "nota_id": 1, "cobro_id": 1, "cola_id": 1}
    rutas = []
    for regla in app.url_map.iter_rules():
        if "GET" not in regla.methods or regla.endpoint == "static" or regla.rule in ("/login", "/login/2fa", "/logout", "/healthz"):
            continue
        if "descargar" in regla.rule or "exportar" in regla.rule:
            continue
        try:
            rutas.append(regla.rule if not regla.arguments else re.sub(r"<(?:int:)?(\w+)>", lambda m: str(valores[m.group(1)]), regla.rule))
        except KeyError:
            continue
    assert len(rutas) > 15
    fallos = []
    for ruta in sorted(set(rutas)):
        try:
            r = bo_citus.get(ruta)
        except Exception as e:                                                                      # noqa: BLE001  (con testing=True las excepciones se propagan en vez de dar un 500)
            import traceback
            donde = [f"{f.filename.split('guilda')[-1]}:{f.lineno}" for f in traceback.extract_tb(e.__traceback__) if "/backoffice/" in f.filename or "/app/db" in f.filename][-2:]
            fallos.append((ruta, f"{type(e).__name__}: {str(e).splitlines()[0][:100]} · {' > '.join(donde)}"))
            continue
        if r.status_code >= 500:
            fallos.append((ruta, r.status_code))
    assert not fallos, "pantallas con error de servidor en Citus:\n" + "\n".join(f"  {r}: {e}" for r, e in fallos)
