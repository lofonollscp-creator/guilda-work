"""Ficha única del cliente (`/clientes/<id>`): una sola pantalla con pestañas en lugar de dos fichas paralelas (la del núcleo y la fiscal).

Pestañas: **Resumen** (datos, contactos, expedientes, plazos, horas), **Fiscal** (vencimientos, facturación, cita, contactos de EspoCRM, accesos), **Tareas**, **Documentos** (los del
cliente, el expediente fiscal y los que sube él desde el portal) y **Mensajes** (portal y correos). Fiscal, Tareas y Mensajes solo existen si el cliente lleva gestión fiscal
(`clientes_fiscales.cliente_id`, ver app/alta_cliente.py). Solo se calcula lo que enseña la pestaña abierta: las llamadas a FacturaScripts, EspoCRM o Cal.com
(best-effort, un fallo nunca rompe la ficha) solo se hacen al abrir Fiscal.

La ruta antigua `/fiscal/clientes/<id>` redirige aquí (app/rutas_fiscal.py:ficha_cliente) para que todos los enlaces existentes sigan funcionando."""
from __future__ import annotations

from datetime import date, timedelta

from flask import url_for

from . import almacen_documentos, calcom, db, espocrm, facturacion_despacho, facturascripts, perfil_fiscal
from .vencimientos_fiscales import modelos_disponibles

PESTANAS = ("resumen", "fiscal", "laboral", "tareas", "documentos", "mensajes")


def pestanas_disponibles(cliente_fiscal_id: int | None) -> list[str]:
    return list(PESTANAS) if cliente_fiscal_id else ["resumen", "documentos"]


def pestana_valida(pedida: str | None, cliente_fiscal_id: int | None) -> str:
    return pedida if pedida in pestanas_disponibles(cliente_fiscal_id) else "resumen"


def semaforo(vencimientos) -> dict:
    """Estado fiscal del cliente de un vistazo (el mismo cálculo del listado de Fiscal)."""
    return perfil_fiscal.semaforo([{"estado": v["estado"], "fecha_limite": v["fecha_limite"]} for v in vencimientos], date.today())


def url_pestana(tenant_id: int, cliente_fiscal_id: int, pestana: str, ancla: str = "", **consulta) -> str:
    """La pestaña de la ficha única de un cliente fiscal (para redirigir tras una acción hecha desde una ruta de Fiscal)."""
    f = db.obtener_cliente_fiscal(tenant_id, cliente_fiscal_id)
    if f is None or f["cliente_id"] is None:
        return url_for("fiscal.ficha_cliente", cliente_id=cliente_fiscal_id, pestana=pestana, **consulta) + ancla
    return url_for("clientes.ficha", cliente_id=f["cliente_id"], pestana=pestana, **consulta) + ancla


def url_documentos(tenant_id: int, cliente_fiscal_id: int) -> str:
    """Dónde cae quien acaba de subir o archivar un documento en el expediente del cliente (pestaña Documentos de la ficha única)."""
    return url_pestana(tenant_id, cliente_fiscal_id, "documentos", "#expediente")


def contexto_fiscal(tenant_id: int, usuario_id: int, cliente, vencimientos) -> dict:
    """La pestaña Fiscal. `cliente` es la fila de `clientes_fiscales`."""
    from .rutas_fiscal import ETIQUETAS_ACCESO
    facturas = []
    if cliente["facturascripts_cliente_codigo"]:
        tenant = db.obtener_tenant(tenant_id)
        try:
            facturas = facturascripts.listar_facturas(tenant["facturascripts_url"], tenant["facturascripts_api_key"], cliente_codigo=cliente["facturascripts_cliente_codigo"], limite=10)
        except facturascripts.ErrorFacturaScripts:
            facturas = []
    contactos_espocrm = []
    if cliente["espocrm_cuenta_id"]:
        try:
            contactos_espocrm = espocrm.listar_contactos_de_cuenta(cliente["espocrm_cuenta_id"])
        except espocrm.ErrorEspoCRM:
            contactos_espocrm = []
    # Cal.diy no tiene «cliente»: se correlaciona por el email de la ficha contra el asistente de cada reserva próxima del despacho.
    proxima_cita = None
    if cliente["email"]:
        tenant_calcom = db.obtener_tenant(tenant_id)
        api_key = tenant_calcom["calcom_api_key"] if tenant_calcom else None
        if api_key:
            try:
                for r in calcom.listar_reservas(api_key, desde=date.today().isoformat()):
                    if any(a.get("email", "").lower() == cliente["email"].lower() for a in r.get("attendees", [])):
                        proxima_cita = r
                        break
            except calcom.ErrorCalcom:
                proxima_cita = None
    supervisor = db.es_supervisor_tenant(usuario_id)
    return {
        "fiscal": cliente, "vencimientos": vencimientos, "modelos_cliente": db.modelos_fiscales_de_cliente(cliente), "modelos_disponibles": modelos_disponibles(cliente["pais"]),
        "hoy": date.today().isoformat(), "limite_proximo": (date.today() + timedelta(days=7)).isoformat(),
        "facturas": facturas, "cobro": facturacion_despacho.cobro_de_cliente(tenant_id, cliente), "contactos_espocrm": contactos_espocrm, "proxima_cita": proxima_cita,
        "accesos": db.listar_accesos_cliente(tenant_id, cliente["id"], 50) if supervisor else None,
        "acciones_acceso": {k: str(v) for k, v in ETIQUETAS_ACCESO.items()},
    }


