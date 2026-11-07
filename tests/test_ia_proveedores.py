"""Proveedores de IA con clave propia (P1, P2): traducción al formato de OpenAI/Claude, errores sin claves y streaming."""
import base64
import json

import pytest

from app import ia_proveedores as pv
from app.ia_errores import ErrorIA

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG0000").decode()
PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 x").decode()


def test_registro_openrouter_primero_y_regiones():
    assert pv.ORDEN[0] == "openrouter" and {"openai", "anthropic", "gemini", "mistral", "ollama"} <= set(pv.PROVEEDORES)
    assert pv.obtener("mistral").region == "ue" and pv.obtener("ollama").region == "local" and not pv.obtener("ollama").pide_clave
    with pytest.raises(ValueError):
        pv.obtener("inventado")


def test_enmascarar_y_limpiar_no_dejan_pasar_claves():
    assert pv.enmascarar("sk-abcdef1234567890") == "sk-…7890" and pv.enmascarar("corta") == "…"
    texto = "Incorrect API key provided: sk-abcdef1234567890. Also AIzaSyA1234567890123456789012345"
    limpio = pv.limpiar(texto, ["sk-abcdef1234567890"])
    assert "abcdef1234567890" not in limpio and "AIzaSy" not in limpio


def test_url_valida():
    assert pv.url_valida("http://localhost:11434/v1/") == "http://localhost:11434/v1"
    for mala in ("localhost", "ftp://x", "http://", "http://a b"):
        with pytest.raises(ValueError):
            pv.url_valida(mala)


