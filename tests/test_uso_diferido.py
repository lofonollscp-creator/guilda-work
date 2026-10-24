"""Uso de la API/MCP fuera de la ruta caliente (app/uso_diferido.py), concurrencia de la API sobre PostgreSQL + Citus y ventana de seguridad del cursor de /sync.

Contexto (medido el 24-oct-2026, docs/anexos-app-movil/medida_concurrencia_uso.json): escribir en cada petición en tablas de referencia de Citus provocaba `DeadlockDetected` distribuido
(4 clientes a la vez: 7 % de 500; 12: 65 %). Estas pruebas fijan que ya no ocurre y que el contador sigue cuadrando."""
import os
import threading
import time

import pytest

from app import db, uso_diferido
from tests.test_rutas_api import _auth, _registrar

POSTGRES = os.environ.get("GUILDA_TEST_MOTOR", "sqlite") == "postgres"
solo_postgres = pytest.mark.skipif(not POSTGRES, reason="comprueba algo propio de PostgreSQL + Citus (tablas de referencia, cursor de cambios)")


def _persona(cliente, email="uso@ejemplo.com"):
    datos = _registrar(cliente, email=email)
    uid = datos["usuario"]["id"]
    token_id = db.listar_tokens_api(uid)[0]["id"]
    return _auth(datos["token"]), uid, token_id


def _llamadas(token_id: int) -> int:
    return sum(f["llamadas"] for f in db.uso_de_token(token_id))


# --- El acumulador ------------------------------------------------------------------------------------------------------------------------

