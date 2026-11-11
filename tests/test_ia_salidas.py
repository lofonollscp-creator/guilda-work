"""Contador de datos que salen a proveedores de IA externos (W9): se anota cuántos, nunca qué, y lo local no cuenta."""
import json
from datetime import datetime, timedelta

from app import db, ia_asistente, ia_salidas


def _t():
    t = db.crear_tenant("Salidas IA")
    u = db.crear_usuario_vinculado_a_kratos("salidas@ejemplo.com", "k-salidas")
    db.asignar_tenant(u, t)
    return t, u


def test_se_anotan_los_datos_enmascarados_por_tipo_y_los_adjuntos_pero_no_el_contenido():
    t, u = _t()
    ia_salidas.preparar({"NIF": 2, "IBAN": 1}, [{"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "file", "file": {}}, {"type": "image_url", "image_url": {}}]}])
    ia_salidas.anotar(t, "openai", "gpt-4o-mini", "facturas", "global")
    ia_salidas.preparar({"PERSONA": 1}, [{"role": "user", "content": "solo texto"}])
    ia_salidas.anotar(t, "openai", "gpt-4o-mini", "asistente", "global")
    r = ia_salidas.resumen(t)
    assert r["consultas"] == 2 and r["con_adjuntos"] == 1 and r["enmascarados"] == {"IBAN": 1, "NIF": 2, "PERSONA": 1}
    assert r["por_proveedor"] == [{"proveedor": "openai", "consultas": 2, "adjuntos": 1}]
    conn = db.get_connection()
    crudo = " ".join(str(v) for fila in conn.execute("SELECT * FROM ia_salidas_datos").fetchall() for v in tuple(fila))
    conn.close()
    assert "solo texto" not in crudo and "file" not in json.dumps(crudo)                                      # nada del contenido


def test_un_proveedor_local_no_cuenta_y_otro_despacho_no_lo_ve():
    t, u = _t()
    t2 = db.crear_tenant("Salidas IA otro")
    ia_salidas.preparar({"NIF": 5}, [])
    ia_salidas.anotar(t, "ollama", "llama3", "asistente", "local")
    assert ia_salidas.resumen(t)["consultas"] == 0
    ia_salidas.preparar({}, [])
    ia_salidas.anotar(t, "anthropic", "claude", "asistente", "global")
    assert ia_salidas.resumen(t)["consultas"] == 1 and ia_salidas.resumen(t2)["consultas"] == 0
    ia_salidas.anotar(None, "anthropic", "claude", "asistente", "global")                                   # sin despacho (usuario local): no rompe
    ia_salidas.anotar(t, "anthropic", "claude", "asistente", "global")                                      # sin preparar: cuenta la salida con ceros
    assert ia_salidas.resumen(t)["consultas"] == 2


def test_lo_viejo_se_purga_y_lo_reciente_se_queda():
    t, u = _t()
    ia_salidas.preparar({}, []); ia_salidas.anotar(t, "openai", "m", "asistente", "global")
    conn = db.get_connection()
    conn.execute("INSERT INTO ia_salidas_datos (tenant_id, proveedor, creado_en) VALUES (?, 'openai', ?)", (t, (datetime.now() - timedelta(days=500)).isoformat(timespec="seconds")))
    conn.commit(); conn.close()
    assert ia_salidas.purgar() == 1 and ia_salidas.resumen(t, dias=900)["consultas"] == 1


def test_una_consulta_real_al_asistente_deja_su_anotacion(monkeypatch):
    t, u = _t()
    monkeypatch.setattr(ia_asistente, "candidatos", lambda uid, tarea: [{"proveedor": "openai", "modelo": "gpt-4o-mini", "claves": ["k"], "url_base": None, "origen": "despacho"}])
    monkeypatch.setattr(ia_asistente, "_reservar_uso", lambda uid: None)
    monkeypatch.setattr(ia_asistente.ia_proveedores, "llamar", lambda *a, **k: {"choices": [{"message": {"content": "ok"}}], "usage": {}})
    def proteger(self, mensajes):                                                                         # el detector real (≈300 MB) está apagado en las pruebas: se simula que vio un NIF y un IBAN
        self.protegidos.update({"NIF": 1, "IBAN": 1})
        return mensajes
    monkeypatch.setattr(ia_asistente.anonimizar.Seudonimizador, "proteger_mensajes", proteger)
    ia_asistente.completar_texto(u, "sistema", "contenido")
    r = ia_salidas.resumen(t)
    assert r["consultas"] == 1 and r["enmascarados"] == {"IBAN": 1, "NIF": 1} and r["por_proveedor"][0]["proveedor"] == "openai"


def test_la_latencia_y_los_errores_por_proveedor_se_miden_y_se_pasa_al_siguiente(monkeypatch):
    from app import ia_uso
    from app.ia_errores import ErrorIA
    t, u = _t()
    monkeypatch.setattr(ia_asistente, "candidatos", lambda uid, tarea: [
        {"proveedor": "openai", "modelo": "gpt-4o-mini", "claves": ["k"], "url_base": None, "origen": "despacho"},
        {"proveedor": "anthropic", "modelo": "claude", "claves": ["k"], "url_base": None, "origen": "despacho"}])
    monkeypatch.setattr(ia_asistente, "_reservar_uso", lambda uid: None)

    def llamar(proveedor, modelo, payload, clave, url_base=None, timeout=90):
        if proveedor == "openai":
            raise ErrorIA("proveedor caído", codigo_http=503)
        return {"choices": [{"message": {"content": "respuesta del segundo"}}], "usage": {}}
    monkeypatch.setattr(ia_asistente.ia_proveedores, "llamar", llamar)
    assert ia_asistente.completar_texto(u, "s", "c") == "respuesta del segundo"                                # el primero cae y contesta el segundo
    r = {f["proveedor"]: f for f in ia_uso.resumen(t)["filas"]}
    assert r["openai"]["errores"] == 1 and r["openai"]["llamadas"] == 0 and r["openai"]["latencia_ms"] is None
    assert r["anthropic"]["llamadas"] == 1 and r["anthropic"]["errores"] == 0 and r["anthropic"]["latencia_ms"] is not None
    assert ia_uso.resumen(t)["total_errores"] == 1


def test_la_pantalla_de_ajustes_enseña_los_datos_enviados_solo_a_la_direccion(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    u = iniciar_sesion_de_prueba(cliente, "salidas-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Salidas web")
    db.asignar_tenant(u, t)
    ia_salidas.preparar({"NIF": 3}, [{"role": "user", "content": [{"type": "file", "file": {}}]}])
    ia_salidas.anotar(t, "openai", "gpt-4o-mini", "facturas", "global")
    assert "Datos que han salido a proveedores externos" not in cliente.get("/ia/ajustes").get_data(as_text=True)        # quien no dirige no lo ve
    db.asignar_supervisor_tenant(u, True)
    html = cliente.get("/ia/ajustes").get_data(as_text=True)
    assert "1 consulta salió a un proveedor externo." in html and "3 nif" in html and "no se pueden enmascarar" in html
