"""Tests de app/ia_asistente.py: el cliente OpenRouter y el bucle de
confirmación de herramientas. Sin llamadas de red reales: se sustituye
ia_asistente._post_json (el único punto que habla con OpenRouter), como ya
hacen los tests de app/ai_local.py con _chat."""
import json

import pytest

from app import db, ia_asistente as a


def _preparar(usuario_id, modo_autonomo=False, modelo="modelo-de-prueba"):
    db.guardar_preferencias_ia(usuario_id, modelo, modo_autonomo)
    a.guardar_api_keys(usuario_id, ["clave-falsa-de-prueba"])


def _respuesta_texto(texto):
    return {"choices": [{"message": {"role": "assistant", "content": texto}}]}


def _respuesta_tool_calls(*llamadas):
    return {
        "choices": [{
            "message": {
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": tid, "type": "function", "function": {"name": nombre, "arguments": json.dumps(args)}}
                    for tid, nombre, args in llamadas
                ],
            }
        }]
    }


def _encolar(monkeypatch, *respuestas):
    cola = list(respuestas)

    def fake_post_json(url, payload, api_key):
        return cola.pop(0)

    monkeypatch.setattr(a, "_post_json", fake_post_json)


def test_procesar_turno_sin_modelo_da_error(usuario_id):
    a.guardar_api_keys(usuario_id, ["clave"])
    with pytest.raises(a.ErrorIA):
        a.procesar_turno(usuario_id, "hola")


def test_procesar_turno_sin_clave_da_error(usuario_id):
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", False)
    with pytest.raises(a.ErrorIA):
        a.procesar_turno(usuario_id, "hola")


def test_procesar_turno_con_texto_vacio_da_error(usuario_id):
    _preparar(usuario_id)
    with pytest.raises(a.ErrorIA):
        a.procesar_turno(usuario_id, "   ")


def test_respuesta_directa_sin_herramientas(monkeypatch, usuario_id):
    _preparar(usuario_id)
    _encolar(monkeypatch, _respuesta_texto("Hola, ¿en qué te ayudo?"))

    resultado = a.procesar_turno(usuario_id, "hola")

    assert resultado["pendiente"] is None
    contenidos = [m["contenido"] for m in resultado["mensajes_nuevos"]]
    assert "Hola, ¿en qué te ayudo?" in contenidos
    assert db.listar_mensajes_ia(usuario_id)[-1]["rol"] == "assistant"


def test_herramienta_de_lectura_se_ejecuta_sola(monkeypatch, usuario_id):
    _preparar(usuario_id)
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "listar_notas", {})),
        _respuesta_texto("No tienes notas todavía."),
    )

    resultado = a.procesar_turno(usuario_id, "¿qué notas tengo?")

    assert resultado["pendiente"] is None
    mensajes = db.listar_mensajes_ia(usuario_id)
    assert any(m["rol"] == "tool" and m["nombre_herramienta"] == "listar_notas" for m in mensajes)
    assert mensajes[-1]["contenido"] == "No tienes notas todavía."


def test_herramienta_de_escritura_pausa_esperando_confirmacion(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=False)
    _encolar(monkeypatch, _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})))

    resultado = a.procesar_turno(usuario_id, "crea una nota que diga 'una nota'")

    assert resultado["pendiente"] == {
        "tool_call_id": "call_1", "herramienta": "crear_nota", "argumentos": {"texto": "una nota"},
    }
    # Nada se ha ejecutado todavía: no hay notas creadas.
    assert [n for n in db.historial(usuario_id) if n["origen"] == "nota"] == []


def test_confirmar_pendiente_aceptando_ejecuta_y_continua(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=False)
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})),
        _respuesta_texto("Nota creada."),
    )
    a.procesar_turno(usuario_id, "crea una nota")

    resultado = a.confirmar_pendiente(usuario_id, True)

    assert resultado["pendiente"] is None
    assert [n["texto"] for n in db.historial(usuario_id) if n["origen"] == "nota"] == ["una nota"]


