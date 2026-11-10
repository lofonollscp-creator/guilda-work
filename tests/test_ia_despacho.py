"""Claves y proveedores de IA del despacho (P3, P4, P6): orden de candidatos, normas, reintentos entre proveedores y uso/coste."""
import json

import pytest

from app import db, ia_asistente as a, ia_claves, ia_despacho as dz, ia_proveedores as pv, ia_uso
from app.ia_errores import ErrorIA


@pytest.fixture
def despacho():
    t = db.crear_tenant("IA Despacho")
    u = db.crear_usuario_vinculado_a_kratos("dir-ia@ejemplo.com", "k-dir-ia")
    db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(u, True)
    u2 = db.crear_usuario_vinculado_a_kratos("emp-ia@ejemplo.com", "k-emp-ia")
    db.asignar_tenant(u2, t)
    return t, u, u2


def _de_despacho(t, u, proveedor="openai", modelo="gpt-4o-mini", clave="sk-despacho-1234567890", **kw):
    dz.guardar(t, proveedor, activo=True, modelo_asistente=modelo, claves_nuevas=[clave] if clave else None, por=u, **kw)


def test_guardar_exige_clave_y_modelo_y_nunca_guarda_la_clave_en_la_base(despacho):
    t, u, _ = despacho
    with pytest.raises(ValueError, match="clave"):
        dz.guardar(t, "openai", activo=True, modelo_asistente="gpt-4o")
    with pytest.raises(ValueError, match="modelo"):
        dz.guardar(t, "openai", activo=True, claves_nuevas=["sk-despacho-1234567890"])
    with pytest.raises(ValueError, match="clave"):
        dz.guardar(t, "openai", activo=True, modelo_asistente="gpt-4o", claves_nuevas=["corta"])
    with pytest.raises(ValueError, match="modelo"):
        dz.guardar(t, "openai", activo=False, modelo_asistente="con espacios")
    _de_despacho(t, u, clave="sk-despacho-1234567890")
    conn = db.get_connection()
    filas = [dict(f) for f in conn.execute("SELECT * FROM ia_proveedores_despacho").fetchall()]
    conn.close()
    volcado = json.dumps(filas, ensure_ascii=False)
    assert "despacho-1234567890" not in volcado and "sk-…7890" in volcado
    assert ia_claves.de_despacho("openai", t) == ["sk-despacho-1234567890"]
    p = next(x for x in dz.listar(t) if x["id"] == "openai")
    assert p["activo"] and p["claves"] == ["sk-…7890"] and "sk-despacho" not in json.dumps(p)


def test_ollama_no_pide_clave_pero_si_direccion_valida(despacho):
    t, u, _ = despacho
    dz.guardar(t, "ollama", activo=True, modelo_asistente="llama3.1", url_base="http://servidor:11434/v1")
    c = dz.candidatos(t, "asistente")
    assert c == [{"proveedor": "ollama", "modelo": "llama3.1", "claves": [""], "url_base": "http://servidor:11434/v1", "origen": "despacho"}]
    with pytest.raises(ValueError, match="dirección"):
        dz.guardar(t, "ollama", activo=True, modelo_asistente="x", url_base="nada")
    with pytest.raises(ValueError, match="Solo se puede cambiar"):
        dz.guardar(t, "anthropic", activo=False, url_base="http://otro.com/v1")


