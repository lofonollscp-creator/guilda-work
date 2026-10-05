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


def test_mensajes_para_openrouter_usa_idioma_del_usuario(usuario_id):
    db.cambiar_idioma_usuario(usuario_id, "en")
    mensajes = a._mensajes_para_openrouter(usuario_id)
    assert "inglés" in mensajes[0]["content"]
    assert mensajes[0]["role"] == "system"


def test_mensajes_para_openrouter_cae_a_espanol_sin_idioma_elegido(usuario_id):
    mensajes = a._mensajes_para_openrouter(usuario_id)
    assert "español" in mensajes[0]["content"]


# --- Contexto del prompt y ventana de historial ----------------------------


def test_el_prompt_incluye_fecha_hora_y_dia_de_la_semana(usuario_id):
    from datetime import datetime

    prompt = a._prompt_sistema(usuario_id, "es", ahora=datetime(2026, 10, 5, 9, 30))

    assert "lunes" in prompt and "2026-10-05" in prompt and "09:30" in prompt
    assert "AAAA-MM-DD" in prompt


def test_el_prompt_incluye_nombre_y_despacho_pero_nunca_el_correo(usuario_id):
    db.guardar_perfil_usuario(usuario_id, nombre_mostrado="Ana Martínez")
    db.asignar_tenant(usuario_id, db.crear_tenant("Gestoría Soler"))

    prompt = a._prompt_sistema(usuario_id, "es")

    assert "Ana Martínez" in prompt
    assert "Gestoría Soler" in prompt
    assert db.obtener_usuario(usuario_id)["email"] not in prompt


def test_el_prompt_sin_nombre_ni_despacho_no_deja_huecos(usuario_id):
    prompt = a._prompt_sistema(usuario_id, "es")
    assert "  " not in prompt and "None" not in prompt


def _conversacion_larga(usuario_id, turnos):
    for n in range(turnos):
        db.agregar_mensaje_ia(usuario_id, "user", contenido=f"pregunta {n}")
        db.agregar_mensaje_ia(usuario_id, "assistant", contenido=f"respuesta {n}")


def test_la_ventana_envia_solo_los_ultimos_turnos_empezando_en_un_mensaje_de_usuario(usuario_id):
    _conversacion_larga(usuario_id, a.HISTORIAL_MAX_TURNOS + 3)

    mensajes = a._mensajes_para_openrouter(usuario_id)

    assert mensajes[0]["role"] == "system"
    assert mensajes[1] == {"role": "user", "content": "pregunta 3"}
    assert len(mensajes) == 1 + 2 * a.HISTORIAL_MAX_TURNOS
    assert mensajes[-1]["content"] == f"respuesta {a.HISTORIAL_MAX_TURNOS + 2}"
    # El historial completo sigue guardado: solo se limita lo que va al modelo.
    assert len(db.listar_mensajes_ia(usuario_id)) == 2 * (a.HISTORIAL_MAX_TURNOS + 3)


def test_una_conversacion_corta_se_envia_entera(usuario_id):
    _conversacion_larga(usuario_id, 3)
    assert len(a._mensajes_para_openrouter(usuario_id)) == 1 + 6


def test_la_ventana_nunca_deja_un_resultado_de_herramienta_huerfano(usuario_id):
    for n in range(a.HISTORIAL_MAX_TURNOS + 2):
        db.agregar_mensaje_ia(usuario_id, "user", contenido=f"pregunta {n}")
        llamada = [{"id": f"call_{n}", "type": "function", "function": {"name": "listar_notas", "arguments": "{}"}}]
        db.agregar_mensaje_ia(usuario_id, "assistant", tool_calls_json=json.dumps(llamada))
        db.agregar_mensaje_ia(usuario_id, "tool", contenido="[]", tool_call_id=f"call_{n}", nombre_herramienta="listar_notas")
        db.agregar_mensaje_ia(usuario_id, "assistant", contenido=f"respuesta {n}")

    mensajes = a._mensajes_para_openrouter(usuario_id)

    assert mensajes[1]["role"] == "user"
    llamadas = {tc["id"] for m in mensajes if m.get("tool_calls") for tc in m["tool_calls"]}
    respondidas = {m["tool_call_id"] for m in mensajes if m["role"] == "tool"}
    assert respondidas <= llamadas


def test_los_resultados_de_herramientas_antiguos_se_recortan_pero_los_del_turno_actual_no(usuario_id):
    enorme = "x" * 5000
    for n in range(2):
        db.agregar_mensaje_ia(usuario_id, "user", contenido=f"pregunta {n}")
        llamada = [{"id": f"call_{n}", "type": "function", "function": {"name": "listar_notas", "arguments": "{}"}}]
        db.agregar_mensaje_ia(usuario_id, "assistant", tool_calls_json=json.dumps(llamada))
        db.agregar_mensaje_ia(usuario_id, "tool", contenido=enorme, tool_call_id=f"call_{n}", nombre_herramienta="listar_notas")

    resultados = [m["content"] for m in a._mensajes_para_openrouter(usuario_id) if m["role"] == "tool"]

    assert len(resultados[0]) < len(enorme) and resultados[0].endswith("[resultado recortado]")
    assert resultados[1] == enorme  # el del turno actual, entero


