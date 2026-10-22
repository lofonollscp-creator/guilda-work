"""Herramientas MCP y del asistente de IA del trabajo con tareas (mcp_tools/herramientas_tareas_trabajo.py)."""
import pytest

import mcp_tools
from app import db, herramientas_grupos as hg, ia_herramientas as ih, tareas_trabajo as tt
from app.db_fiscal import crear_cliente_fiscal

LECTURA = ("listar_subtareas_tarea", "listar_clientes_de_tarea", "listar_tareas_de_cliente", "listar_adjuntos_tarea", "listar_revisiones_tarea", "informe_tareas", "listar_conversaciones_cliente_tarea", "listar_dependencias_tarea",
           "listar_reglas_automatizacion", "simular_regla_automatizacion", "listar_ejecuciones_automatizacion")
ESCRITURA = ("cambiar_estado_tarea_con_motivo", "crear_subtarea", "fijar_clientes_de_tarea", "pedir_revision_tarea", "resolver_revision_tarea", "ocultar_comentario_cliente_tarea", "anadir_dependencia_tarea", "quitar_dependencia_tarea")


def _equipo(nombre):
    t = db.crear_tenant(nombre)
    slug = nombre.lower().replace(" ", "")

    def u(sufijo, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(f"{slug}{sufijo}@ejemplo.com", f"k-{slug}{sufijo}")
        db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    return t, u("dir", True), u("ana"), u("beto")


def test_estan_clasificadas_en_su_grupo_y_en_el_mcp():
    for n in LECTURA:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False), n
    for n in ESCRITURA:
        assert n in ih.ESCRITURA and ih.necesita_confirmacion(n, modo_autonomo=False) and not ih.necesita_confirmacion(n, modo_autonomo=True), n
    for n in LECTURA + ESCRITURA:
        assert hg.grupo_de(n) == "tareas_avanzadas" and any(t.__name__ == n for t in mcp_tools.TOOLS), n
        assert n in {t["function"]["name"] for t in ih.HERRAMIENTAS}, n
        assert hg.es_lectura(n, ih.LECTURA) == (n in LECTURA), n                     # el perfil de solo lectura del MCP las separa igual
        assert (getattr(mcp_tools, n).__doc__ or "").strip().__len__() > 40, n


def test_los_perfiles_de_solo_lectura_no_ofrecen_las_de_escritura():
    nombres = {t.__name__ for t in mcp_tools.tools_filtradas(None, True)}
    assert set(LECTURA) <= nombres and not (set(ESCRITURA) & nombres)
    nombres_ia = {t["function"]["name"] for t in ih.herramientas_para(None, solo_lectura=True)}
    assert set(LECTURA) <= nombres_ia and not (set(ESCRITURA) & nombres_ia)


def test_las_palabras_clave_ofrecen_el_grupo():
    for frase in ("Dame el informe de tareas del último trimestre", "Pide la revisión de la tarea a Beto", "¿Qué automatizaciones tenemos?"):
        ofrecidas = {t["function"]["name"] for t in ih.herramientas_para([{"role": "user", "content": frase}])}
        assert "informe_tareas" in ofrecidas and "pedir_revision_tarea" in ofrecidas, frase


def test_estado_con_motivo_version_y_reglas_de_cierre():
    t, d, ana, beto = _equipo("Despacho herramientas tareas")
    tid = db.crear_tarea_outlook(ana, asunto="Declaración")
    with pytest.raises(ih.ErrorHerramientaIA, match="por qué la tarea queda bloqueada"):
        ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "esperando"})
    r = ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "esperando", "motivo": "Falta el certificado"})
    assert (r["estado"], r["motivo_bloqueo"]) == ("esperando", "Falta el certificado")
    with pytest.raises(ih.ErrorHerramientaIA, match="ha cambiado desde que la leíste"):
        ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "en_progreso", "version": 1})
    r = ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "en_progreso", "version": r["version"]})
    assert r["estado"] == "en_progreso" and r["motivo_bloqueo"] is None
    sub = ih.ejecutar(ana, "crear_subtarea", {"tarea_id": tid, "asunto": "Pedir el certificado"})
    assert ih.ejecutar(ana, "listar_subtareas_tarea", {"tarea_id": tid})["progreso"] == {"total": 1, "hechas": 0, "abiertas": 1}
    with pytest.raises(ih.ErrorHerramientaIA, match="subtareas sin completar"):
        ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "completada"})
    with pytest.raises(ih.ErrorHerramientaIA, match="solo se permite un nivel"):
        ih.ejecutar(ana, "crear_subtarea", {"tarea_id": sub["id"], "asunto": "Nieta"})
    ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": sub["id"], "estado": "completada"})
    assert ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "completada"})["estado"] == "completada"