def test_el_orden_se_puede_cambiar_y_el_modelo_de_facturas_manda_en_facturas(despacho):
    t, u, _ = despacho
    _de_despacho(t, u, "openai", "gpt-4o-mini")
    dz.guardar(t, "anthropic", activo=True, modelo_asistente="claude-haiku-5-5", modelo_facturas="claude-sonnet-5-5", claves_nuevas=["sk-ant-despacho-12345"], por=u)
    assert [c["proveedor"] for c in dz.candidatos(t, "asistente")] == ["openai", "anthropic"]
    dz.mover(t, "anthropic", arriba=True)
    assert [c["proveedor"] for c in dz.candidatos(t, "asistente")] == ["anthropic", "openai"]
    por_tarea = {c["proveedor"]: c["modelo"] for c in dz.candidatos(t, "facturas")}
    assert por_tarea == {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o-mini"}                  # sin modelo propio de facturas, el del asistente
    assert {c["proveedor"]: c["modelo"] for c in dz.candidatos(t, "asistente")}["anthropic"] == "claude-haiku-5-5"
    dz.mover(t, "anthropic", arriba=True)                                                           # ya es el primero: no pasa nada
    assert dz.candidatos(t, "asistente")[0]["proveedor"] == "anthropic"
    dz.guardar(t, "anthropic", activo=False, modelo_asistente="claude-haiku-5-5")
    assert [c["proveedor"] for c in dz.candidatos(t, "asistente")] == ["openai"]


def test_las_claves_de_la_persona_van_primero_y_despues_las_del_despacho(despacho):
    t, u, u2 = despacho
    _de_despacho(t, u)
    db.guardar_preferencias_ia(u2, "gpt-4o", False)
    conn = db.get_connection(); conn.execute("UPDATE ia_preferencias SET proveedor_ia = 'openai' WHERE usuario_id = ?", (u2,)); conn.commit(); conn.close()
    ia_claves.guardar_de_usuario("openai", u2, ["sk-personal-abcdefgh"])
    c = a.candidatos(u2, "asistente")
    assert [(x["origen"], x["proveedor"], x["modelo"], x["claves"]) for x in c] == [("usuario", "openai", "gpt-4o", ["sk-personal-abcdefgh"]), ("despacho", "openai", "gpt-4o-mini", ["sk-despacho-1234567890"])]
    sin_claves_propias = a.candidatos(u, "asistente")
    assert [x["origen"] for x in sin_claves_propias] == ["despacho"]                               # quien no tiene las suyas usa las del despacho


def test_openrouter_personal_sigue_funcionando_como_siempre(despacho):
    t, u, u2 = despacho
    db.guardar_preferencias_ia(u2, "meta-llama/llama-3.1-70b-instruct:free", False)
    a.guardar_api_keys(u2, ["sk-or-personal-12345678"])
    assert a.obtener_api_keys(u2) == ["sk-or-personal-12345678"]
    c = a.candidatos(u2, "facturas")
    assert c == [{"proveedor": "openrouter", "modelo": "meta-llama/llama-3.1-70b-instruct:free", "claves": ["sk-or-personal-12345678"], "url_base": None, "origen": "usuario"}]
    assert a.disponible(u2, "facturas") and not a.disponible(u, "facturas")


def test_normas_solo_ue_y_sin_claves_personales(despacho):
    t, u, u2 = despacho
    _de_despacho(t, u, "openai")
    dz.guardar(t, "mistral", activo=True, modelo_asistente="pixtral-large-latest", claves_nuevas=["mistral-clave-12345"], por=u)
    db.guardar_preferencias_ia(u2, "gpt-4o", False)
    conn = db.get_connection(); conn.execute("UPDATE ia_preferencias SET proveedor_ia = 'openai' WHERE usuario_id = ?", (u2,)); conn.commit(); conn.close()
    ia_claves.guardar_de_usuario("openai", u2, ["sk-personal-abcdefgh"])
    dz.guardar_config(t, solo_ue=True, claves_personales=True, facturas_modo="compartida", umbral_confianza=90, por=u)
    assert [(x["origen"], x["proveedor"]) for x in a.candidatos(u2, "asistente")] == [("despacho", "mistral")]       # OpenAI manda datos fuera de la UE
    with pytest.raises(ValueError, match="UE"):
        _de_despacho(t, u, "openai", "gpt-4o")
    dz.guardar_config(t, solo_ue=False, claves_personales=False, facturas_modo="compartida", umbral_confianza=90, por=u)
    assert [x["origen"] for x in a.candidatos(u2, "asistente")] == ["despacho", "despacho"]                        # sin claves personales


def test_config_valida_modo_y_umbral(despacho):
    t, u, _ = despacho
    assert dz.config(t) == {"solo_ue": False, "claves_personales": True, "facturas_modo": "compartida", "umbral_confianza": 90, "lectura_texto": True, "separar_pdf": True, "ocr_local": "respaldo", "segunda_lectura": False}
    with pytest.raises(ValueError, match="modo"):
        dz.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="otro", umbral_confianza=90)
    for malo in (10, 101, "x"):
        with pytest.raises(ValueError, match="umbral"):
            dz.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="auto", umbral_confianza=malo)
    dz.guardar_config(t, solo_ue=True, claves_personales=False, facturas_modo="auto", umbral_confianza=95, lectura_texto=False, por=u)
    assert dz.config(t) == {"solo_ue": True, "claves_personales": False, "facturas_modo": "auto", "umbral_confianza": 95, "lectura_texto": False, "separar_pdf": True, "ocr_local": "respaldo", "segunda_lectura": False}


