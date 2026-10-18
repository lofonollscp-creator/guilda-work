"""«Hoy»: todo lo que necesita a una persona en un solo sitio, venga del módulo que venga (tareas, plazos, vencimientos fiscales, visitas, mensajes de clientes, correos sin contestar, ausencias por
aprobar, traspasos y certificados). Reúne lo que cada módulo ya calcula, sin duplicar sus reglas, y lo presenta por urgencia. Solo lectura; cada elemento lleva el enlace a donde se resuelve."""
from __future__ import annotations

from datetime import date, timedelta

from flask import url_for
from flask_babel import gettext as _, ngettext

from . import ausencias, certificados, db, mensajes_enlace, nucleo, resumen_pendientes, traspasos, verticales

DIAS_CERCANO = 7                 # «próximo»: lo que vence en la próxima semana
DIAS_CERTIFICADO = 30
MAX_POR_SECCION = 25
ORDEN_URGENCIA = {"vencido": 0, "hoy": 1, "proximo": 2, "info": 3}


def _urgencia(fecha: str | None, hoy: date) -> str:
    if not fecha:
        return "info"
    d = (fecha or "")[:10]
    return "vencido" if d < hoy.isoformat() else ("hoy" if d == hoy.isoformat() else ("proximo" if d <= (hoy + timedelta(days=DIAS_CERCANO)).isoformat() else "info"))


def _item(titulo: str, url: str, urgencia: str, detalle: str | None = None, fecha: str | None = None) -> dict:
    return {"titulo": titulo, "detalle": detalle, "url": url, "urgencia": urgencia, "fecha": (fecha or "")[:16]}


def _seccion(clave: str, titulo: str, items: list[dict]) -> dict | None:
    if not items:
        return None
    items = sorted(items, key=lambda i: (ORDEN_URGENCIA[i["urgencia"]], i["fecha"] or "9999"))
    return {"clave": clave, "titulo": titulo, "elementos": items[:MAX_POR_SECCION], "total": len(items),
            "urgentes": sum(1 for i in items if i["urgencia"] in ("vencido", "hoy"))}