def test_confirmar_pendiente_rechazando_no_ejecuta_pero_continua(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=False)
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})),
        _respuesta_texto("Vale, no la creo."),
    )
    a.procesar_turno(usuario_id, "crea una nota")

    resultado = a.confirmar_pendiente(usuario_id, False)

    assert resultado["pendiente"] is None
    assert [n for n in db.historial(usuario_id) if n["origen"] == "nota"] == []
    tool_msg = next(m for m in db.listar_mensajes_ia(usuario_id) if m["rol"] == "tool")
    assert json.loads(tool_msg["contenido"])["rechazado"] is True


def test_modo_autonomo_ejecuta_escritura_sin_confirmar(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=True)
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "nota autonoma"})),
        _respuesta_texto("Hecho."),
    )

    resultado = a.procesar_turno(usuario_id, "crea una nota")

    assert resultado["pendiente"] is None
    assert [n["texto"] for n in db.historial(usuario_id) if n["origen"] == "nota"] == ["nota autonoma"]


def test_enviar_borrador_correo_siempre_pausa_aunque_modo_autonomo(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=True)
    _encolar(monkeypatch, _respuesta_tool_calls(("call_1", "enviar_borrador_correo", {"borrador_id": "x"})))

    resultado = a.procesar_turno(usuario_id, "envía el borrador x")

    assert resultado["pendiente"]["herramienta"] == "enviar_borrador_correo"


def test_no_se_puede_mandar_mensaje_con_confirmacion_pendiente(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=False)
    _encolar(monkeypatch, _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "x"})))
    a.procesar_turno(usuario_id, "crea una nota")

    with pytest.raises(a.ErrorIA):
        a.procesar_turno(usuario_id, "otro mensaje mientras tanto")


# --- listar_modelos_gratuitos ------------------------------------------------

class _RespuestaFalsa:
    """Imita el objeto que devuelve urllib.request.urlopen (usado como
    context manager, con .read())."""

    def __init__(self, cuerpo: dict):
        self._cuerpo = json.dumps(cuerpo).encode("utf-8")

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_cache_modelos():
    """La caché de listar_modelos_gratuitos vive en variables de módulo —
    se resetea antes y después de cada test para que no se contaminen entre
    sí (incluidos los tests de otras clases de este mismo archivo)."""
    a._cache_modelos_gratuitos = None
    a._cache_modelos_expira_en = 0.0
    yield
    a._cache_modelos_gratuitos = None
    a._cache_modelos_expira_en = 0.0


def test_listar_modelos_gratuitos_filtra_solo_precio_cero(monkeypatch):
    cuerpo = {
        "data": [
            {"id": "meta-llama/llama-3.1-70b-instruct:free", "name": "Llama 3.1 70B (free)",
             "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini",
             "pricing": {"prompt": "0.00015", "completion": "0.0006"}},
        ]
    }
    monkeypatch.setattr(a.urllib.request, "urlopen", lambda req, timeout: _RespuestaFalsa(cuerpo))

    modelos = a.listar_modelos_gratuitos()

    assert len(modelos) == 1
    assert modelos[0]["id"] == "meta-llama/llama-3.1-70b-instruct:free"


def test_listar_modelos_gratuitos_cachea_entre_llamadas(monkeypatch):
    llamadas = {"n": 0}

    def urlopen_falso(req, timeout):
        llamadas["n"] += 1
        return _RespuestaFalsa({"data": [{"id": "a:free", "name": "A", "pricing": {"prompt": "0", "completion": "0"}}]})

    monkeypatch.setattr(a.urllib.request, "urlopen", urlopen_falso)

    a.listar_modelos_gratuitos()
    a.listar_modelos_gratuitos()

    assert llamadas["n"] == 1


def test_listar_modelos_gratuitos_si_falla_devuelve_respaldo_sin_lanzar(monkeypatch):
    def urlopen_falso(req, timeout):
        raise a.urllib.error.URLError("sin red")

    monkeypatch.setattr(a.urllib.request, "urlopen", urlopen_falso)

    modelos = a.listar_modelos_gratuitos()

    assert modelos == a.MODELOS_GRATUITOS_RESPALDO