def test_el_uso_se_acumula_en_memoria_y_se_vuelca_de_una_vez(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_USO_DIFERIDO", "1")
    h, _uid, token_id = _persona(cliente)
    uso_diferido.volcar()
    antes = _llamadas(token_id)
    for _ in range(5):
        assert cliente.get("/api/v1/notas", headers=h).status_code == 200
    assert uso_diferido.pendientes()["tokens"] >= 1                       # aún en memoria: ninguna escritura en la ruta de la petición
    conn = db.get_connection()
    try:
        en_base = conn.execute("SELECT COALESCE(SUM(llamadas), 0) FROM tokens_api_uso WHERE token_id = ?", (token_id,)).fetchone()[0]
    finally:
        conn.close()
    assert en_base == antes                                               # la base no ha visto esas 5 llamadas todavía
    assert _llamadas(token_id) == antes + 5                               # leer vuelca antes: el panel y /tokens/{id}/uso ven siempre lo último
    assert uso_diferido.pendientes()["tokens"] == 0


def test_con_el_diferido_apagado_se_escribe_en_el_momento(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_USO_DIFERIDO", "0")
    h, _uid, token_id = _persona(cliente, "uso2@ejemplo.com")
    antes = _llamadas(token_id)
    assert cliente.get("/api/v1/notas", headers=h).status_code == 200
    assert uso_diferido.pendientes()["tokens"] == 0
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COALESCE(SUM(llamadas), 0) FROM tokens_api_uso WHERE token_id = ?", (token_id,)).fetchone()[0] == antes + 1
    finally:
        conn.close()


def test_los_errores_se_cuentan_aparte(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_USO_DIFERIDO", "1")
    h, _uid, token_id = _persona(cliente, "uso3@ejemplo.com")
    uso_diferido.volcar()
    antes = sum(f["errores"] for f in db.uso_de_token(token_id))
    assert cliente.get("/api/v1/notas/999999", headers=h).status_code == 404
    assert sum(f["errores"] for f in db.uso_de_token(token_id)) == antes + 1


def test_ultimo_uso_del_token_se_anota_como_mucho_una_vez_por_minuto(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_USO_DIFERIDO", "1")
    h, _uid, token_id = _persona(cliente, "uso4@ejemplo.com")
    uso_diferido.volcar()
    ahora = db.now_iso()
    assert uso_diferido.tocar_token(token_id, ahora, "1.2.3.4", ahora) is False                 # visto hace 0 s: nada que anotar
    assert uso_diferido.pendientes()["ultimo_uso"] == 0
    antiguo = "2020-01-01T00:00:00"
    assert uso_diferido.tocar_token(token_id, antiguo, "1.2.3.4", ahora) is False               # antiguo: se anota en memoria, no se escribe en línea
    assert uso_diferido.pendientes()["ultimo_uso"] == 1
    assert uso_diferido.volcar() >= 1
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT ultimo_uso_en, ultima_ip FROM tokens_api WHERE id = ?", (token_id,)).fetchone()
    finally:
        conn.close()
    assert fila["ultimo_uso_en"] == ahora and fila["ultima_ip"] == "1.2.3.4"


def test_un_volcado_que_falla_conserva_lo_pendiente_y_no_lanza(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_USO_DIFERIDO", "1")
    h, _uid, token_id = _persona(cliente, "uso5@ejemplo.com")
    uso_diferido.volcar()
    antes = _llamadas(token_id)
    for _ in range(3):
        cliente.get("/api/v1/notas", headers=h)
    original = db.get_connection

    def roto():
        raise RuntimeError("la base no responde")

    monkeypatch.setattr(db, "get_connection", roto)
    assert uso_diferido.volcar() == 0                                     # no lanza
    monkeypatch.setattr(db, "get_connection", original)
    assert uso_diferido.pendientes()["tokens"] >= 1                       # conserva lo pendiente
    assert _llamadas(token_id) == antes + 3                               # y el siguiente volcado lo escribe


def test_lo_pendiente_de_otra_base_de_datos_no_se_escribe_en_esta(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_USO_DIFERIDO", "1")
    _h, _uid, token_id = _persona(cliente, "uso6@ejemplo.com")
    uso_diferido.volcar()
    antes = _llamadas(token_id)
    uso_diferido.sumar_uso_token(token_id, 200)
    propia = uso_diferido._identidad
    monkeypatch.setattr(uso_diferido, "_identidad", lambda: "otra-base")
    assert uso_diferido.volcar() == 0
    monkeypatch.setattr(uso_diferido, "_identidad", propia)
    assert _llamadas(token_id) == antes


def test_el_uso_del_mcp_tambien_va_diferido(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_USO_DIFERIDO", "1")
    _h, uid, _t = _persona(cliente, "uso7@ejemplo.com")
    db.mcp_registrar_llamada(uid, "test", None, "listar_tareas", True, "ok", None, None, 5)
    db.mcp_registrar_llamada(uid, "test", None, "listar_tareas", True, "error", "boom", None, 5)
    assert uso_diferido.pendientes()["mcp"] == 1
    resumen = db.mcp_resumen(7)
    assert resumen["llamadas"] >= 2 and resumen["errores"] >= 1


# --- Concurrencia de la API (la prueba que habría detectado el problema) --------------------------------------------------------------------

@pytest.mark.parametrize("hilos", [4, 8])
def test_la_api_aguanta_peticiones_simultaneas_sin_errores(cliente, hilos):
    """Cada hilo es un cliente con su propio token. Antes de sacar las escrituras de la ruta caliente, sobre PostgreSQL + Citus esto devolvía 500 (`distributed deadlock`)."""
    from app.main import app

    personas = [_persona(cliente, f"conc{i}@ejemplo.com") for i in range(hilos)]
    codigos: list[int] = []
    errores: list[str] = []
    cerrojo = threading.Lock()
    salida = threading.Barrier(hilos)

    def trabajar(cabeceras):
        c = app.test_client()
        salida.wait()
        for ruta in ("/api/v1/auth/me", "/api/v1/notas", "/api/v1/proyectos", "/api/v1/auth/me", "/api/v1/perfil") * 4:
            try:
                r = c.get(ruta, headers=cabeceras)
                with cerrojo:
                    codigos.append(r.status_code)
            except Exception as e:                                       # noqa: BLE001
                with cerrojo:
                    errores.append(repr(e))

    hs = [threading.Thread(target=trabajar, args=(p[0],)) for p in personas]
    [h.start() for h in hs]
    [h.join(60) for h in hs]
    assert not errores, errores[:3]
    assert len(codigos) == hilos * 20
    assert all(c == 200 for c in codigos), {c: codigos.count(c) for c in set(codigos)}


@pytest.mark.parametrize("hilos", [6])
def test_escrituras_simultaneas_con_idempotencia_no_dan_500(cliente, hilos):
    from app.main import app

    personas = [_persona(cliente, f"idem{i}@ejemplo.com") for i in range(hilos)]
    codigos: list[int] = []
    cerrojo = threading.Lock()
    salida = threading.Barrier(hilos)

    def trabajar(i, cabeceras):
        c = app.test_client()
        salida.wait()
        for k in range(4):
            r = c.post("/api/v1/notas", json={"texto": f"nota {i}-{k}"}, headers={**cabeceras, "Idempotency-Key": f"k-{i}-{k}"})
            with cerrojo:
                codigos.append(r.status_code)

    hs = [threading.Thread(target=trabajar, args=(i, p[0])) for i, p in enumerate(personas)]
    [h.start() for h in hs]
    [h.join(60) for h in hs]
    assert len(codigos) == hilos * 4 and all(c in (200, 201) for c in codigos), {c: codigos.count(c) for c in set(codigos)}


def test_una_clave_de_idempotencia_caducada_se_puede_reutilizar(cliente):
    h, uid, _t = _persona(cliente, "idem-cad@ejemplo.com")
    assert db.idempotencia_reservar(uid, "clave-vieja", "huella-1") == ("nuevo",)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE api_idempotencia SET creado_en = ? WHERE usuario_id = ? AND clave = ?", ("2020-01-01T00:00:00", uid, "clave-vieja"))
        conn.commit()
    finally:
        conn.close()
    assert db.idempotencia_reservar(uid, "clave-vieja", "huella-2") == ("nuevo",)         # ya no cuenta como la misma petición
    assert db.idempotencia_reservar(uid, "clave-vieja", "huella-2")[0] in ("en_curso", "repetida")


# --- Cursor de /sync: ventana de seguridad -------------------------------------------------------------------------------------------------

def _insertar_cambio(uid: int, cambio_id: int, entidad_id: int) -> None:
    """Un cambio con un id elegido: simula que una transacción que EMPEZÓ antes (id menor) confirma DESPUÉS de otra con un id mayor."""
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO api_cambios (id, entidad, entidad_id, accion, usuario_id) VALUES (?, 'notas', ?, 'upsert', ?)", (cambio_id, entidad_id, uid))
        conn.commit()
    finally:
        conn.close()


@solo_postgres
def test_sin_ventana_un_cambio_que_confirma_tarde_se_pierde_con_ventana_no(cliente, monkeypatch):
    h, uid, _t = _persona(cliente, "cursor@ejemplo.com")
    base = 9_000_000
    # --- el fallo original (ventana 0): B (id mayor) confirma primero, el cliente lee, A (id menor) confirma después y ya no se le entrega
    monkeypatch.setenv("GUILDA_SYNC_VENTANA_SEG", "0")
    c0 = db.cursor_cambios_actual()
    _insertar_cambio(uid, base + 2, 2002)                                  # B
    s1 = db.cambios_desde(uid, c0)
    assert [x[1] for x in s1["cambios"]] == [2002]
    _insertar_cambio(uid, base + 1, 2001)                                  # A, tarde
    s2 = db.cambios_desde(uid, s1["cursor"])
    assert s2["cambios"] == []                                              # PERDIDO: este es el defecto que se reprodujo

    # --- con la ventana: lo reciente no se entrega hasta que «madura»; A y B llegan los dos, en orden
    monkeypatch.setenv("GUILDA_SYNC_VENTANA_SEG", "2")
    c0 = db.cursor_cambios_actual()
    _insertar_cambio(uid, base + 12, 3002)                                 # B (id mayor) confirma primero
    s1 = db.cambios_desde(uid, c0)
    assert s1["cambios"] == [] and s1["cursor"] == c0                      # joven: no se entrega y el cursor no se adelanta
    _insertar_cambio(uid, base + 11, 3001)                                 # A confirma después, con id menor
    time.sleep(3.2)
    s2 = db.cambios_desde(uid, s1["cursor"])
    assert {3001, 3002} <= {x[1] for x in s2["cambios"]}                  # los dos, sin pérdida (pueden venir también los de la fase anterior, aún por entregar)
    assert s2["cursor"] >= base + 12


@solo_postgres
def test_el_cursor_inicial_no_se_adelanta_a_un_cambio_joven(cliente, monkeypatch):
    h, uid, _t = _persona(cliente, "cursor2@ejemplo.com")
    monkeypatch.setenv("GUILDA_SYNC_VENTANA_SEG", "30")
    inicial = db.cursor_cambios_actual()
    _insertar_cambio(uid, 9_100_000, 1)
    assert db.cursor_cambios_actual() == inicial                           # el cambio recién creado aún está en la ventana


def test_con_sqlite_la_ventana_no_se_aplica(cliente, monkeypatch):
    if POSTGRES:
        pytest.skip("solo para SQLite")
    h, uid, _t = _persona(cliente, "cursor3@ejemplo.com")
    monkeypatch.setenv("GUILDA_SYNC_VENTANA_SEG", "30")                    # aunque se pida, SQLite tiene un único escritor y no necesita esperar
    c0 = db.cursor_cambios_actual()
    nota = cliente.post("/api/v1/notas", json={"texto": "hola"}, headers=h)
    assert nota.status_code == 201
    s = db.cambios_desde(uid, c0)
    assert any(x[0] == "notas" for x in s["cambios"])


# --- Contexto de acceso en una sola consulta -----------------------------------------------------------------------------------------------

def test_el_contexto_de_acceso_equivale_a_las_cuatro_lecturas_de_antes(cliente):
    _h, uid, _t = _persona(cliente, "ctx1@ejemplo.com")
    otro = _persona(cliente, "ctx2@ejemplo.com")[1]
    t = db.crear_tenant("Despacho contexto")
    db.asignar_tenant(otro, t)
    db.asignar_gestor_fichajes(otro, True)
    db.asignar_supervisor_tenant(otro, True)
    db.hacer_admin("ctx1@ejemplo.com")
    for u in (uid, otro, 999_999):
        antes_tenant = db.tenant_de_usuario(u)
        c = db.contexto_de_acceso(u)
        if u == 999_999:
            assert c is None
            continue
        assert c["tenant_id"] == (antes_tenant["id"] if antes_tenant else None)
        assert c["es_admin"] == db.es_admin(u) and c["gestor_fichajes"] == db.es_gestor_fichajes(u) and c["supervisor_tenant"] == db.es_supervisor_tenant(u)
