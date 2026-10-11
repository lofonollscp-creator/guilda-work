"""El asistente como soporte de la plataforma (app/ia_soporte.py): búsqueda en la ayuda, pantallas, ajustes propios,
modo soporte sin coste en el límite de IA y borrador de tiquets."""
import json

import pytest

from app import db, ia_asistente, ia_consumo, ia_herramientas as ih, ia_soporte


# --- ¿qué es soporte? --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto", [
    "¿Cómo funciona esta pantalla y qué puedo hacer aquí?", "Ayúdame a configurar mi cuenta: idioma, perfil y avisos.",
    "¿Cómo conecto mi correo?", "¿Dónde cambio la contraseña?", "No me llega el correo de recuperación", "Hay un error al exportar",
    "How do I connect my email?", "Where is my profile?", "Com puc canviar l'idioma?", "Comment puis-je activer la vérification en deux étapes ?",
    "Quiero sugerir una mejora",
])
def test_detecta_soporte(texto):
    assert ia_soporte.es_consulta_soporte(texto)


@pytest.mark.parametrize("texto", [
    "Hazme un resumen de mi día: tareas para hoy y atrasadas.", "Lista mis tareas atrasadas ordenadas por prioridad.", "Crea una tarea para llamar a Pedro",
    "¿Qué vencimientos fiscales y tareas vencen esta semana?", "Resume cómo funciona el IVA de mi cliente", "Show my overdue tasks", "", None,
])
def test_los_datos_no_son_soporte(texto):
    assert not ia_soporte.es_consulta_soporte(texto)


def test_los_atajos_de_soporte_de_serie_se_detectan_en_todos_los_idiomas():
    from app import ia_atajos

    for titulo, prompt in ia_atajos.DE_SERIE[-2:]:
        assert ia_soporte.es_consulta_soporte(str(prompt))


# --- búsqueda en la ayuda -----------------------------------------------------------------------------------------------------------------
@pytest.fixture
def ayuda_falsa(tmp_path, monkeypatch):
    articulos = [
        {"titulo": "Conectar tu cuenta de correo", "categoria": "Primeros pasos", "url": "/primeros-pasos/conectar-correo/", "extracto": "x",
         "texto": "para conectar el correo ve a correo cuentas y pulsa añadir cuenta. funciona con gmail y outlook"},
        {"titulo": "Verificación en dos pasos", "categoria": "Mi cuenta", "url": "/mi-cuenta/verificacion-en-dos-pasos/", "extracto": "y",
         "texto": "activa la verificación en dos pasos desde ajustes de la cuenta con una app de autenticación"},
        {"titulo": "Fichaje", "categoria": "Trabajo diario", "url": "/trabajo-diario/fichaje/", "extracto": "z", "texto": "ficha la entrada y la salida"},
    ]
    (tmp_path / "indice.json").write_text(json.dumps(articulos), encoding="utf-8")
    (tmp_path / "en").mkdir()
    (tmp_path / "en" / "indice.json").write_text(json.dumps([{**articulos[0], "titulo": "Connect your email account", "url": "/getting-started/connect-email/", "texto": "connect your email account"}]), encoding="utf-8")
    monkeypatch.setenv("GUILDA_AYUDA_INDICE_DIR", str(tmp_path))
    ia_soporte._CACHE.clear()
    return tmp_path


def test_busca_el_articulo_correcto_con_enlace_en_su_idioma(ayuda_falsa):
    r = ia_soporte.buscar_ayuda("¿cómo conecto mi correo?")
    assert r[0]["titulo"] == "Conectar tu cuenta de correo" and r[0]["enlace"].endswith("/primeros-pasos/conectar-correo/")
    assert ia_soporte.buscar_ayuda("activar la verificación en dos pasos")[0]["titulo"] == "Verificación en dos pasos"
    en = ia_soporte.buscar_ayuda("connect email account", "en")
    assert "/en/getting-started/connect-email/" in en[0]["enlace"]
    assert ia_soporte.buscar_ayuda("zzzz qqqq") == [] and ia_soporte.buscar_ayuda("") == []


def test_sin_indice_no_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("GUILDA_AYUDA_INDICE_DIR", str(tmp_path / "no-existe"))
    ia_soporte._CACHE.clear()
    assert ia_soporte.buscar_ayuda("correo") == []