def reunir(usuario_id: int, supervisor: bool = False, hoy: date | None = None) -> dict:
    """`{secciones: [...], total, urgentes, destacados}`; cada sección ya viene ordenada por urgencia y las vacías no aparecen. `destacados` son los elementos más urgentes de todas (para el inicio)."""
    hoy = hoy or date.today()
    iso = hoy.isoformat()
    tenant = db.tenant_de_usuario(usuario_id)
    tid = tenant["id"] if tenant else None
    secciones: list[dict | None] = []

    mi_dia = db.tareas_para_hoy(usuario_id)
    tareas = []
    vistas = set()
    for clave in ("vencidas", "hoy", "asignadas"):
        for t in mi_dia[clave]:
            if t["id"] in vistas:
                continue
            vistas.add(t["id"])
            urg = "vencido" if clave == "vencidas" else ("hoy" if clave == "hoy" else "info")
            tareas.append(_item(t["asunto"], url_for("tareas.ver", tarea_id=t["id"]), urg, None if clave != "asignadas" else _("Asignada a ti"), t["fecha_vencimiento"]))
    secciones.append(_seccion("tareas", _("Tareas"), tareas))

    secciones.append(_seccion("correo", _("Correos sin contestar"), [
        _item(c["asunto"] or _("(sin asunto)"), url_for("correo.ver_mensaje", mensaje_id=c["id"]), "hoy" if c["importante"] else "info", c["remitente"], c["fecha"])
        for c in resumen_pendientes.correos_sin_contestar(usuario_id, hoy)]))

    if tid is not None:
        activos = verticales.activos_de(tid)
        hasta = (hoy + timedelta(days=DIAS_CERCANO)).isoformat()
        if activos:
            plazos = []
            for z in nucleo.listar_plazos(tid, usuario_id, supervisor, estado="abiertos", responsable_id=usuario_id, hasta=hasta, hoy=hoy):
                destino = url_for("expedientes.ficha", expediente_id=z["expediente_id"]) if z["expediente_id"] else (url_for("clientes.ficha", cliente_id=z["cliente_id"]) if z["cliente_id"] else url_for("plazos.lista"))
                plazos.append(_item(z["titulo"], destino, _urgencia(z["fecha_limite"], hoy), z["cliente_nombre"] or z["expediente_titulo"], z["fecha_limite"]))
            secciones.append(_seccion("plazos", _("Plazos"), plazos))
            mensajes = []
            for m in mensajes_enlace.pendientes_del_equipo(tid, usuario_id, supervisor):
                quien = m["nombre"] or (_("el propietario") if m["vertical"] == "inmobiliaria" else _("el cliente"))
                mensajes.append(_item(ngettext("%(n)s mensaje sin leer de %(quien)s", "%(n)s mensajes sin leer de %(quien)s", m["n"], n=m["n"], quien=quien),
                                      url_for("expedientes.ficha", expediente_id=m["expediente_id"]), "hoy", m["titulo"] or m["cliente"], m["ultimo"]))
            secciones.append(_seccion("mensajes", _("Mensajes de clientes"), mensajes))
        if "inmobiliaria" in activos:
            from . import inmobiliaria
            visitas = [_item(f"{(v['fecha_hora'] or '')[11:16]} · {v['direccion']}", url_for("inmobiliaria.panel"), "hoy", v["visitante_nombre"], v["fecha_hora"])
                       for v in inmobiliaria.listar_visitas(tid, usuario_id, supervisor, agente_id=usuario_id, desde=iso, hasta=iso, estado="prevista")]
            secciones.append(_seccion("visitas", _("Visitas de hoy"), visitas))

        venc = []
        for estado in ("pendiente", "fuera_plazo"):
            for v in db.listar_vencimientos_fiscales(tid, estado=estado, hasta=hasta):
                if v["usuario_id"] == usuario_id or (supervisor and v["fecha_limite"][:10] < iso):
                    venc.append(_item(f"{v['modelo']} · {v['cliente_nombre']}", url_for("fiscal.ficha_cliente", cliente_id=v["cliente_fiscal_id"]), _urgencia(v["fecha_limite"], hoy),
                                      None if v["usuario_id"] == usuario_id else _("Vencido, de otra persona"), v["fecha_limite"]))
        secciones.append(_seccion("vencimientos", _("Vencimientos fiscales"), venc))

        pendientes_traspaso = [t for t in traspasos.listar(tid, usuario_id, estado="pendiente") if t["a_usuario_id"] == usuario_id]
        secciones.append(_seccion("traspasos", _("Clientes que te quieren pasar"), [
            _item(t["cliente"], url_for("control_fiscal.traspasos_pantalla"), "hoy", _("De %(quien)s", quien=t.get("de_nombre") or "—"), t.get("creado_en")) for t in pendientes_traspaso]))

        if ausencias.puede_gestionar(usuario_id, tid):
            secciones.append(_seccion("ausencias", _("Ausencias por aprobar"), [
                _item(f"{a['persona']}", url_for("fichaje.ausencias_equipo"), "hoy", f"{a['desde']} → {a['hasta']}", a["desde"]) for a in ausencias.listar(tid, estado="pendiente")]))

        if certificados.puede_gestionar(usuario_id, tid):
            cert = []
            for plazo, urg in (("caducados", "vencido"), ("mes", "proximo")):
                for c in certificados.listar(tid, plazo=plazo):
                    cert.append(_item(c.get("nombre_comun") or _("Certificado"), url_for("certificados.detalle", certificado_id=c["id"]), urg,
                                      c.get("cliente_nombre") or c.get("titular"), c.get("caduca_el")))
            secciones.append(_seccion("certificados", _("Certificados que caducan"), cert))

    secciones = [s for s in secciones if s]
    todos = sorted((dict(i, seccion=s["titulo"], clave=s["clave"]) for s in secciones for i in s["elementos"]), key=lambda i: (ORDEN_URGENCIA[i["urgencia"]], i["fecha"] or "9999"))
    return {"secciones": secciones, "total": sum(s["total"] for s in secciones), "urgentes": sum(s["urgentes"] for s in secciones), "destacados": todos[:30]}
