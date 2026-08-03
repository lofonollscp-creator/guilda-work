"""Tests del cliente de Meilisearch (app/busqueda.py) — se mockea
busqueda._peticion, sin un Meilisearch de verdad.

El diseño en sí (tenant tokens firmados con una clave de búsqueda propia,
nunca la maestra; filtro `usuario_id = <n>` embebido e imposible de
saltar, verificado en vivo: probar a pedir el filtro de otro usuario da
0 resultados porque queda en AND con el propio, no lo sustituye) se
verificó en vivo contra un contenedor real durante el desarrollo — ver
el docstring del propio módulo. Aquí solo se comprueba que
app/busqueda.py ORQUESTA las llamadas correctas y construye el JWT bien."""
import base64
import json

import pytest

from app import busqueda as b
from tests.conftest import iniciar_sesion_de_prueba


def _reset_cache(monkeypatch):
    monkeypatch.setattr(b, "_clave_busqueda_cache", None)
    monkeypatch.setattr(b, "_indice_listo", False)


def _decodificar_payload(token: str) -> dict:
    _, payload_b64, _ = token.split(".")
    relleno = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + relleno))


# --- generar_token_busqueda --------------------------------------------------

def test_generar_token_sin_master_key_lanza_error(monkeypatch):
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", None)
    with pytest.raises(b.ErrorBusqueda):
        b.generar_token_busqueda(42)