def test_clientes_de_una_tarea_y_tareas_de_un_cliente():
    t, d, ana, beto = _equipo("Despacho herramientas clientes")
    c1, c2 = crear_cliente_fiscal(t, "Alfa SL"), crear_cliente_fiscal(t, "Beta SL")
    ajeno = crear_cliente_fiscal(db.crear_tenant("Otro despacho herr"), "Ajeno SL")
    tid = db.crear_tarea_outlook(ana, asunto="Vencida", fecha_vencimiento="2026-01-05")
    db.crear_tarea_outlook(ana, asunto="Al día", cliente_fiscal_id=c1)
    r = ih.ejecutar(ana, "fijar_clientes_de_tarea", {"tarea_id": tid, "cliente_ids": [c1, c2], "principal_id": c2})
    assert {c["id"] for c in r["clientes"]} == {c1, c2} and r["clientes"][0]["id"] == c2
    assert [c["id"] for c in ih.ejecutar(ana, "listar_clientes_de_tarea", {"tarea_id": tid})["clientes"]] == [c2, c1]
    with pytest.raises(ih.ErrorHerramientaIA, match="no existe o no es de tu despacho"):
        ih.ejecutar(ana, "fijar_clientes_de_tarea", {"tarea_id": tid, "cliente_ids": [c1, ajeno]})
    datos = ih.ejecutar(ana, "listar_tareas_de_cliente", {"cliente_fiscal_id": c1})
    assert {x["asunto"] for x in datos["tareas"]} == {"Vencida", "Al día"} and datos["contadores"]["abiertas"] == 2 and datos["contadores"]["vencidas"] == 1
    solo = ih.ejecutar(ana, "listar_tareas_de_cliente", {"cliente_fiscal_id": c1, "solo_vencidas": True})
    assert [x["asunto"] for x in solo["tareas"]] == ["Vencida"] and solo["contadores"]["total"] == 2
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe el cliente fiscal"):
        ih.ejecutar(ana, "listar_tareas_de_cliente", {"cliente_fiscal_id": ajeno})
    assert ih.ejecutar(beto, "listar_tareas_de_cliente", {"cliente_fiscal_id": c1})["tareas"] == []            # no ve las tareas privadas de otros


def test_revision_por_herramientas_y_permisos():
    t, d, ana, beto = _equipo("Despacho herramientas revision")
    tid = db.crear_tarea_outlook(ana, asunto="Para revisar")
    with pytest.raises(ih.ErrorHerramientaIA, match="otra persona"):
        ih.ejecutar(ana, "pedir_revision_tarea", {"tarea_id": tid, "revisor_id": ana})
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe la tarea"):
        ih.ejecutar(beto, "pedir_revision_tarea", {"tarea_id": tid, "revisor_id": d})                       # beto ni la ve
    r = ih.ejecutar(ana, "pedir_revision_tarea", {"tarea_id": tid, "revisor_id": beto, "nota": "Mira el IVA"})
    assert r["pendiente"]["revisor_id"] == beto
    with pytest.raises(ih.ErrorHerramientaIA, match="revisión pendiente"):
        ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "completada"})
    with pytest.raises(ih.ErrorHerramientaIA, match="Solo puede resolverla"):
        ih.ejecutar(ana, "resolver_revision_tarea", {"tarea_id": tid, "decision": "aprobar"})
    with pytest.raises(ih.ErrorHerramientaIA, match="Explica qué hay que cambiar"):
        ih.ejecutar(beto, "resolver_revision_tarea", {"tarea_id": tid, "decision": "cambios"})
    ih.ejecutar(beto, "resolver_revision_tarea", {"tarea_id": tid, "decision": "aprobar", "nota": "Bien"})
    h = ih.ejecutar(ana, "listar_revisiones_tarea", {"tarea_id": tid})
    assert h["pendiente"] is None and h["historial"][0]["estado"] == "aprobada"
    assert ih.ejecutar(ana, "cambiar_estado_tarea_con_motivo", {"tarea_id": tid, "estado": "completada"})["estado"] == "completada"


def test_adjuntos_solo_la_lista():
    t, d, ana, beto = _equipo("Despacho herramientas adjuntos")
    tid = db.crear_tarea_outlook(ana, asunto="Con archivo")
    tt.subir_adjunto(ana, tid, "justificante.pdf", b"%PDF contenido")
    lista = ih.ejecutar(ana, "listar_adjuntos_tarea", {"tarea_id": tid})
    assert [a["nombre_archivo"] for a in lista] == ["justificante.pdf"] and "contenido" not in lista[0]
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe la tarea"):
        ih.ejecutar(beto, "listar_adjuntos_tarea", {"tarea_id": tid})


def test_informe_por_herramienta_solo_ve_lo_suyo():
    t, d, ana, beto = _equipo("Despacho herramientas informe")
    db.crear_tarea_outlook(ana, asunto="Vencida", fecha_vencimiento="2026-01-05")
    db.crear_tarea_outlook(beto, asunto="De Beto", fecha_vencimiento="2026-01-05")
    r = ih.ejecutar(ana, "informe_tareas", {})
    assert r["ahora"]["abiertas"] == 1 and r["alcance"] == "tareas que la persona puede ver"
    with pytest.raises(ih.ErrorHerramientaIA, match="AAAA-MM-DD"):
        ih.ejecutar(ana, "informe_tareas", {"desde": "ayer"})
    with pytest.raises(ih.ErrorHerramientaIA, match="posterior"):
        ih.ejecutar(ana, "informe_tareas", {"desde": "2026-02-01", "hasta": "2026-01-01"})