def test_openai_envia_bearer_url_y_normaliza_el_uso(monkeypatch):
    visto = {}

    def falso(url, payload, cabeceras, timeout, claves, nombre, metodo="POST"):
        visto.update(url=url, payload=payload, cab=cabeceras, claves=claves, nombre=nombre)
        return {"choices": [{"message": {"role": "assistant", "content": "hola"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    monkeypatch.setattr(pv, "_http_json", falso)
    r = pv.llamar("openai", "gpt-4o-mini", {"messages": [{"role": "user", "content": "hi"}], "temperature": 0}, "sk-clave-de-prueba")
    assert visto["url"] == "https://api.openai.com/v1/chat/completions" and visto["cab"]["Authorization"] == "Bearer sk-clave-de-prueba"
    assert visto["payload"]["model"] == "gpt-4o-mini" and visto["payload"]["temperature"] == 0 and visto["nombre"] == "OpenAI (ChatGPT)"
    assert r["usage"] == {"prompt_tokens": 10, "completion_tokens": 3} and r["choices"][0]["message"]["content"] == "hola"


def test_openai_razonadores_sin_temperature_y_con_max_completion_tokens(monkeypatch):
    visto = {}
    monkeypatch.setattr(pv, "_http_json", lambda url, payload, *a, **k: visto.update(p=payload) or {"choices": [{"message": {"content": "x"}}]})
    pv.llamar("openai", "o3-mini", {"messages": [], "temperature": 0, "max_tokens": 50}, "sk-clave-de-prueba")
    assert "temperature" not in visto["p"] and visto["p"]["max_completion_tokens"] == 50 and "max_tokens" not in visto["p"]
    pv.llamar("openai", "gpt-5", {"messages": [], "temperature": 0}, "sk-clave-de-prueba")
    assert "temperature" not in visto["p"]
    pv.llamar("openai", "gpt-4o", {"messages": [], "temperature": 0}, "sk-clave-de-prueba")
    assert visto["p"]["temperature"] == 0


def test_ollama_no_manda_autorizacion_y_usa_su_direccion(monkeypatch):
    visto = {}
    monkeypatch.setattr(pv, "_http_json", lambda url, payload, cab, *a, **k: visto.update(url=url, cab=cab) or {"choices": [{"message": {"content": "x"}}]})
    pv.llamar("ollama", "llama3.1", {"messages": []}, "", "http://servidor-interno:11434/v1")
    assert visto["url"] == "http://servidor-interno:11434/v1/chat/completions" and "Authorization" not in visto["cab"]


def test_los_proveedores_sin_pdf_reciben_las_paginas_como_imagenes(monkeypatch):
    visto = {}
    monkeypatch.setattr(pv, "_http_json", lambda url, payload, *a, **k: visto.update(p=payload) or {"choices": [{"message": {"content": "x"}}]})
    from app import pdf_facturas
    monkeypatch.setattr(pdf_facturas, "paginas_a_imagenes", lambda contenido, *a, **k: [b"png1", b"png2"])
    partes = [{"type": "text", "text": "mira"}, {"type": "file", "file": {"filename": "f.pdf", "file_data": PDF}}]
    pv.llamar("gemini", "gemini-2.0-flash", {"messages": [{"role": "user", "content": partes}]}, "AIzaclavedeprueba")
    enviadas = visto["p"]["messages"][0]["content"]
    assert [p["type"] for p in enviadas] == ["text", "image_url", "image_url"]
    pv.llamar("openai", "gpt-4o", {"messages": [{"role": "user", "content": partes}]}, "sk-clave-de-prueba")                    # OpenAI sí lee PDF
    assert [p["type"] for p in visto["p"]["messages"][0]["content"]] == ["text", "file"]


def test_traduccion_a_anthropic_mensajes_herramientas_imagenes_y_pdf():
    payload = {"temperature": 0, "messages": [
        {"role": "system", "content": "Eres contable"},
        {"role": "user", "content": [{"type": "text", "text": "factura"}, {"type": "image_url", "image_url": {"url": PNG}}, {"type": "file", "file": {"filename": "f.pdf", "file_data": PDF}}]},
        {"role": "assistant", "content": "voy a mirar", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "listar", "arguments": "{\"n\": 2}"}},
                                                                    {"id": "t2", "type": "function", "function": {"name": "otra", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "uno"}, {"role": "tool", "tool_call_id": "t2", "content": "dos"},
        {"role": "user", "content": "gracias"}],
        "tools": [{"type": "function", "function": {"name": "listar", "description": "Lista", "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}}}}]}
    a = pv._a_anthropic(payload, "claude-sonnet-5-5")
    assert a["system"] == "Eres contable" and a["model"] == "claude-sonnet-5-5" and a["max_tokens"] == pv.ANTHROPIC_MAX_TOKENS and a["temperature"] == 0
    u1 = a["messages"][0]
    assert u1["role"] == "user" and [b["type"] for b in u1["content"]] == ["text", "image", "document"]
    assert u1["content"][1]["source"] == {"type": "base64", "media_type": "image/png", "data": PNG.split(",")[1]}
    assert u1["content"][2]["source"]["media_type"] == "application/pdf"
    asistente = a["messages"][1]
    assert asistente["role"] == "assistant" and [b["type"] for b in asistente["content"]] == ["text", "tool_use", "tool_use"] and asistente["content"][1]["input"] == {"n": 2}
    resultados = a["messages"][2]                                            # los dos resultados de herramienta + el «gracias» van en UN mensaje de usuario, como exige Claude
    assert resultados["role"] == "user" and [b["type"] for b in resultados["content"]] == ["tool_result", "tool_result", "text"]
    assert [m["role"] for m in a["messages"]] == ["user", "assistant", "user"]
    assert a["tools"] == [{"name": "listar", "description": "Lista", "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}}}]


def test_anthropic_siempre_empieza_por_usuario():
    a = pv._a_anthropic({"messages": [{"role": "assistant", "content": "hola"}]}, "m")
    assert a["messages"][0]["role"] == "user"


def test_respuesta_de_anthropic_vuelve_con_forma_de_openai(monkeypatch):
    visto = {}

    def falso(url, payload, cabeceras, timeout, claves, nombre, metodo="POST"):
        visto.update(url=url, cab=cabeceras, payload=payload)
        return {"content": [{"type": "text", "text": "Voy"}, {"type": "tool_use", "id": "tu1", "name": "listar", "input": {"n": 1}}], "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5}}
    monkeypatch.setattr(pv, "_http_json", falso)
    r = pv.llamar("anthropic", "claude-sonnet-5-5", {"messages": [{"role": "user", "content": "hola"}]}, "sk-ant-prueba-12345")
    assert visto["url"] == "https://api.anthropic.com/v1/messages" and visto["cab"]["x-api-key"] == "sk-ant-prueba-12345" and visto["cab"]["anthropic-version"] == pv.ANTHROPIC_VERSION
    m = r["choices"][0]["message"]
    assert m["content"] == "Voy" and m["tool_calls"] == [{"id": "tu1", "type": "function", "function": {"name": "listar", "arguments": "{\"n\": 1}"}}]
    assert r["usage"] == {"prompt_tokens": 105, "completion_tokens": 20}


def test_streaming_de_anthropic_y_de_openai(monkeypatch):
    eventos = [{"type": "message_start", "message": {"usage": {"input_tokens": 50, "output_tokens": 1}}},
               {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
               {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hola "}},
               {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "mundo"}},
               {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu9", "name": "listar"}},
               {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"n\":"}},
               {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": " 3}"}},
               {"type": "message_delta", "usage": {"output_tokens": 42}}]
    trozos = list(pv._chunks_de_anthropic(iter(eventos)))
    texto = "".join(t["choices"][0]["delta"].get("content", "") for t in trozos if "choices" in t)
    assert texto == "Hola mundo"
    args = "".join(tc["function"]["arguments"] for t in trozos if "choices" in t for tc in t["choices"][0]["delta"].get("tool_calls", []))
    assert args == "{\"n\": 3}" or args == "{\"n\":" + " 3}"
    inicio = [tc for t in trozos if "choices" in t for tc in t["choices"][0]["delta"].get("tool_calls", []) if tc.get("id")][0]
    assert inicio["id"] == "tu9" and inicio["function"]["name"] == "listar" and inicio["index"] == 0
    assert trozos[-1] == {"usage": {"prompt_tokens": 50, "completion_tokens": 42}}
    with pytest.raises(ErrorIA, match="cortó"):
        list(pv._chunks_de_anthropic(iter([{"type": "error", "error": {"message": "overloaded"}}])))


def test_el_streaming_de_openai_pide_el_uso_y_lo_normaliza(monkeypatch):
    visto = {}

    class Resp(list):
        def close(self):
            pass
    monkeypatch.setattr(pv, "_abrir_stream", lambda url, payload, *a: visto.update(p=payload) or Resp([b'data: {"choices":[{"delta":{"content":"a"}}]}\n', b"\n",
                                                                                                      b'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":2}}\n', b"data: [DONE]\n"]))
    trozos = list(pv.llamar_stream("openai", "gpt-4o-mini", {"messages": []}, "sk-clave-de-prueba"))
    assert visto["p"]["stream"] is True and visto["p"]["stream_options"] == {"include_usage": True}
    assert trozos[0]["choices"][0]["delta"]["content"] == "a" and trozos[-1]["usage"] == {"prompt_tokens": 7, "completion_tokens": 2}


def test_los_errores_http_no_llevan_la_clave(monkeypatch):
    import io
    import urllib.error

    def falla(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b'{"error":"Incorrect API key provided: sk-secreta-1234567890abcd"}'))
    monkeypatch.setattr(pv.urllib.request, "urlopen", falla)
    with pytest.raises(ErrorIA) as e:
        pv.llamar("openai", "gpt-4o", {"messages": []}, "sk-secreta-1234567890abcd")
    assert e.value.codigo_http == 401 and "secreta" not in str(e.value) and "***" in str(e.value)


def test_probar_traduce_los_codigos_en_mensajes_legibles(monkeypatch):
    def falla(codigo):
        def f(*a, **k):
            raise ErrorIA("x", codigo_http=codigo)
        return f
    for codigo, texto in ((401, "no acepta la clave"), (402, "saldo"), (404, "modelo no existe"), (429, "limitado")):
        monkeypatch.setattr(pv, "llamar", falla(codigo))
        assert texto in pv.probar("openai", "m", "k")
    monkeypatch.setattr(pv, "llamar", lambda *a, **k: {})
    assert pv.probar("openai", "m", "k") == ""


def test_listar_modelos_filtra_lo_que_no_es_chat(monkeypatch):
    monkeypatch.setattr(pv, "_http_json", lambda *a, **k: {"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "gpt-4o-mini"}, {"id": "dall-e-3"}]})
    assert pv.listar_modelos("openai", "sk-clave-de-prueba") == ["gpt-4o", "gpt-4o-mini"]
    monkeypatch.setattr(pv, "_http_json", lambda *a, **k: {"models": [{"id": "models/gemini-2.0-flash"}]})
    assert pv.listar_modelos("gemini", "AIzaclavedeprueba") == ["gemini-2.0-flash"]
