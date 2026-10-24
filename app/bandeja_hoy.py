"""«Hoy»: todo lo que necesita a una persona en un solo sitio, venga del módulo que venga (tareas, plazos, vencimientos fiscales, visitas, mensajes de clientes, correos sin contestar, ausencias por
aprobar, traspasos y certificados). Reúne lo que cada módulo ya calcula, sin duplicar sus reglas, y lo presenta por urgencia. Solo lectura; cada elemento lleva el enlace a donde se resuelve."""
from __future__ import annotations

from datetime import date, timedelta

from flask import url_for
from flask_babel import gettext as _, ngettext

from . import ausencias, certificados, db, facturacion_despacho, facturas_contables, mensajes_enlace, nucleo, resumen_pendientes, traspasos, verticales

DIAS_CERCANO = 7                 # «próximo»: lo que vence en la próxima semana
DIAS_CERTIFICADO = 30
DIAS_FACTURA_ANTIGUA = 5       # una factura de cliente que lleva tantos días sin revisar ya es urgente
MAX_POR_SECCION = 25
ORDEN_URGENCIA = {"vencido": 0, "hoy": 1, "proximo": 2, "info": 3}


def _urgencia(fecha: str | None, hoy: date) -> str:
    if not fecha:
        return "info"
    d = (fecha or "")[:10]
    return "vencido" if d < hoy.isoformat() else ("hoy" if d == hoy.isoformat() else ("proximo" if d <= (hoy + timedelta(days=DIAS_CERCANO)).isoformat() else "info"))


# Qué se puede hacer con un elemento desde la app móvil sin abrir la web (cada acción es una operación que ya existe en la API). `abrir` siempre.
ACCIONES = {"tarea": ["abrir", "completar"], "vencimiento": ["abrir", "presentar"], "traspaso": ["abrir", "aceptar", "rechazar"]}


def _destino(tipo: str, id_: int | None, **extra) -> dict:
    """A dónde lleva el elemento, sin URLs de la web: `{tipo, id, ...}`. La app móvil navega por esto (docs/plan-app-movil.md, S-01)."""
    return {"tipo": tipo, "id": id_, **{k: v for k, v in extra.items() if v is not None}}


def _item(titulo: str, url: str, urgencia: str, detalle: str | None = None, fecha: str | None = None, destino: dict | None = None) -> dict:
    item = {"titulo": titulo, "detalle": detalle, "url": url, "urgencia": urgencia, "fecha": (fecha or "")[:16]}
    if destino is not None:
        item["destino"] = destino
        item["acciones"] = ACCIONES.get(destino["tipo"], ["abrir"])
    return item


def _seccion(clave: str, titulo: str, items: list[dict]) -> dict | None:
    if not items:
        return None
    items = sorted(items, key=lambda i: (ORDEN_URGENCIA[i["urgencia"]], i["fecha"] or "9999"))
    return {"clave": clave, "titulo": titulo, "elementos": items[:MAX_POR_SECCION], "total": len(items),
            "urgentes": sum(1 for i in items if i["urgencia"] in ("vencido", "hoy"))}