def _openai_ok(texto="hecho", entrada=1000, salida=200):
    return {"choices": [{"message": {"role": "assistant", "content": texto}}], "usage": {"prompt_tokens": entrada, "completion_tokens": salida}}


def test_si_falla_el_primero_responde_el_siguiente_y_se_anota_el_uso(despacho, monkeypatch):
    t, u, u2 = despacho
    _de_despacho(t, u, "openai", "gpt-4o-mini")
    dz.guardar(t, "anthropic", activo=True, modelo_asistente="claude-haiku-5-5", claves_nuevas=["sk-ant-despacho-12345"], por=u)
    llamadas = []

    def falso(proveedor, modelo, payload, clave, url_base=None, timeout=30):
        llamadas.append((proveedor, modelo, clave))
        if proveedor == "openai":
            raise ErrorIA("OpenAI devolvió un error (500)", codigo_http=500)
        return _openai_ok()
    monkeypatch.setattr(pv, "llamar", falso)
    r = a._llamar(u, "asistente", {"messages": [{"role": "user", "content": "hola"}]})
    assert r["choices"][0]["message"]["content"] == "hecho" and [x[0] for x in llamadas] == ["openai", "anthropic"]
    uso = ia_uso.resumen(t)
    assert [(f["proveedor"], f["tarea"], f["origen"], f["llamadas"]) for f in uso["filas"]] == [("anthropic", "asistente", "despacho", 1)]
    assert uso["filas"][0]["tokens_entrada"] == 1000 and uso["hay_sin_tarifa"] is True                 # claude-haiku-5-5 aún no tiene tarifa conocida: no se inventa


def test_si_todos_fallan_el_error_es_el_del_primero_y_no_se_anota_uso(despacho, monkeypatch):
    t, u, _ = despacho
    _de_despacho(t, u, "openai")
    dz.guardar(t, "anthropic", activo=True, modelo_asistente="claude-haiku-5-5", claves_nuevas=["sk-ant-despacho-12345"], por=u)

    def falso(proveedor, *a, **k):
        raise ErrorIA(f"{proveedor} caído", codigo_http=500)
    monkeypatch.setattr(pv, "llamar", falso)
    with pytest.raises(ErrorIA, match="openai caído"):
        a._llamar(u, "asistente", {"messages": []})
    assert ia_uso.resumen(t)["filas"] == []


def test_varias_claves_del_mismo_proveedor_pasan_a_la_siguiente_si_la_primera_no_vale(despacho, monkeypatch):
    t, u, _ = despacho
    dz.guardar(t, "openai", activo=True, modelo_asistente="gpt-4o-mini", claves_nuevas=["sk-sin-saldo-1234567", "sk-buena-12345678"], por=u)
    usadas = []

    def falso(proveedor, modelo, payload, clave, url_base=None, timeout=30):
        usadas.append(clave)
        if clave.startswith("sk-sin-saldo"):
            raise ErrorIA("sin saldo", codigo_http=402)
        return _openai_ok()
    monkeypatch.setattr(pv, "llamar", falso)
    a._llamar(u, "asistente", {"messages": []})
    assert usadas == ["sk-sin-saldo-1234567", "sk-buena-12345678"]