def test_la_llamada_al_modelo_lleva_la_ventana_y_la_confirmacion_pendiente_sigue_funcionando(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=False)
    _conversacion_larga(usuario_id, a.HISTORIAL_MAX_TURNOS + 5)
    enviados = []

    def fake_post_json(url, payload, api_key):
        enviados.append(payload["messages"])
        return _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "x"}))

    monkeypatch.setattr(a, "_post_json", fake_post_json)

    resultado = a.procesar_turno(usuario_id, "crea una nota")

    assert len(enviados[0]) <= 1 + 2 * a.HISTORIAL_MAX_TURNOS + 1
    assert resultado["pendiente"]["herramienta"] == "crear_nota"
    assert a.pendiente_actual(usuario_id)["tool_call_id"] == "call_1"


# --- Variantes en streaming (asistente de voz) ------------------------------


def _chunks_texto(*fragmentos):
    """Simula los chunks 'delta' que streamea OpenRouter para una respuesta
    de texto plano, sin tool_calls."""
    return [{"choices": [{"delta": {"content": frag}}]} for frag in fragmentos]


def _chunks_tool_calls(*llamadas):
    """Simula los chunks 'delta' troceados por índice para tool_calls, como
    los manda OpenRouter en streaming de verdad: primero id+nombre, los
    argumentos llegan fragmentados en chunks posteriores."""
    chunks = []
    for idx, (tid, nombre, args) in enumerate(llamadas):
        chunks.append({"choices": [{"delta": {
            "tool_calls": [{"index": idx, "id": tid, "function": {"name": nombre, "arguments": ""}}]
        }}]})
        chunks.append({"choices": [{"delta": {
            "tool_calls": [{"index": idx, "function": {"arguments": json.dumps(args)}}]
        }}]})
    return chunks


def _encolar_stream(monkeypatch, *tandas):
    """Cada 'tanda' es la lista de chunks de UNA llamada a OpenRouter (puede
    haber varias tandas si el asistente encadena herramientas)."""
    cola = [list(t) for t in tandas]

    def fake_stream(url, payload, claves):
        return iter(cola.pop(0))

    monkeypatch.setattr(a, "_post_json_stream_con_fallback", fake_stream)


def test_procesar_turno_stream_respuesta_directa(monkeypatch, usuario_id):
    _preparar(usuario_id)
    _encolar_stream(monkeypatch, _chunks_texto("Hola, ", "¿en qué te ayudo?"))

    eventos = list(a.procesar_turno_stream(usuario_id, "hola"))

    deltas = [e["texto"] for e in eventos if e["tipo"] == "delta"]
    assert deltas == ["Hola, ", "¿en qué te ayudo?"]
    mensajes = [e["mensaje"] for e in eventos if e["tipo"] == "mensaje"]
    assert any(m["contenido"] == "Hola, ¿en qué te ayudo?" for m in mensajes)
    assert eventos[-1] == {"tipo": "fin"}
    assert db.listar_mensajes_ia(usuario_id)[-1]["rol"] == "assistant"


def test_procesar_turno_stream_tool_call_pausa_confirmacion(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=False)
    _encolar_stream(monkeypatch, _chunks_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})))

    eventos = list(a.procesar_turno_stream(usuario_id, "crea una nota"))

    pendientes = [e for e in eventos if e["tipo"] == "pendiente"]
    assert len(pendientes) == 1
    assert pendientes[0]["pendiente"] == {
        "tool_call_id": "call_1", "herramienta": "crear_nota", "argumentos": {"texto": "una nota"},
    }
    assert eventos[-1] == {"tipo": "fin"}
    # Nada se ha ejecutado todavía, igual que en la versión no-streaming.
    assert [n for n in db.historial(usuario_id) if n["origen"] == "nota"] == []


def test_procesar_turno_stream_herramienta_de_lectura_encadena_segunda_llamada(monkeypatch, usuario_id):
    _preparar(usuario_id)
    _encolar_stream(
        monkeypatch,
        _chunks_tool_calls(("call_1", "listar_notas", {})),
        _chunks_texto("No tienes notas todavía."),
    )

    eventos = list(a.procesar_turno_stream(usuario_id, "¿qué notas tengo?"))

    assert not any(e["tipo"] == "pendiente" for e in eventos)
    assert eventos[-1] == {"tipo": "fin"}
    mensajes = db.listar_mensajes_ia(usuario_id)
    assert any(m["rol"] == "tool" and m["nombre_herramienta"] == "listar_notas" for m in mensajes)
    assert mensajes[-1]["contenido"] == "No tienes notas todavía."


def test_procesar_turno_stream_sin_modelo_da_evento_error(usuario_id):
    a.guardar_api_keys(usuario_id, ["clave"])
    eventos = list(a.procesar_turno_stream(usuario_id, "hola"))
    assert len(eventos) == 1
    assert eventos[0]["tipo"] == "error"


def test_confirmar_pendiente_stream_aceptando_ejecuta_y_continua(monkeypatch, usuario_id):
    _preparar(usuario_id, modo_autonomo=False)
    _encolar_stream(monkeypatch, _chunks_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})))
    list(a.procesar_turno_stream(usuario_id, "crea una nota"))

    _encolar_stream(monkeypatch, _chunks_texto("Nota creada."))
    eventos = list(a.confirmar_pendiente_stream(usuario_id, True))

    assert not any(e["tipo"] == "pendiente" for e in eventos)
    assert eventos[-1] == {"tipo": "fin"}
    assert [n["texto"] for n in db.historial(usuario_id) if n["origen"] == "nota"] == ["una nota"]


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
