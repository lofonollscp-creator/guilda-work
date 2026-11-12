"""scripts/detectar_secretos.py (AA6): detecta secretos de verdad sin dar la lata con marcadores."""
import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("detectar_secretos", RAIZ / "scripts" / "detectar_secretos.py")
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)


def tipos(linea):
    return [(c, t) for c, t in ds.revisar_linea(linea)]


def test_secretos_de_verdad_son_de_confianza_alta():
    assert ("alta", "clave de acceso de AWS") in tipos("AWS_KEY = 'AKIAIOSFODNN7EXAMPLQ'")
    assert ("alta", "clave privada") in tipos("-----BEGIN RSA PRIVATE KEY-----")
    assert ("alta", "token de OpenRouter/OpenAI/Anthropic") in tipos("clave = sk-or-v1-" + "a1b2c3d4" * 6)
    assert ("alta", "clave de Stripe en producción") in tipos("STRIPE=sk_live_" + "A1b2C3d4E5f6G7h8")
    assert ("alta", "URL con usuario y contraseña") in tipos("DSN=postgres://app:Zx81kLmQ9pT@db.interno-real.net:5432/x")


def test_los_marcadores_y_lo_local_no_saltan():
    assert tipos("DSN=postgres://app:${DB_PASSWORD}@postgres:5432/x") == []
    assert tipos("DSN=postgres://app:secreto1234@localhost:5432/x") == []
    assert tipos("#   smtp://usuario:CONTRASENA@smtp.ionos.es:587/") == []
    assert tipos('password = "cambia-esto-por-algo-largo"') == []

    assert tipos("x = 1  # secreto-permitido AKIAIOSFODNN7EXAMPLQ") == []


def test_asignacion_de_contrasena_larga_es_solo_aviso():
    r = tipos('GUILDA_ADMIN_PASSWORD = "k3j2h4k5j6h7k8"')
    assert r == [("media", "asignación de contraseña o clave")]


def test_en_tests_la_clave_privada_de_mentira_no_cuenta_y_la_lista_blanca_funciona():
    assert ds.revisar_texto("tests/test_x.py", "b'-----BEGIN PRIVATE KEY-----'", set()) == []
    assert ds.revisar_texto("app/x.py", "-----BEGIN PRIVATE KEY-----", set())
    assert ds.revisar_texto("app/x.py", "-----BEGIN PRIVATE KEY-----", {"app/x.py"}) == []
    assert ds.revisar_texto("app/x.py", "\n-----BEGIN PRIVATE KEY-----", {"app/x.py:2"}) == []