def test_sin_nada_configurado_los_mensajes_de_siempre(despacho):
    t, u, u2 = despacho
    with pytest.raises(ErrorIA, match="ningún modelo"):
        a.completar_texto(u2, "s", "c")
    db.guardar_preferencias_ia(u2, "algun/modelo", False)
    with pytest.raises(ErrorIA, match="ninguna clave"):
        a.completar_texto(u2, "s", "c")


def test_las_consultas_con_clave_del_despacho_funcionan_de_extremo_a_extremo(despacho, monkeypatch):
    t, u, u2 = despacho
    _de_despacho(t, u, "anthropic", "claude-sonnet-5-5", "sk-ant-despacho-12345")
    monkeypatch.setattr(pv, "_http_json", lambda url, payload, cab, *r, **k: {"content": [{"type": "text", "text": "Respuesta de Claude"}], "usage": {"input_tokens": 12, "output_tokens": 4}})
    assert a.completar_texto(u2, "sistema", "contenido") == "Respuesta de Claude"
    assert ia_uso.resumen(t)["filas"][0]["proveedor"] == "anthropic"


def test_stream_con_proveedor_propio_y_cambio_de_candidato_al_abrir(despacho, monkeypatch):
    t, u, u2 = despacho
    _de_despacho(t, u, "openai", "gpt-4o-mini")
    dz.guardar(t, "anthropic", activo=True, modelo_asistente="claude-haiku-5-5", claves_nuevas=["sk-ant-despacho-12345"], por=u)

    def flujo(proveedor, modelo, payload, clave, url_base=None):
        if proveedor == "openai":
            raise ErrorIA("caído", codigo_http=503)
        yield {"choices": [{"delta": {"content": "a"}}]}
        yield {"choices": [{"delta": {"content": "b"}}]}
        yield {"usage": {"prompt_tokens": 9, "completion_tokens": 2}}
    monkeypatch.setattr(pv, "llamar_stream", flujo)
    trozos = list(a._llamar_stream(u2, "asistente", {"messages": []}))
    assert "".join(t_["choices"][0]["delta"]["content"] for t_ in trozos if "choices" in t_) == "ab"
    assert ia_uso.resumen(t)["filas"][0]["tokens_salida"] == 2


def test_coste_estimado():
    assert ia_uso.coste_estimado("openai", "gpt-4o-mini", 1_000_000, 1_000_000, None) == pytest.approx(0.75)
    assert ia_uso.coste_estimado("openrouter", "openai/gpt-4o", 1_000_000, 0, None) == pytest.approx(2.5)
    assert ia_uso.coste_estimado("openrouter", "x/y:free", 5000, 5000, None) == 0.0
    assert ia_uso.coste_estimado("openrouter", "x/y", 5, 5, {"cost": 0.0123}) == 0.0123
    assert ia_uso.coste_estimado("ollama", "lo-que-sea", 9, 9, None) == 0.0
    assert ia_uso.coste_estimado("anthropic", "claude-modelo-nuevo", 100, 100, None) is None


def test_el_uso_se_acumula_por_mes_proveedor_tarea_y_origen(despacho):
    t, u, _ = despacho
    for _ in range(3):
        ia_uso.registrar(t, "openai", "gpt-4o-mini", "facturas", "despacho", {"prompt_tokens": 1000, "completion_tokens": 100})
    ia_uso.registrar(t, "openai", "gpt-4o-mini", "asistente", "usuario", {"prompt_tokens": 10, "completion_tokens": 1})
    r = ia_uso.resumen(t)
    fila = next(f for f in r["filas"] if f["tarea"] == "facturas")
    assert fila["llamadas"] == 3 and fila["tokens_entrada"] == 3000 and fila["coste_usd"] == pytest.approx(3 * (1000 * 0.15 + 100 * 0.60) / 1_000_000)
    assert r["total_llamadas"] == 4 and r["hay_sin_tarifa"] is False
    ia_uso.registrar(None, "openai", "m", "x", "usuario", {})                                      # sin despacho: no hace nada ni falla