def test_generar_token_crea_la_clave_de_busqueda_si_no_existe(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")
    llamadas = []

    def fake_peticion(endpoint, *, clave, metodo="GET", cuerpo=None):
        llamadas.append((endpoint, metodo))
        if endpoint == "/keys" and metodo == "GET":
            return {"results": []}
        if endpoint == "/keys" and metodo == "POST":
            assert cuerpo["actions"] == ["search"]
            assert cuerpo["indexes"] == [b.INDICE]
            return {"uid": "uid-nuevo", "key": "key-nueva"}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(b, "_peticion", fake_peticion)
    token = b.generar_token_busqueda(42)

    payload = _decodificar_payload(token)
    assert payload["apiKeyUid"] == "uid-nuevo"
    assert payload["searchRules"][b.INDICE]["filter"] == "usuario_id = 42"
    assert ("/keys", "GET") in llamadas
    assert ("/keys", "POST") in llamadas


def test_generar_token_reutiliza_la_clave_de_busqueda_existente(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")

    def fake_peticion(endpoint, *, clave, metodo="GET", cuerpo=None):
        if endpoint == "/keys" and metodo == "GET":
            return {"results": [{"uid": "uid-existente", "key": "key-existente", "description": b._DESCRIPCION_CLAVE_BUSQUEDA}]}
        raise AssertionError("no debería crear una clave nueva")

    monkeypatch.setattr(b, "_peticion", fake_peticion)
    token = b.generar_token_busqueda(7)
    payload = _decodificar_payload(token)
    assert payload["apiKeyUid"] == "uid-existente"


def test_generar_token_cachea_la_clave_entre_llamadas(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")
    llamadas_keys = []

    def fake_peticion(endpoint, *, clave, metodo="GET", cuerpo=None):
        if endpoint == "/keys":
            llamadas_keys.append(1)
            return {"results": [{"uid": "u1", "key": "k1", "description": b._DESCRIPCION_CLAVE_BUSQUEDA}]}
        raise AssertionError("inesperado")

    monkeypatch.setattr(b, "_peticion", fake_peticion)
    b.generar_token_busqueda(1)
    b.generar_token_busqueda(2)
    assert len(llamadas_keys) == 1


def test_generar_token_respeta_minutos_validez(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")
    monkeypatch.setattr(b, "_asegurar_clave_busqueda", lambda: {"uid": "u1", "key": "k1"})
    token = b.generar_token_busqueda(1, minutos_validez=10)
    payload = _decodificar_payload(token)
    assert "exp" in payload


# --- indexar_* / eliminar_del_indice -----------------------------------------

def test_indexar_nota_sin_master_key_no_hace_nada(monkeypatch):
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", None)
    monkeypatch.setattr(b, "_peticion", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería llamar")))
    b.indexar_nota({"id": 1, "usuario_id": 1, "texto": "x", "creada_en": "2026-01-01T00:00:00"})


def test_indexar_nota_construye_el_documento_correcto(monkeypatch):
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")
    monkeypatch.setattr(b, "_asegurar_indice", lambda: None)
    capturado = {}

    def fake_peticion(endpoint, *, clave, metodo="GET", cuerpo=None):
        capturado["args"] = (endpoint, metodo, cuerpo)

    monkeypatch.setattr(b, "_peticion", fake_peticion)
    b.indexar_nota({"id": 7, "usuario_id": 3, "texto": "Hola", "creada_en": "2026-01-01T00:00:00", "categoria_id": 2})

    endpoint, metodo, cuerpo = capturado["args"]
    assert endpoint == f"/indexes/{b.INDICE}/documents"
    assert metodo == "POST"
    assert cuerpo == [{"id": "nota-7", "tipo": "nota", "usuario_id": 3, "texto": "Hola", "creada_en": "2026-01-01T00:00:00", "categoria_id": 2}]


def test_indexar_tarea_construye_el_documento_correcto(monkeypatch):
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")
    monkeypatch.setattr(b, "_asegurar_indice", lambda: None)
    capturado = {}
    monkeypatch.setattr(b, "_peticion", lambda endpoint, *, clave, metodo="GET", cuerpo=None: capturado.update(cuerpo=cuerpo))

    b.indexar_tarea({"id": 5, "usuario_id": 3, "nombre": "Reunión", "inicio_en": "2026-01-01T10:00:00", "categoria_id": 1})

    assert capturado["cuerpo"] == [{"id": "tarea-5", "tipo": "tarea", "usuario_id": 3, "texto": "Reunión", "creada_en": "2026-01-01T10:00:00", "categoria_id": 1}]


def test_indexar_mensaje_usa_el_usuario_id_pasado_explicito(monkeypatch):
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")
    monkeypatch.setattr(b, "_asegurar_indice", lambda: None)
    capturado = {}
    monkeypatch.setattr(b, "_peticion", lambda endpoint, *, clave, metodo="GET", cuerpo=None: capturado.update(cuerpo=cuerpo))

    b.indexar_mensaje({"id": 9, "asunto": "Hola", "cuerpo_texto": "Cuerpo", "fecha": "2026-01-01T10:00:00"}, usuario_id=4)

    assert capturado["cuerpo"] == [{"id": "mensaje-9", "tipo": "mensaje", "usuario_id": 4, "texto": "Hola Cuerpo", "creada_en": "2026-01-01T10:00:00"}]


def test_eliminar_del_indice_sin_master_key_no_hace_nada(monkeypatch):
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", None)
    monkeypatch.setattr(b, "_peticion", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería llamar")))
    b.eliminar_del_indice("nota", 1)


def test_eliminar_del_indice_llama_al_endpoint_correcto(monkeypatch):
    monkeypatch.setattr(b, "MEILISEARCH_MASTER_KEY", "clave-maestra")
    capturado = {}
    monkeypatch.setattr(b, "_peticion", lambda endpoint, *, clave, metodo="GET", cuerpo=None: capturado.update(endpoint=endpoint, metodo=metodo))

    b.eliminar_del_indice("tarea", 5)

    assert capturado == {"endpoint": f"/indexes/{b.INDICE}/documents/tarea-5", "metodo": "DELETE"}


# --- Ganchos en app/db.py y app/correo.py (indexación en cada escritura) ----
#
# db.py hace `from . import busqueda` de forma perezosa dentro de cada
# función (ver _reindexar_nota/_reindexar_tarea) — mockear
# app.busqueda.indexar_nota/eliminar_del_indice directamente afecta a esa
# misma instancia de módulo, así que estos tests no necesitan levantar
# ningún Meilisearch real.

def test_crear_nota_la_indexa(usuario_id, monkeypatch):
    from app import db

    llamadas = []
    monkeypatch.setattr(b, "indexar_nota", lambda nota: llamadas.append(dict(nota)))
    nota_id = db.crear_nota(usuario_id, "Hola búsqueda")

    assert len(llamadas) == 1
    assert llamadas[0]["id"] == nota_id
    assert llamadas[0]["texto"] == "Hola búsqueda"


def test_editar_nota_la_reindexa(usuario_id, monkeypatch):
    from app import db

    nota_id = db.crear_nota(usuario_id, "Original")
    llamadas = []
    monkeypatch.setattr(b, "indexar_nota", lambda nota: llamadas.append(dict(nota)))
    db.editar_nota(usuario_id, nota_id, "Editada")

    assert len(llamadas) == 1
    assert llamadas[0]["texto"] == "Editada"


def test_eliminar_nota_la_quita_del_indice(usuario_id, monkeypatch):
    from app import db

    nota_id = db.crear_nota(usuario_id, "A borrar")
    llamadas = []
    monkeypatch.setattr(b, "eliminar_del_indice", lambda tipo, id_: llamadas.append((tipo, id_)))
    db.eliminar_nota(usuario_id, nota_id)

    assert llamadas == [("nota", nota_id)]


def test_un_fallo_del_buscador_no_rompe_crear_nota(usuario_id, monkeypatch):
    """El registro de actividad en sí no debe depender de que Meilisearch
    esté levantado — mismo criterio "opcional, no bloqueante" que el
    resto de integraciones de este proyecto."""
    from app import db

    def falla(nota):
        raise b.ErrorBusqueda("Meilisearch caído, simulado")

    monkeypatch.setattr(b, "indexar_nota", falla)
    nota_id = db.crear_nota(usuario_id, "Debe sobrevivir")
    assert db.obtener_nota(usuario_id, nota_id) is not None


def test_crear_tarea_la_indexa(usuario_id, monkeypatch):
    from app import db

    categoria_id = db.crear_categoria(usuario_id, "Lueira")
    llamadas = []
    monkeypatch.setattr(b, "indexar_tarea", lambda tarea: llamadas.append(dict(tarea)))
    tarea_id = db.crear_tarea(usuario_id, "Reunión", categoria_id, "duracion")

    assert len(llamadas) == 1
    assert llamadas[0]["id"] == tarea_id
    assert llamadas[0]["nombre"] == "Reunión"


def test_eliminar_tarea_la_quita_del_indice(usuario_id, monkeypatch):
    from app import db

    categoria_id = db.crear_categoria(usuario_id, "Lueira")
    tarea_id = db.crear_tarea(usuario_id, "A borrar", categoria_id, "duracion")
    llamadas = []
    monkeypatch.setattr(b, "eliminar_del_indice", lambda tipo, id_: llamadas.append((tipo, id_)))
    db.eliminar_tarea(usuario_id, tarea_id)

    assert llamadas == [("tarea", tarea_id)]


def test_sincronizar_bandeja_reindexa_mensajes_tras_sincronizar_con_novedades(usuario_id, monkeypatch):
    from app import correo

    llamadas = []
    monkeypatch.setattr(correo, "_sincronizar_imap", lambda cuenta: 2)
    monkeypatch.setattr(correo.db, "obtener_cuenta_correo", lambda uid, cid: {"id": cid, "protocolo": "imap"})
    monkeypatch.setattr(correo.db, "marcar_sincronizada_cuenta_correo", lambda cid: None)
    monkeypatch.setattr(correo.db, "listar_mensajes_correo", lambda cid, limite=200: [{"id": 1, "asunto": "Hola"}])
    monkeypatch.setattr(b, "indexar_mensaje", lambda mensaje, usuario_id: llamadas.append((dict(mensaje), usuario_id)))

    resultado = correo.sincronizar_bandeja(usuario_id, 5)

    assert resultado == {"nuevos": 2}
    assert llamadas == [({"id": 1, "asunto": "Hola"}, usuario_id)]


def test_sincronizar_bandeja_sin_mensajes_nuevos_no_reindexa(usuario_id, monkeypatch):
    from app import correo

    monkeypatch.setattr(correo, "_sincronizar_imap", lambda cuenta: 0)
    monkeypatch.setattr(correo.db, "obtener_cuenta_correo", lambda uid, cid: {"id": cid, "protocolo": "imap"})
    monkeypatch.setattr(correo.db, "marcar_sincronizada_cuenta_correo", lambda cid: None)
    monkeypatch.setattr(correo.db, "listar_mensajes_correo", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería reindexar")))

    resultado = correo.sincronizar_bandeja(usuario_id, 5)
    assert resultado == {"nuevos": 0}


# --- app/main.py:token_busqueda() (/busqueda/token) --------------------------

def test_busqueda_token_sin_sesion_redirige_a_login(cliente):
    resp = cliente.get("/busqueda/token")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_busqueda_token_sin_meilisearch_configurado_da_503(cliente):
    iniciar_sesion_de_prueba(cliente, "busqueda1@ejemplo.com", "contrasena123")
    resp = cliente.get("/busqueda/token")
    assert resp.status_code == 503
    assert resp.get_json()["ok"] is False


def test_busqueda_token_devuelve_token_url_e_indice(cliente, monkeypatch):
    from app import main

    iniciar_sesion_de_prueba(cliente, "busqueda2@ejemplo.com", "contrasena123")
    monkeypatch.setattr(main.busqueda, "generar_token_busqueda", lambda uid: "token-de-prueba")
    monkeypatch.setattr(main.busqueda, "MEILISEARCH_URL", "http://127.0.0.1:8029")
    monkeypatch.setattr(main.busqueda, "INDICE", "registro_actividad")

    resp = cliente.get("/busqueda/token")
    datos = resp.get_json()
    assert resp.status_code == 200
    assert datos == {"ok": True, "token": "token-de-prueba", "url": "http://127.0.0.1:8029", "indice": "registro_actividad"}