def test_el_indice_real_responde_a_las_dudas_habituales():
    """Con el centro de ayuda publicado en este equipo, las dudas típicas llevan al artículo correcto (se omite si no está)."""
    import os
    from pathlib import Path

    if not Path(os.environ.get("GUILDA_AYUDA_INDICE_DIR") or "/home/guilda/guilda-help/salida", "indice.json").exists():
        pytest.skip("el centro de ayuda no está publicado aquí")
    ia_soporte._CACHE.clear()
    for consulta, parte in (("conectar el correo", "correo"), ("verificación en dos pasos", "dos-pasos"), ("fichar entrada y salida", "fichaje")):
        assert any(parte in a["enlace"] for a in ia_soporte.buscar_ayuda(consulta)), consulta


# --- pantallas ----------------------------------------------------------------------------------------------------------------------------
def test_todos_los_destinos_resuelven(cliente, usuario_id):
    from app.main import app

    with app.test_request_context("/"):
        for destino in ia_soporte.DESTINOS:
            r = ia_soporte.abrir_pantalla(usuario_id, destino)
            assert r["enlace"].startswith("https://") and "error" not in r, destino
        assert "error" in ia_soporte.abrir_pantalla(usuario_id, "no-existe")
        assert ia_soporte.abrir_pantalla(usuario_id, "notificaciones")["enlace"].endswith("#notificaciones")


# --- ajustes de la propia cuenta -----------------------------------------------------------------------------------------------------------
def test_cambia_solo_los_ajustes_pedidos_de_su_cuenta(usuario_id):
    otro = db.crear_usuario_vinculado_a_kratos("otro-soporte@ejemplo.com", "kratos-otro-soporte")
    r = ia_soporte.cambiar_mis_ajustes(usuario_id, idioma="ca", cargo="Gestora", avisos_correo=False, no_molestar_desde="22:00", no_molestar_hasta="08:00")
    assert "error" not in r and db.idioma_usuario(usuario_id) == "ca"
    perfil = db.obtener_perfil_usuario(usuario_id)
    assert perfil["cargo"] == "Gestora" and not perfil["notificar_push_correo"] and perfil["silencio_desde"] == "22:00"
    assert db.idioma_usuario(otro) != "ca" and db.obtener_perfil_usuario(otro)["cargo"] is None
    ia_soporte.cambiar_mis_ajustes(usuario_id, quitar_no_molestar=True)
    assert db.obtener_perfil_usuario(usuario_id)["silencio_desde"] is None


@pytest.mark.parametrize("kw", [{"idioma": "de"}, {"no_molestar_desde": "25:00", "no_molestar_hasta": "08:00"}, {"no_molestar_desde": "10:00", "no_molestar_hasta": "10:00"}, {}])
def test_ajustes_invalidos_no_cambian_nada(usuario_id, kw):
    antes = (db.idioma_usuario(usuario_id), dict(db.obtener_perfil_usuario(usuario_id)))
    assert "error" in ia_soporte.cambiar_mis_ajustes(usuario_id, **kw)
    assert (db.idioma_usuario(usuario_id), dict(db.obtener_perfil_usuario(usuario_id))) == antes


def test_el_asistente_no_puede_tocar_seguridad_ni_otros_usuarios():
    herramienta = next(t for t in ih.HERRAMIENTAS if t["function"]["name"] == "cambiar_mis_ajustes")
    params = set(herramienta["function"]["parameters"]["properties"])
    assert not params & {"usuario_id", "password", "contrasena", "email", "totp", "tema", "modo_autonomo", "solo_lectura"}
    assert "cambiar_mis_ajustes" in ih.ESCRITURA and ih.necesita_confirmacion("cambiar_mis_ajustes", modo_autonomo=False)
    for lectura in ("ayuda_buscar", "abrir_pantalla", "ver_mis_ajustes"):
        assert lectura in ih.LECTURA


# --- herramientas ofrecidas ---------------------------------------------------------------------------------------------------------------
def _mensajes(texto):
    return [{"role": "system", "content": "s"}, {"role": "user", "content": texto}]


