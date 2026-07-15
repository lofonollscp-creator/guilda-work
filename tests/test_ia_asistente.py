"""Tests de app/ia_asistente.py: el cliente OpenRouter y el bucle de
confirmación de herramientas. Sin llamadas de red reales: se sustituye
ia_asistente._post_json (el único punto que habla con OpenRouter), como ya
hacen los tests de app/ai_local.py con _chat."""
import json

import pytest

from app import db, ia_asistente as a


def _preparar(modo_autonomo=False, modelo="modelo-de-prueba"):
    db.guardar_preferencias_ia(modelo, modo_autonomo)
    a.guardar_api_key("clave-falsa-de-prueba")


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


def test_procesar_turno_sin_modelo_da_error():
    a.guardar_api_key("clave")
    with pytest.raises(a.ErrorIA):
        a.procesar_turno("hola")


def test_procesar_turno_sin_clave_da_error():
    db.guardar_preferencias_ia("modelo-de-prueba", False)
    with pytest.raises(a.ErrorIA):
        a.procesar_turno("hola")


def test_procesar_turno_con_texto_vacio_da_error():
    _preparar()
    with pytest.raises(a.ErrorIA):
        a.procesar_turno("   ")


def test_respuesta_directa_sin_herramientas(monkeypatch):
    _preparar()
    _encolar(monkeypatch, _respuesta_texto("Hola, ¿en qué te ayudo?"))

    resultado = a.procesar_turno("hola")

    assert resultado["pendiente"] is None
    contenidos = [m["contenido"] for m in resultado["mensajes_nuevos"]]
    assert "Hola, ¿en qué te ayudo?" in contenidos
    assert db.listar_mensajes_ia()[-1]["rol"] == "assistant"


def test_herramienta_de_lectura_se_ejecuta_sola(monkeypatch):
    _preparar()
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "listar_notas", {})),
        _respuesta_texto("No tienes notas todavía."),
    )

    resultado = a.procesar_turno("¿qué notas tengo?")

    assert resultado["pendiente"] is None
    mensajes = db.listar_mensajes_ia()
    assert any(m["rol"] == "tool" and m["nombre_herramienta"] == "listar_notas" for m in mensajes)
    assert mensajes[-1]["contenido"] == "No tienes notas todavía."


def test_herramienta_de_escritura_pausa_esperando_confirmacion(monkeypatch):
    _preparar(modo_autonomo=False)
    _encolar(monkeypatch, _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})))

    resultado = a.procesar_turno("crea una nota que diga 'una nota'")

    assert resultado["pendiente"] == {
        "tool_call_id": "call_1", "herramienta": "crear_nota", "argumentos": {"texto": "una nota"},
    }
    # Nada se ha ejecutado todavía: no hay notas creadas.
    assert [n for n in db.historial() if n["origen"] == "nota"] == []


def test_confirmar_pendiente_aceptando_ejecuta_y_continua(monkeypatch):
    _preparar(modo_autonomo=False)
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})),
        _respuesta_texto("Nota creada."),
    )
    a.procesar_turno("crea una nota")

    resultado = a.confirmar_pendiente(True)

    assert resultado["pendiente"] is None
    assert [n["texto"] for n in db.historial() if n["origen"] == "nota"] == ["una nota"]


def test_confirmar_pendiente_rechazando_no_ejecuta_pero_continua(monkeypatch):
    _preparar(modo_autonomo=False)
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "una nota"})),
        _respuesta_texto("Vale, no la creo."),
    )
    a.procesar_turno("crea una nota")

    resultado = a.confirmar_pendiente(False)

    assert resultado["pendiente"] is None
    assert [n for n in db.historial() if n["origen"] == "nota"] == []
    tool_msg = next(m for m in db.listar_mensajes_ia() if m["rol"] == "tool")
    assert json.loads(tool_msg["contenido"])["rechazado"] is True


def test_modo_autonomo_ejecuta_escritura_sin_confirmar(monkeypatch):
    _preparar(modo_autonomo=True)
    _encolar(
        monkeypatch,
        _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "nota autonoma"})),
        _respuesta_texto("Hecho."),
    )

    resultado = a.procesar_turno("crea una nota")

    assert resultado["pendiente"] is None
    assert [n["texto"] for n in db.historial() if n["origen"] == "nota"] == ["nota autonoma"]


def test_enviar_borrador_correo_siempre_pausa_aunque_modo_autonomo(monkeypatch):
    _preparar(modo_autonomo=True)
    _encolar(monkeypatch, _respuesta_tool_calls(("call_1", "enviar_borrador_correo", {"borrador_id": "x"})))

    resultado = a.procesar_turno("envía el borrador x")

    assert resultado["pendiente"]["herramienta"] == "enviar_borrador_correo"


def test_no_se_puede_mandar_mensaje_con_confirmacion_pendiente(monkeypatch):
    _preparar(modo_autonomo=False)
    _encolar(monkeypatch, _respuesta_tool_calls(("call_1", "crear_nota", {"texto": "x"})))
    a.procesar_turno("crea una nota")

    with pytest.raises(a.ErrorIA):
        a.procesar_turno("otro mensaje mientras tanto")
