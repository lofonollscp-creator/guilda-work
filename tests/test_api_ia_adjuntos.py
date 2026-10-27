"""Asistente en la app móvil (API 1.11): subir un archivo de texto para que lo lea y las fuentes que cita en sus mensajes."""
import io
import json

from app import db
from tests.test_rutas_api import _auth, _registrar


def _h(cliente, email="ia-adj@ejemplo.com"):
    r = _registrar(cliente, email=email)
    return _auth(r["token"]), r["usuario"]["id"]


def test_subir_un_adjunto_de_texto(cliente):
    h, uid = _h(cliente)
    r = cliente.post("/api/v1/ia/adjuntos", data={"adjunto": (io.BytesIO("a;b\n1;2\n".encode()), "datos.csv")}, headers=h, content_type="multipart/form-data")
    assert r.status_code == 201
    datos = r.get_json()["data"]
    assert datos["nombre_archivo"] == "datos.csv"
    assert db.obtener_adjunto_ia(uid, datos["id"])["contenido"] == b"a;b\n1;2\n"


def test_adjunto_sin_archivo_demasiado_grande_o_binario(cliente):
    h, _ = _h(cliente, "ia-adj2@ejemplo.com")
    assert cliente.post("/api/v1/ia/adjuntos", data={}, headers=h, content_type="multipart/form-data").status_code == 400
    grande = cliente.post("/api/v1/ia/adjuntos", data={"adjunto": (io.BytesIO(b"x" * (1024 * 1024 + 1)), "grande.txt")}, headers=h, content_type="multipart/form-data")
    assert grande.status_code == 413 and grande.get_json()["campo"] == "adjunto"
    binario = cliente.post("/api/v1/ia/adjuntos", data={"adjunto": (io.BytesIO(b"\xff\xfe\x00\x80"), "foto.png")}, headers=h, content_type="multipart/form-data")
    assert binario.status_code == 400


def test_el_adjunto_lo_ve_solo_quien_lo_subio(cliente):
    h1, _ = _h(cliente, "ia-adj3@ejemplo.com")
    h2, u2 = _h(cliente, "ia-adj4@ejemplo.com")
    i = cliente.post("/api/v1/ia/adjuntos", data={"adjunto": (io.BytesIO(b"hola"), "n.txt")}, headers=h1, content_type="multipart/form-data").get_json()["data"]["id"]
    assert db.obtener_adjunto_ia(u2, i) is None


def test_los_mensajes_del_asistente_traen_sus_fuentes(cliente):
    h, uid = _h(cliente, "ia-adj5@ejemplo.com")
    fuentes = [{"tipo": "tarea", "titulo": "Llamar a Acme", "url": "/tareas/7/editar"}]
    db.agregar_mensaje_ia(uid, "user", "¿qué tengo?")
    db.agregar_mensaje_ia(uid, "assistant", "Esto.", fuentes_json=json.dumps(fuentes))
    filas = cliente.get("/api/v1/ia/mensajes", headers=h).get_json()["data"]
    assert json.loads(filas[-1]["fuentes_json"]) == fuentes