def _nombres(msgs):
    return {t["function"]["name"] for t in ih.herramientas_para(msgs)}


def test_en_soporte_solo_se_ofrecen_las_herramientas_de_soporte():
    n = _nombres(_mensajes("¿Cómo conecto mi correo?"))
    assert n == set(ia_soporte.HERRAMIENTAS_SOPORTE) and "crear_tiquet" in n
    assert not n & {"listar_bandeja_entrada", "listar_tareas", "crear_tarea", "listar_notas", "activar_herramientas", "leer_correo"}


def test_fuera_de_soporte_la_ayuda_sigue_disponible_y_los_ajustes_por_palabra_clave():
    n = _nombres(_mensajes("Lista mis tareas atrasadas"))
    assert {"ayuda_buscar", "abrir_pantalla", "listar_tareas"} <= n and "cambiar_mis_ajustes" not in n
    assert "cambiar_mis_ajustes" in _nombres(_mensajes("Crea una tarea y pon mi idioma en catalán"))


# --- el soporte no cuenta en el límite de IA -----------------------------------------------------------------------------------------------
def _tenant_con_limite(usuario_id, limite):
    t = db.crear_tenant("Despacho soporte")
    db.asignar_tenant(usuario_id, t)
    ia_consumo.fijar_limite(t, limite)
    return t


def test_una_consulta_de_soporte_no_consume_ni_se_bloquea_por_el_limite(usuario_id):
    t = _tenant_con_limite(usuario_id, 1)
    ia_asistente._reservar_turno(usuario_id, "Lista mis tareas")           # consulta de datos: consume la única
    assert ia_consumo.estado(t)["usadas"] == 1
    with pytest.raises(ia_asistente.ErrorIA):
        ia_asistente._reservar_turno(usuario_id, "Lista mis tareas")        # agotado
    ia_asistente._reservar_turno(usuario_id, "¿Cómo conecto mi correo?")    # soporte: pasa igualmente
    assert ia_consumo.estado(t)["usadas"] == 1, "el soporte no suma"


def test_con_la_ia_desactivada_tampoco_hay_soporte(usuario_id):
    _tenant_con_limite(usuario_id, 0)
    with pytest.raises(ia_asistente.ErrorIA):
        ia_asistente._reservar_turno(usuario_id, "¿Cómo conecto mi correo?")


def test_el_cupo_diario_gratuito_evita_abusos(usuario_id, monkeypatch):
    t = _tenant_con_limite(usuario_id, 100)
    monkeypatch.setattr(ia_soporte, "TOPE_DIARIO_GRATIS", 2)
    for _ in range(2):
        ia_asistente._reservar_turno(usuario_id, "¿Cómo conecto mi correo?")
    assert ia_consumo.estado(t)["usadas"] == 0
    ia_asistente._reservar_turno(usuario_id, "¿Cómo conecto mi correo?")    # pasado el cupo: cuenta como una normal, no se rechaza
    assert ia_consumo.estado(t)["usadas"] == 1


# --- prompt y tiquets -----------------------------------------------------------------------------------------------------------------------
def test_el_prompt_enseña_a_hacer_soporte_y_a_registrar_tiquets(usuario_id):
    p = ia_asistente._prompt_sistema(usuario_id, "es", soporte=True)
    for clave in ("ayuda_buscar", "abrir_pantalla", "cambiar_mis_ajustes", "crear_tiquet", "«error» o «sugerencia»", "sin datos personales", "solo atiendes soporte"):
        assert clave in p, clave
    assert "solo atiendes soporte" not in ia_asistente._prompt_sistema(usuario_id, "es", soporte=False)


def test_la_pantalla_actual_llega_al_prompt(usuario_id):
    ia_soporte.recordar_pantalla(usuario_id, "correo.cuentas")
    assert "correo.cuentas" in ia_asistente._prompt_sistema(usuario_id, "es") and "primeros-pasos/conectar-correo" in ia_asistente._prompt_sistema(usuario_id, "es")
    ia_soporte.recordar_pantalla(usuario_id, "ia.panel_flotante")
    assert "correo.cuentas" not in ia_asistente._prompt_sistema(usuario_id, "es")