def contexto_documentos(tenant_id: int, usuario_id: int, c, cliente_fiscal, vencimientos) -> dict:
    """Los documentos del cliente (almacén del núcleo) y, con gestión fiscal, el expediente fiscal y lo que ha subido él por el portal."""
    ctx = {"documentos": almacen_documentos.listar(tenant_id, usuario_id, cliente_id=c["id"]), "expediente": None, "documentos_totales": []}
    if cliente_fiscal is not None:
        ctx["expediente"] = almacen_documentos.listar_de_cliente_fiscal(tenant_id, cliente_fiscal["id"])
        ctx["categorias_documento"] = db.CATEGORIAS_DOCUMENTO
        ctx["soy_supervisor"] = db.es_supervisor_tenant(usuario_id)
        for v in vencimientos:
            for d in db.listar_documentos_vencimiento(v["id"]):
                ctx["documentos_totales"].append({**dict(d), "vencimiento": v})
    return ctx


def contexto_mensajes(cliente_fiscal, vencimientos) -> dict:
    """Mensajes del portal (de todos sus vencimientos, el más reciente primero) y correos vinculados a mano desde Correo."""
    mensajes = []
    for v in vencimientos:
        for m in db.listar_mensajes_vencimiento(v["id"]):
            mensajes.append({**dict(m), "vencimiento": v})
    mensajes.sort(key=lambda m: m["creado_en"], reverse=True)
    return {"mensajes_totales": mensajes, "correos_relacionados": db.listar_correos_de_cliente_fiscal(cliente_fiscal["id"])}


def contexto_laboral(tenant_id: int, usuario_id: int, cliente_fiscal) -> dict:
    """Los trabajadores del cliente (ver app/laboral.py); quien solo es auditor los ve pero no los toca."""
    from . import acceso, laboral, reglas_laborales
    trabajadores = laboral.listar(tenant_id, cliente_fiscal["id"])
    nominas = laboral.config(tenant_id)
    return {"nominas_config": nominas, "nominas": laboral.seguimiento_nominas(tenant_id, cliente_fiscal["id"], laboral.periodo_actual()), "estados_nomina": laboral.ESTADOS_NOMINA,
            "es_directivo": acceso.es_directivo(usuario_id),
            "reglas_laborales_aprobadas": bool({"tc", "m190"} & reglas_laborales.vigentes().keys() or nominas["activo"]), "trabajadores": trabajadores, "trabajadores_activos": sum(1 for t in trabajadores if not t["de_baja"]), "tipos_contrato": laboral.TIPOS_CONTRATO,
            "puede_modificar": acceso.puede_modificar_cliente(tenant_id, usuario_id, cliente_fiscal["id"])}


def contexto_tareas(usuario_id: int, cliente_fiscal) -> dict:
    """Las tareas del cliente que la persona puede ver (suyas, asignadas o en las que colabora), abiertas primero."""
    tareas = [dict(t) for t in db.listar_tareas_outlook(usuario_id, incluir_asignadas=True, cliente_fiscal_id=cliente_fiscal["id"])]
    tareas.sort(key=lambda t: (t["estado"] == "completada", t["fecha_vencimiento"] or "9999", t["id"]))
    from . import tareas_trabajo
    contadores = tareas_trabajo.contadores_de_cliente(tareas)
    for t in tareas:
        t["vencida"] = tareas_trabajo.esta_vencida(t["fecha_vencimiento"], t["estado"])
    return {"tareas": tareas, "tareas_abiertas": contadores["abiertas"], "tareas_vencidas": contadores["vencidas"], "tareas_completadas": contadores["completadas"]}