def reunir(usuario_id: int, supervisor: bool = False, hoy: date | None = None, tenant_id: int | None = None) -> dict:
    """`{secciones: [...], total, urgentes, destacados}`; cada sección ya viene ordenada por urgencia y las vacías no aparecen. `destacados` son los elementos más urgentes de todas (para el inicio)."""
    hoy = hoy or date.today()
    iso = hoy.isoformat()
    # `tenant_id`: el despacho activo de la petición (una persona en varios despachos puede mirar el que haya elegido); sin él, el principal.
    if tenant_id is not None:
        tid = tenant_id
    else:
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
            tareas.append(_item(t["asunto"], url_for("tareas.ver", tarea_id=t["id"]), urg, None if clave != "asignadas" else _("Asignada a ti"), t["fecha_vencimiento"],
                               destino=_destino("tarea", t["id"])))
    secciones.append(_seccion("tareas", _("Tareas"), tareas))

    secciones.append(_seccion("correo", _("Correos sin contestar"), [
        _item(c["asunto"] or _("(sin asunto)"), url_for("correo.ver_mensaje", mensaje_id=c["id"]), "hoy" if c["importante"] else "info", c["remitente"], c["fecha"],
              destino=_destino("correo", c["id"]))
        for c in resumen_pendientes.correos_sin_contestar(usuario_id, hoy)]))

    if tid is not None:
        activos = verticales.activos_de(tid)
        hasta = (hoy + timedelta(days=DIAS_CERCANO)).isoformat()
        if activos:
            plazos = []
            for z in nucleo.listar_plazos(tid, usuario_id, supervisor, estado="abiertos", responsable_id=usuario_id, hasta=hasta, hoy=hoy):
                destino = url_for("expedientes.ficha", expediente_id=z["expediente_id"]) if z["expediente_id"] else (url_for("clientes.ficha", cliente_id=z["cliente_id"]) if z["cliente_id"] else url_for("plazos.lista"))
                plazos.append(_item(z["titulo"], destino, _urgencia(z["fecha_limite"], hoy), z["cliente_nombre"] or z["expediente_titulo"], z["fecha_limite"],
                                    destino=_destino("plazo", z["id"], expediente_id=z["expediente_id"], cliente_id=z["cliente_id"])))
            secciones.append(_seccion("plazos", _("Plazos"), plazos))
            mensajes = []
            for m in mensajes_enlace.pendientes_del_equipo(tid, usuario_id, supervisor):
                quien = m["nombre"] or (_("el propietario") if m["vertical"] == "inmobiliaria" else _("el cliente"))
                mensajes.append(_item(ngettext("%(n)s mensaje sin leer de %(quien)s", "%(n)s mensajes sin leer de %(quien)s", m["n"], n=m["n"], quien=quien),
                                      url_for("expedientes.ficha", expediente_id=m["expediente_id"]), "hoy", m["titulo"] or m["cliente"], m["ultimo"],
                                      destino=_destino("expediente", m["expediente_id"])))
            secciones.append(_seccion("mensajes", _("Mensajes de clientes"), mensajes))
        if "inmobiliaria" in activos:
            from . import inmobiliaria
            visitas = [_item(f"{(v['fecha_hora'] or '')[11:16]} · {v['direccion']}", url_for("inmobiliaria.panel"), "hoy", v["visitante_nombre"], v["fecha_hora"],
                             destino=_destino("visita", v["id"]))
                       for v in inmobiliaria.listar_visitas(tid, usuario_id, supervisor, agente_id=usuario_id, desde=iso, hasta=iso, estado="prevista")]
            secciones.append(_seccion("visitas", _("Visitas de hoy"), visitas))

        venc = []
        for estado in ("pendiente", "fuera_plazo"):
            for v in db.listar_vencimientos_fiscales(tid, estado=estado, hasta=hasta):
                if v["usuario_id"] == usuario_id or (supervisor and v["fecha_limite"][:10] < iso):
                    venc.append(_item(f"{v['modelo']} · {v['cliente_nombre']}", url_for("fiscal.ficha_cliente", cliente_id=v["cliente_fiscal_id"]), _urgencia(v["fecha_limite"], hoy),
                                      None if v["usuario_id"] == usuario_id else _("Vencido, de otra persona"), v["fecha_limite"],
                                      destino=_destino("vencimiento", v["id"], cliente_fiscal_id=v["cliente_fiscal_id"])))
        secciones.append(_seccion("vencimientos", _("Vencimientos fiscales"), venc))

        pendientes_traspaso = [t for t in traspasos.listar(tid, usuario_id, estado="pendiente") if t["a_usuario_id"] == usuario_id]
        secciones.append(_seccion("traspasos", _("Clientes que te quieren pasar"), [
            _item(t["cliente"], url_for("control_fiscal.traspasos_pantalla"), "hoy", _("De %(quien)s", quien=t.get("de_nombre") or "—"), t.get("creado_en"),
                  destino=_destino("traspaso", t["id"])) for t in pendientes_traspaso]))

        if ausencias.puede_gestionar(usuario_id, tid):
            secciones.append(_seccion("ausencias", _("Ausencias por aprobar"), [
                _item(f"{a['persona']}", url_for("fichaje.ausencias_equipo"), "hoy", f"{a['desde']} → {a['hasta']}", a["desde"], destino=_destino("ausencia", a["id"])) for a in ausencias.listar(tid, estado="pendiente")]))

        impagos = []
        for f in facturacion_despacho.vencidas_sin_cobrar(tid, usuario_id, supervisor):
            destino = url_for("expedientes.ficha", expediente_id=f["expediente_id"]) + "#facturacion" if f["expediente_id"] else (url_for("clientes.ficha", cliente_id=f["cliente_id"], pestana="fiscal") if f["cliente_id"] else url_for("clientes.lista"))
            impagos.append(_item(_("Factura %(codigo)s sin cobrar", codigo=f["codigo"]), destino, "vencido", f"{f['cliente'] or ''} · {f['total']} €".strip(" ·"), f["fecha"],
                            destino=_destino("factura", f.get("idfactura"), expediente_id=f.get("expediente_id"), cliente_id=f.get("cliente_id"))))
        secciones.append(_seccion("facturas", _("Facturas vencidas sin cobrar"), impagos))

        if "contabilizacion" in activos:
            limite_antiguas = (hoy - timedelta(days=DIAS_FACTURA_ANTIGUA)).isoformat()
            facturas_cli = []
            for c in facturas_contables.pendientes_por_cliente(tid, usuario_id):
                partes = []
                if c["pendientes"]:
                    partes.append(_("Por revisar: %(n)s", n=c["pendientes"]))
                if c["por_leer"]:
                    partes.append(_("Por leer: %(n)s", n=c["por_leer"]))
                if c["revisadas"]:
                    partes.append(_("Para exportar: %(n)s", n=c["revisadas"]))
                urgente = bool(c["del_portal"]) or bool(c["antigua"] and c["antigua"][:10] <= limite_antiguas)
                facturas_cli.append(_item(c["nombre"], url_for("contabilidad.lista", cliente_id=c["cliente_fiscal_id"]), "hoy" if urgente else "info", " · ".join(partes), c["antigua"],
                                      destino=_destino("contabilizacion", c["cliente_fiscal_id"])))
            secciones.append(_seccion("contabilizacion", _("Facturas de clientes"), facturas_cli))

        if certificados.puede_gestionar(usuario_id, tid):
            cert = []
            for plazo, urg in (("caducados", "vencido"), ("mes", "proximo")):
                for c in certificados.listar(tid, plazo=plazo):
                    cert.append(_item(c.get("nombre_comun") or _("Certificado"), url_for("certificados.detalle", certificado_id=c["id"]), urg,
                                      c.get("cliente_nombre") or c.get("titular"), c.get("caduca_el"), destino=_destino("certificado", c["id"])))
            secciones.append(_seccion("certificados", _("Certificados que caducan"), cert))

    secciones = [s for s in secciones if s]
    todos = sorted((dict(i, seccion=s["titulo"], clave=s["clave"]) for s in secciones for i in s["elementos"]), key=lambda i: (ORDEN_URGENCIA[i["urgencia"]], i["fecha"] or "9999"))
    return {"secciones": secciones, "total": sum(s["total"] for s in secciones), "urgentes": sum(s["urgentes"] for s in secciones), "destacados": todos[:30]}