def test_registrar_tiquet_desde_el_chat_pide_confirmacion_y_lo_crea(usuario_id):
    assert ih.necesita_confirmacion("crear_tiquet", modo_autonomo=False)
    r = ih.ejecutar(usuario_id, "crear_tiquet", {"tipo": "sugerencia", "titulo": "Botón de PDF en tareas", "descripcion": "Pantalla: tareas."})
    assert r["tipo"] == "sugerencia" and r["estado"] == "sin_revisar"


def test_ejecutar_herramientas_de_soporte(usuario_id, ayuda_falsa):
    assert ih.ejecutar(usuario_id, "ayuda_buscar", {"consulta": "conectar correo"})["resultados"]
    assert "aviso" in ih.ejecutar(usuario_id, "ayuda_buscar", {"consulta": "zzzz qqqq"})
    assert "idioma" in ih.ejecutar(usuario_id, "ver_mis_ajustes", {})


# --- de punta a punta con un modelo simulado --------------------------------------------------------------------------------------------------
def _llamada(*llamadas):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": tid, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}} for tid, n, a in llamadas]}}]}


def _texto(t):
    return {"choices": [{"message": {"role": "assistant", "content": t}}]}


def test_duda_de_soporte_de_punta_a_punta_sin_consumir_limite(monkeypatch, usuario_id, ayuda_falsa):
    t = _tenant_con_limite(usuario_id, 5)
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", False, solo_lectura=False)
    ia_asistente.guardar_api_keys(usuario_id, ["clave-falsa"])
    cola = [_llamada(("c1", "ayuda_buscar", {"consulta": "conectar correo"})), _texto("Ve a Cuentas. Más información: https://help.guildawork.com/x")]
    enviados = []
    monkeypatch.setattr(ia_asistente, "_post_json", lambda url, payload, key: (enviados.append(payload), cola.pop(0))[1])
    r = ia_asistente.procesar_turno(usuario_id, "¿Cómo conecto mi correo?")
    assert r["pendiente"] is None and "Más información" in r["mensajes_nuevos"][-1]["contenido"]
    assert {x["function"]["name"] for x in enviados[0]["tools"]} == set(ia_soporte.HERRAMIENTAS_SOPORTE)
    assert "solo atiendes soporte" in enviados[0]["messages"][0]["content"]
    tool = next(m for m in r["mensajes_nuevos"] if m["rol"] == "tool")
    assert "Conectar tu cuenta de correo" in tool["contenido"]
    assert ia_consumo.estado(t)["usadas"] == 0


def test_sugerencia_desde_el_chat_pide_confirmacion_antes_de_crear_el_tiquet(monkeypatch, usuario_id):

    ia_asistente.guardar_api_keys(usuario_id, ["clave-falsa"])
    db.guardar_preferencias_ia(usuario_id, "modelo-de-prueba", False, solo_lectura=False)
    args = {"tipo": "sugerencia", "titulo": "Exportar tareas a PDF", "descripcion": "Pantalla: tareas. Falta el botón."}
    cola = [_llamada(("c1", "crear_tiquet", args)), _texto("Registrado.")]
    monkeypatch.setattr(ia_asistente, "_post_json", lambda url, payload, key: cola.pop(0))
    r = ia_asistente.procesar_turno(usuario_id, "Quiero sugerir una mejora: exportar tareas a PDF")
    assert r["pendiente"] and r["pendiente"]["herramienta"] == "crear_tiquet", "no se crea hasta que la persona acepta"
    assert db.listar_tiquets() == []
    ia_asistente.confirmar_pendiente(usuario_id, True)
    assert [x["titulo"] for x in db.listar_tiquets()] == ["Exportar tareas a PDF"]


def test_el_chat_recuerda_la_pantalla_por_el_referer(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    uid = iniciar_sesion_de_prueba(cliente, "soporte-referer@ejemplo.com", "contrasena123")
    cliente.post("/ia/mensaje", json={"texto": ""}, headers={"Referer": "http://127.0.0.1:8000/correo/cuentas"})
    assert ia_soporte.pantalla_de(uid) == "correo.cuentas"
    cliente.post("/ia/mensaje", json={"texto": ""}, headers={"Referer": "http://127.0.0.1:8000/ia/"})
    assert ia_soporte.pantalla_de(uid) is None
