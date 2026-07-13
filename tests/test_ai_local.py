"""Tests de app/ai_local.py.

No hacen ninguna llamada de red real: se sustituye `ai_local._chat` (el
único punto que habla con Ollama/LM Studio) para comprobar que los mensajes
se construyen bien, sin depender de tener un servicio local corriendo.
"""
import pytest

from app import ai_local

DATOS_EJEMPLO = {"registros": [{"texto_o_nombre": "Llamada a cliente"}]}


def test_generar_informe_envia_instruccion_y_datos(monkeypatch):
    capturado = {}

    def _chat_falso(proveedor, modelo, mensajes):
        capturado["proveedor"] = proveedor
        capturado["modelo"] = modelo
        capturado["mensajes"] = mensajes
        return "informe generado"

    monkeypatch.setattr(ai_local, "_chat", _chat_falso)

    resultado = ai_local.generar_informe(DATOS_EJEMPLO, "Resume esto", "ollama", "llama3.1")

    assert resultado == "informe generado"
    assert capturado["proveedor"] == "ollama"
    assert capturado["modelo"] == "llama3.1"
    assert len(capturado["mensajes"]) == 1
    assert capturado["mensajes"][0]["role"] == "user"
    assert "Resume esto" in capturado["mensajes"][0]["content"]
    assert "Llamada a cliente" in capturado["mensajes"][0]["content"]


def test_preguntar_antepone_sistema_con_datos_y_reenvia_historial(monkeypatch):
    capturado = {}

    def _chat_falso(proveedor, modelo, mensajes):
        capturado["mensajes"] = mensajes
        return "respuesta"

    monkeypatch.setattr(ai_local, "_chat", _chat_falso)

    historial_previo = [
        {"role": "user", "content": "¿Qué hice ayer?"},
        {"role": "assistant", "content": "Registraste 2 notas."},
    ]
    resultado = ai_local.preguntar(DATOS_EJEMPLO, historial_previo, "¿Y hoy?", "lmstudio", "modelo-x")

    assert resultado == "respuesta"
    mensajes = capturado["mensajes"]
    assert mensajes[0]["role"] == "system"
    assert "Llamada a cliente" in mensajes[0]["content"]
    assert mensajes[1:3] == historial_previo
    assert mensajes[-1] == {"role": "user", "content": "¿Y hoy?"}


def test_preguntar_recorta_historial_muy_largo(monkeypatch):
    capturado = {}

    def _chat_falso(proveedor, modelo, mensajes):
        capturado["mensajes"] = mensajes
        return "ok"

    monkeypatch.setattr(ai_local, "_chat", _chat_falso)

    historial_largo = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    ai_local.preguntar(DATOS_EJEMPLO, historial_largo, "pregunta", "ollama", "modelo")

    # 1 sistema + como mucho MAX_MENSAJES_HISTORIAL previos + 1 pregunta nueva
    assert len(capturado["mensajes"]) <= 1 + ai_local.MAX_MENSAJES_HISTORIAL + 1


def test_preguntar_sin_texto_da_error(monkeypatch):
    monkeypatch.setattr(ai_local, "_chat", lambda p, m, msgs: "no debería llamarse")
    with pytest.raises(ai_local.ErrorIALocal):
        ai_local.preguntar(DATOS_EJEMPLO, [], "   ", "ollama", "llama3.1")


def test_chat_sin_modelo_da_error():
    with pytest.raises(ai_local.ErrorIALocal):
        ai_local._chat("ollama", "  ", [{"role": "user", "content": "hola"}])