def test_automatizaciones_solo_consulta_y_solo_la_direccion():
    from app import automatizaciones as au
    t, d, ana, beto = _equipo("Despacho herramientas auto")
    rid = au.crear_regla(t, d, "Vencidas", "tarea.vencida", {"dias_vencida": 1}, [{"tipo": "notificar", "titulo": "Vencida {asunto}", "a": "responsable"}])
    db.crear_tarea_outlook(ana, asunto="Vieja", fecha_vencimiento="2020-01-01")
    assert [r["id"] for r in ih.ejecutar(d, "listar_reglas_automatizacion", {})] == [rid]
    s = ih.ejecutar(d, "simular_regla_automatizacion", {"regla_id": rid})
    assert s["cumplen"] == 1 and s["nuevas"] == 1 and ih.ejecutar(d, "listar_ejecuciones_automatizacion", {}) == []     # simular no escribe
    au.ejecutar(t)
    assert [e["estado"] for e in ih.ejecutar(d, "listar_ejecuciones_automatizacion", {"estado": "ok"})] == ["ok"]
    for n, args in (("listar_reglas_automatizacion", {}), ("simular_regla_automatizacion", {"regla_id": rid}), ("listar_ejecuciones_automatizacion", {})):
        with pytest.raises(ih.ErrorHerramientaIA, match="Solo la dirección"):
            ih.ejecutar(ana, n, args)
    with pytest.raises(ih.ErrorHerramientaIA, match="Regla no encontrada"):
        ih.ejecutar(d, "simular_regla_automatizacion", {"regla_id": 99999})
    otro, d2, _, _ = _equipo("Despacho herramientas auto dos")
    assert ih.ejecutar(d2, "listar_reglas_automatizacion", {}) == []                                               # reglas de otro despacho, invisibles
    with pytest.raises(ih.ErrorHerramientaIA, match="Regla no encontrada"):
        ih.ejecutar(d2, "simular_regla_automatizacion", {"regla_id": rid})


def test_ninguna_herramienta_toca_lo_que_ve_el_cliente_ni_crea_reglas():
    nombres = {t.__name__ for t in mcp_tools.TOOLS}
    assert not ({"fijar_visible_cliente_de_la_tarea", "crear_regla_automatizacion", "cambiar_regla_automatizacion", "borrar_regla_automatizacion"} & nombres)
    assert not any("visible_cliente" in n or n.startswith(("crear_regla_auto", "borrar_regla_auto")) for n in nombres)


# --- Dependencias entre tareas -----------------------------------------------------------------------------------------------

def test_herramientas_de_dependencias_entre_tareas():
    t, d, ana, beto = _equipo("Despacho dependencias herramientas")
    a, b, c = (db.crear_tarea_outlook(ana, asunto=n) for n in ("Primera", "Segunda", "Tercera"))
    ajena = db.crear_tarea_outlook(beto, asunto="Privada de Beto")
    r = ih.ejecutar(ana, "anadir_dependencia_tarea", {"tarea_id": b, "depende_de_id": a})
    assert r["bloqueada"] is True and [x["id"] for x in r["depende_de"]] == [a]
    assert ih.ejecutar(ana, "listar_dependencias_tarea", {"tarea_id": b})["bloqueada"] is True
    ih.ejecutar(ana, "anadir_dependencia_tarea", {"tarea_id": c, "depende_de_id": b})
    for args, texto in (({"tarea_id": a, "depende_de_id": a}, "a sí misma"), ({"tarea_id": a, "depende_de_id": c}, "ciclo"), ({"tarea_id": b, "depende_de_id": ajena}, "no puedes verla")):
        with pytest.raises(ih.ErrorHerramientaIA, match=texto):
            ih.ejecutar(ana, "anadir_dependencia_tarea", args)
    with pytest.raises(ih.ErrorHerramientaIA, match="no puedes verla"):
        ih.ejecutar(beto, "listar_dependencias_tarea", {"tarea_id": b})                               # otra persona sin acceso a la tarea
    db.completar_tarea_outlook(ana, a)
    assert ih.ejecutar(ana, "listar_dependencias_tarea", {"tarea_id": b})["bloqueada"] is False
    r = ih.ejecutar(ana, "quitar_dependencia_tarea", {"tarea_id": c, "depende_de_id": b})
    assert r["depende_de"] == [] and r["bloqueada"] is False
    with pytest.raises(ih.ErrorHerramientaIA, match="no esperaba"):
        ih.ejecutar(ana, "quitar_dependencia_tarea", {"tarea_id": c, "depende_de_id": b})
