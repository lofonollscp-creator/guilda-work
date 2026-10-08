"""Rutas del "Calendario fiscal": clientes fiscales y sus vencimientos
(modelos 303/390/130/111/115/200...) por tenant. Vive en su propio
Blueprint, mismo patrón que app/rutas_tareas.py.

A diferencia de tareas/notas/categorías (que se filtran por g.usuario_id,
propiedad de un miembro concreto del equipo), esto son datos de la
GESTORÍA -- se filtran por g.tenant_id en cada consulta a db.py. Es
autoservicio por tenant, sin pantallas de backoffice: cualquier usuario
con tenant asignado puede gestionar los clientes fiscales y vencimientos
de SU tenant."""
import calendar
import csv
import io
import json
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l

from . import calcom, constancia_presentacion, db, documenso, espocrm, eventos, facturascripts, nextcloud, notificaciones_email, stripe_pagos
from .auth import login_required
from .notificaciones_email import (
    ErrorNotificacionesEmail, enviar_enlace_pago, enviar_respuesta_portal, enviar_solicitud_documento,
)
from .vencimientos_fiscales import MODELOS_POR_PAIS, generar_vencimientos_propuestos
from .vencimientos_fiscales import modelos_disponibles as modelos_disponibles_para_pais

fiscal_bp = Blueprint("fiscal", __name__, url_prefix="/fiscal")

ESTADOS_VENCIMIENTO = [
    ("pendiente", _l("Pendiente")),
    ("presentado", _l("Presentado")),
    ("fuera_plazo", _l("Fuera de plazo")),
]

# Para la vista de calendario mensual (vencimientos_calendario) -- calendar.Calendar
# usa firstweekday=0 (lunes), así que el índice 0 de estas dos listas es lunes.
MESES = [
    _l("Enero"), _l("Febrero"), _l("Marzo"), _l("Abril"), _l("Mayo"), _l("Junio"),
    _l("Julio"), _l("Agosto"), _l("Septiembre"), _l("Octubre"), _l("Noviembre"), _l("Diciembre"),
]
DIAS_SEMANA = [_l("L"), _l("M"), _l("X"), _l("J"), _l("V"), _l("S"), _l("D")]


@fiscal_bp.before_request
def _exigir_tenant():
    # Un blueprint before_request corre ANTES que @login_required de la
    # vista -- si abortáramos aquí para cualquier g.tenant_id None,
    # un visitante sin sesión (g.usuario_id también None) recibiría un 403
    # en seco en vez del redirect a /login habitual. Dejar pasar cuando no
    # hay sesión: login_required se encarga de esa parte tal cual siempre.
    if g.usuario_id is not None and g.tenant_id is None:
        abort(403)


# Países con algún país-calendario configurado en absoluto -- para el
# <select> de país en fiscal_cliente_editar.html (mostrar solo los que
# tienen o podrían tener reglas, en vez de una lista fija de países del
# mundo). Hoy solo "ES"; ver app/vencimientos_fiscales.py:MODELOS_POR_PAIS.
PAISES_CON_CALENDARIO = list(MODELOS_POR_PAIS.keys())


@fiscal_bp.route("/clientes")
@login_required
def clientes():
    q = request.args.get("q") or None
    pais = request.args.get("pais") or None
    return render_template(
        "fiscal_clientes.html",
        clientes=db.listar_clientes_fiscales(g.tenant_id, q=q, pais=pais),
        filtro_q=q, filtro_pais=pais,
        paises_en_uso=db.paises_clientes_fiscales(g.tenant_id),
    )


@fiscal_bp.route("/clientes", methods=["POST"])
@login_required
def crear_cliente():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        cliente_id = db.crear_cliente_fiscal(
            g.tenant_id, nombre, nif=request.form.get("nif"), notas=request.form.get("notas"),
            modelos_fiscales=request.form.getlist("modelos_fiscales") or None,
            email=request.form.get("email"),
        )
        # EspoCRM: opcional y best-effort, mismo idioma que el resto de
        # integraciones tenant (ver rutas_backoffice.py:crear_tenant) --
        # sin ESPOCRM_API_KEY configurada, buscar_cuenta_por_nombre/
        # crear_cuenta no hacen nada y este try/except ni se entera. El
        # calendario fiscal debe funcionar igual de bien sin EspoCRM (ver
        # comentario de cabecera de la tabla clientes_fiscales en db.py).
        try:
            cuenta_id = espocrm.buscar_cuenta_por_nombre(nombre)
            if cuenta_id is None:
                cuenta = espocrm.crear_cuenta(nombre)
                cuenta_id = cuenta["id"] if cuenta else None
            if cuenta_id:
                db.editar_cliente_fiscal(g.tenant_id, cliente_id, espocrm_cuenta_id=cuenta_id)
        except espocrm.ErrorEspoCRM:
            pass
    return redirect(url_for("fiscal.clientes"))


@fiscal_bp.route("/clientes/<int:cliente_id>")
@login_required
def ficha_cliente(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404)
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "ficha_vista")
    # Facturas de FacturaScripts (bloque 3, best-effort): solo si el
    # cliente está vinculado -- un fallo de la API no debe romper la
    # ficha del cliente, así que se traga en silencio como el resto de
    # integraciones opcionales de esta pantalla (EspoCRM).
    facturas = []
    if cliente["facturascripts_cliente_codigo"]:
        tenant = db.obtener_tenant(g.tenant_id)
        try:
            facturas = facturascripts.listar_facturas(
                tenant["facturascripts_url"], tenant["facturascripts_api_key"],
                cliente_codigo=cliente["facturascripts_cliente_codigo"], limite=10,
            )
        except facturascripts.ErrorFacturaScripts:
            facturas = []
    # Contactos de EspoCRM (tercera ronda de mejoras): solo si el cliente
    # ya está vinculado a una Cuenta -- best-effort, mismo criterio que
    # facturas/documentos/mensajes/correos de esta misma ficha.
    contactos_espocrm = []
    if cliente["espocrm_cuenta_id"]:
        try:
            contactos_espocrm = espocrm.listar_contactos_de_cuenta(cliente["espocrm_cuenta_id"])
        except espocrm.ErrorEspoCRM:
            contactos_espocrm = []
    # Próxima cita en Cal.diy (tercera ronda de mejoras): sin ninguna
    # columna nueva -- Cal.diy no tiene concepto de "cliente" propio, así
    # que se correlaciona por email (el mismo email de la ficha del
    # cliente, si tiene uno puesto) contra el asistente de cada reserva
    # próxima del tenant. Best-effort, mismo criterio que el resto de
    # integraciones opcionales de esta pantalla.
    proxima_cita = None
    if cliente["email"]:
        tenant_calcom = db.obtener_tenant(g.tenant_id)
        api_key = tenant_calcom["calcom_api_key"] if tenant_calcom else None
        if api_key:
            try:
                reservas = calcom.listar_reservas(api_key, desde=date.today().isoformat())
                for r in reservas:
                    if any(a.get("email", "").lower() == cliente["email"].lower() for a in r.get("attendees", [])):
                        proxima_cita = r
                        break
            except calcom.ErrorCalcom:
                proxima_cita = None
    # Panel de "salud del cliente" (bloque 4): documentos y mensajes del
    # portal de cliente NO tienen una función de BD propia por
    # cliente_fiscal_id (listar_documentos_vencimiento/
    # listar_mensajes_vencimiento están firmadas por vencimiento_id) --
    # se agregan aquí iterando los vencimientos ya cargados, sin tocar
    # el esquema ni añadir funciones nuevas de BD.
    vencimientos = db.listar_vencimientos_fiscales(g.tenant_id, cliente_fiscal_id=cliente_id)
    documentos_totales = []
    mensajes_totales = []
    for v in vencimientos:
        for d in db.listar_documentos_vencimiento(v["id"]):
            documentos_totales.append({**dict(d), "vencimiento": v})
        for m in db.listar_mensajes_vencimiento(v["id"]):
            mensajes_totales.append({**dict(m), "vencimiento": v})
    mensajes_totales.sort(key=lambda m: m["creado_en"], reverse=True)
    # Correos vinculados manualmente desde Correo (bloque de esta ronda,
    # ver app/rutas_correo.py:asignar_cliente_fiscal) -- no es
    # automático, un empleado tiene que haberlo enlazado a mano.
    correos_relacionados = db.listar_correos_de_cliente_fiscal(cliente_id)
    return render_template(
        "fiscal_cliente_detalle.html",
        cliente=cliente,
        expediente=db.listar_documentos_cliente(g.tenant_id, cliente_id),
        categorias_documento=db.CATEGORIAS_DOCUMENTO, soy_supervisor=db.es_supervisor_tenant(g.usuario_id),
        accesos=db.listar_accesos_cliente(g.tenant_id, cliente_id, 50) if db.es_supervisor_tenant(g.usuario_id) else None,
        acciones_acceso={k: str(v) for k, v in ETIQUETAS_ACCESO.items()},
        modelos_cliente=db.modelos_fiscales_de_cliente(cliente),
        modelos_disponibles=modelos_disponibles_para_pais(cliente["pais"]),
        vencimientos=vencimientos,
        hoy=date.today().isoformat(),
        limite_proximo=(date.today() + timedelta(days=7)).isoformat(),
        facturas=facturas,
        contactos_espocrm=contactos_espocrm,
        proxima_cita=proxima_cita,
        documentos_totales=documentos_totales,
        mensajes_totales=mensajes_totales,
        correos_relacionados=correos_relacionados,
    )


@fiscal_bp.route("/clientes/<int:cliente_id>/documentos", methods=["POST"])
@login_required
def subir_documentos_cliente(cliente_id: int):
    """Sube uno o varios archivos al expediente del cliente (hasta 10 a la vez)."""
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404)
    for archivo in request.files.getlist("archivo")[:10]:
        if archivo and archivo.filename:
            resultado, _id = db.archivar_documento_cliente(
                g.usuario_id, cliente_id, archivo.filename, archivo.mimetype, archivo.read(db.MAX_DOCUMENTO_CLIENTE_BYTES + 1),
                categoria=request.form.get("categoria"),
            )
            if resultado == "ok":
                db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "documento_subido", archivo.filename)
    return redirect(url_for("fiscal.ficha_cliente", cliente_id=cliente_id) + "#expediente")


# Tipos que un navegador interpretaría como página si se abrieran: se sirven siempre como descarga genérica.
_TIPOS_PELIGROSOS = ("text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml", "text/javascript")


@fiscal_bp.route("/clientes/<int:cliente_id>/documentos/<int:documento_id>")
@login_required
def descargar_documento_cliente(cliente_id: int, documento_id: int):
    documento = db.obtener_documento_cliente(g.tenant_id, cliente_id, documento_id)
    if documento is None:
        abort(404)
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "documento_descargado", documento["nombre_archivo"])
    tipo = documento["tipo_mime"].lower().split(";")[0]
    respuesta = Response(bytes(documento["contenido"]), mimetype="application/octet-stream" if tipo in _TIPOS_PELIGROSOS else tipo)
    respuesta.headers.set("Content-Disposition", "attachment", filename=documento["nombre_archivo"])
    respuesta.headers.set("X-Content-Type-Options", "nosniff")
    return respuesta


@fiscal_bp.route("/clientes/<int:cliente_id>/documentos/<int:documento_id>/eliminar", methods=["POST"])
@login_required
def eliminar_documento_cliente(cliente_id: int, documento_id: int):
    previo = db.obtener_documento_cliente(g.tenant_id, cliente_id, documento_id)
    if not db.eliminar_documento_cliente(g.usuario_id, cliente_id, documento_id):
        abort(404)
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "documento_eliminado", previo["nombre_archivo"] if previo else "")
    return redirect(url_for("fiscal.ficha_cliente", cliente_id=cliente_id) + "#expediente")


def _vista_previa_recordatorio(config: dict) -> dict | None:
    """Cómo quedaría el correo con el texto propio, con datos de ejemplo."""
    if not (config["asunto"] and config["cuerpo"]):
        return None
    valores = notificaciones_email.valores_plantilla(
        "Panadería López", "303", "2T 2026", "2026-07-20", 3, notificaciones_email.texto_cuando(3), "https://app.ejemplo.com/portal/entrar",
        "Tu despacho", "extractos bancarios de junio",
    )
    return {"asunto": notificaciones_email.rellenar_plantilla(config["asunto"], valores), "cuerpo": notificaciones_email.rellenar_plantilla(config["cuerpo"], valores)}


@fiscal_bp.route("/recordatorios", methods=["GET", "POST"])
@login_required
def recordatorios():
    """Cuándo y cómo se recuerda a los clientes sus vencimientos (portal): días de aviso, aviso al equipo y texto propio."""
    if g.tenant_id is None:
        abort(404)
    error = None
    guardado = False
    if request.method == "POST":
        try:
            config = db.guardar_config_recordatorios(
                g.tenant_id, request.form.get("dias_antes"), request.form.get("dias_despues"), request.form.get("avisar_equipo") == "on",
                request.form.get("asunto", ""), request.form.get("cuerpo", ""),
            )
            guardado = True
        except ValueError as e:
            error = str(e)
            config = db.obtener_config_recordatorios(g.tenant_id)
    else:
        config = db.obtener_config_recordatorios(g.tenant_id)
    return render_template(
        "fiscal_recordatorios.html", config=config, error=error, guardado=guardado, marcas=notificaciones_email.MARCAS_PLANTILLA,
        vista_previa=_vista_previa_recordatorio(config), smtp_configurado=notificaciones_email.configurado(),
        max_antes=db.MAX_AVISOS_ANTES, max_despues=db.MAX_AVISOS_DESPUES,
    )


ETIQUETAS_ACCESO = {
    "ficha_vista": _l("Ha abierto la ficha"), "cliente_editado": _l("Ha editado los datos"), "cliente_eliminado": _l("Ha enviado el cliente a la papelera"),
    "documento_subido": _l("Ha subido un documento al expediente"), "documento_descargado": _l("Ha descargado un documento del expediente"),
    "documento_eliminado": _l("Ha eliminado un documento del expediente"), "correo_archivado": _l("Ha archivado un correo en el expediente"),
    "vencimiento_documento_descargado": _l("Ha descargado un documento de un vencimiento"),
}


@fiscal_bp.route("/clientes/<int:cliente_id>/accesos.csv")
@login_required
def accesos_cliente_csv(cliente_id: int):
    """Registro completo de accesos a un cliente, para supervisores (auditoría y RGPD)."""
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None or not db.es_supervisor_tenant(g.usuario_id):
        abort(404)
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["fecha", "usuario", "accion", "detalle"])
    for a in reversed(db.listar_accesos_cliente(g.tenant_id, cliente_id, 5000)):
        escritor.writerow([a["creado_en"], a["usuario"], str(ETIQUETAS_ACCESO.get(a["accion"], a["accion"])), a["detalle"] or ""])
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "ficha_vista", "exportó el registro de accesos")
    return Response("\ufeff" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=accesos_cliente_{cliente_id}.csv", "X-Content-Type-Options": "nosniff"})


@fiscal_bp.route("/clientes/<int:cliente_id>/resumen.json")
@login_required
def resumen_cliente_json(cliente_id: int):
    """Resumen ligero para el panel lateral de /fiscal/vencimientos (patrón
    master-detail: la lista no navega a la ficha completa al hacer clic en
    un cliente, solo pide esto por AJAX). Deliberadamente NO reutiliza
    ficha_cliente() de arriba -- esa vista agrega facturas/contactos
    EspoCRM/próxima cita/documentos/mensajes con varias llamadas a APIs
    externas, pensada para una carga de página completa; aquí solo hacen
    falta los datos que ya tiene cliente_fiscal en BD, sin llamadas
    externas, para que abrir el panel sea instantáneo."""
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404)
    vencimientos = db.listar_vencimientos_fiscales(g.tenant_id, cliente_fiscal_id=cliente_id, estado="pendiente")
    return {
        "id": cliente["id"],
        "nombre": cliente["nombre"],
        "nif": cliente["nif"],
        "modelos": db.modelos_fiscales_de_cliente(cliente),
        "vencimientos_pendientes": len(vencimientos),
        "generacion_automatica": bool(cliente["generacion_automatica"]),
        "espocrm_url": espocrm.url_cuenta(cliente["espocrm_cuenta_id"]) if cliente["espocrm_cuenta_id"] else None,
        "url_ficha": url_for("fiscal.ficha_cliente", cliente_id=cliente["id"]),
        "url_generar_vencimientos": url_for("fiscal.generar_vencimientos", cliente_id=cliente["id"]),
    }


@fiscal_bp.route("/clientes/<int:cliente_id>/espocrm")
@login_required
def ver_en_espocrm(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None or not cliente["espocrm_cuenta_id"]:
        abort(404)
    return redirect(espocrm.url_cuenta(cliente["espocrm_cuenta_id"]))


@fiscal_bp.route("/clientes/<int:cliente_id>/facturascripts/vincular", methods=["POST"])
@login_required
def vincular_facturascripts(cliente_id: int):
    """Busca un cliente de FacturaScripts por nombre y lo vincula; si no
    hay ninguno, crea uno nuevo. Best-effort -- si FacturaScripts no está
    aprovisionado para este tenant o la API falla, no rompe nada."""
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404)
    tenant = db.obtener_tenant(g.tenant_id)
    try:
        encontrados = facturascripts.listar_clientes(
            tenant["facturascripts_url"], tenant["facturascripts_api_key"], texto=cliente["nombre"], limite=1,
        )
        if encontrados:
            codigo = encontrados[0]["codcliente"]
        else:
            creado = facturascripts.crear_cliente(
                tenant["facturascripts_url"], tenant["facturascripts_api_key"],
                cliente["nombre"], nif=cliente["nif"] or "", email=cliente["email"] or "",
            )
            codigo = creado["codcliente"]
        db.editar_cliente_fiscal(g.tenant_id, cliente_id, facturascripts_cliente_codigo=codigo)
    except facturascripts.ErrorFacturaScripts:
        pass
    return redirect(url_for("fiscal.ficha_cliente", cliente_id=cliente_id))


@fiscal_bp.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required
def editar_cliente(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404)
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if nombre:
            pais = (request.form.get("pais") or "ES").strip().upper()
            db.editar_cliente_fiscal(
                g.tenant_id, cliente_id,
                nombre=nombre, nif=request.form.get("nif"), notas=request.form.get("notas"),
                modelos_fiscales=db.serializar_modelos_fiscales(request.form.getlist("modelos_fiscales") or None),
                # Un país sin calendario configurado no tiene modelos que marcar,
                # así que tampoco tiene sentido la generación automática --
                # se desactiva sola en vez de dejar un checkbox activo que
                # nunca generaría nada (ver PAISES_CON_CALENDARIO arriba).
                generacion_automatica=1 if (request.form.get("generacion_automatica") and pais in PAISES_CON_CALENDARIO) else 0,
                email=(request.form.get("email") or "").strip() or None,
                pais=pais,
                recordatorios_portal=1 if request.form.get("recordatorios_portal") else 0,
                idioma=request.form.get("idioma") if request.form.get("idioma") in ("es", "ca", "en", "fr") else "es",
            )
            db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "cliente_editado")
        return redirect(url_for("fiscal.clientes"))
    return render_template(
        "fiscal_cliente_editar.html",
        cliente=cliente, modelos_cliente=db.modelos_fiscales_de_cliente(cliente),
        modelos_disponibles=modelos_disponibles_para_pais(cliente["pais"]),
        paises_con_calendario=PAISES_CON_CALENDARIO,
    )


@fiscal_bp.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
@login_required
def eliminar_cliente(cliente_id: int):
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404)
    db.eliminar_cliente_fiscal(g.tenant_id, cliente_id)
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "cliente_eliminado")
    return redirect(url_for("fiscal.clientes"))


@fiscal_bp.route("/clientes/<int:cliente_id>/generar-vencimientos", methods=["GET", "POST"])
@login_required
def generar_vencimientos(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404)

    modelos_disponibles = modelos_disponibles_para_pais(cliente["pais"])

    if request.method == "POST":
        # Cada propuesta llega como 3 campos indexados por posición `i`
        # (modelo_i/periodo_i/fecha_limite_i) -- el usuario pudo haber
        # editado la fecha o quitado alguna fila entera antes de confirmar,
        # así que se guarda tal cual venga del formulario, no lo que
        # generar_vencimientos_propuestos calculó originalmente.
        indices = sorted({
            clave.rsplit("_", 1)[1] for clave in request.form if clave.startswith("modelo_")
        }, key=int)
        for i in indices:
            modelo = request.form.get(f"modelo_{i}", "").strip()
            periodo = request.form.get(f"periodo_{i}", "").strip()
            fecha_limite = request.form.get(f"fecha_limite_{i}", "").strip()
            if modelo and periodo and fecha_limite:
                db.crear_vencimiento_fiscal(g.tenant_id, cliente_id, modelo, periodo, fecha_limite)
        return redirect(url_for("fiscal.vencimientos"))

    # Sin `modelo` explícito en la query, se parte de los modelos guardados
    # del cliente (modelos_fiscales) si tiene alguno -- antes siempre
    # arrancaba con TODOS los modelos marcados, así que había que
    # desmarcar a mano los que no aplican cada vez que se generaba.
    modelos_cliente = db.modelos_fiscales_de_cliente(cliente)
    modelos_pedidos = request.args.getlist("modelo") or modelos_cliente or list(modelos_disponibles.keys())
    anio = request.args.get("anio", type=int) or date.today().year
    propuestas = generar_vencimientos_propuestos(modelos_pedidos, anio, pais=cliente["pais"])
    return render_template(
        "fiscal_generar_vencimientos.html",
        cliente=cliente, propuestas=propuestas, anio=anio,
        modelos_disponibles=modelos_disponibles, modelos_pedidos=modelos_pedidos,
    )


@fiscal_bp.route("/generar-vencimientos-masivo", methods=["GET", "POST"])
@login_required
def generar_vencimientos_masivo():
    """Aplica generar_vencimientos_propuestos() a TODOS los clientes del
    tenant que tengan modelos_fiscales definido, de una sola vez -- antes
    había que entrar cliente a cliente en "Generar vencimientos". No
    reescribe la función pura, solo la llama una vez por cliente."""
    clientes_tenant = db.listar_clientes_fiscales(g.tenant_id)
    clientes_con_modelos = [
        (c, db.modelos_fiscales_de_cliente(c)) for c in clientes_tenant
    ]
    clientes_con_modelos = [(c, m) for c, m in clientes_con_modelos if m]

    if request.method == "POST":
        anio = request.form.get("anio", type=int) or date.today().year
        creados = 0
        for cliente, modelos in clientes_con_modelos:
            for p in generar_vencimientos_propuestos(modelos, anio, pais=cliente["pais"]):
                db.crear_vencimiento_fiscal(g.tenant_id, cliente["id"], p["modelo"], p["periodo"], p["fecha_limite"])
                creados += 1
        return redirect(url_for("fiscal.vencimientos"))

    anio = request.args.get("anio", type=int) or date.today().year
    previa = [
        {"cliente": cliente, "propuestas": generar_vencimientos_propuestos(modelos, anio, pais=cliente["pais"])}
        for cliente, modelos in clientes_con_modelos
    ]
    return render_template("fiscal_generar_vencimientos_masivo.html", previa=previa, anio=anio)


@fiscal_bp.route("/vencimientos/export.csv")
@login_required
def export_csv():
    filas = db.listar_vencimientos_fiscales(
        g.tenant_id,
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None,
        estado=request.args.get("estado") or None,
        cliente_fiscal_id=request.args.get("cliente_id", type=int),
        pais=request.args.get("pais") or None,
    )
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(["cliente", "modelo", "periodo", "fecha_limite", "estado", "notas"])
    for v in filas:
        escritor.writerow([v["cliente_nombre"], v["modelo"], v["periodo"], v["fecha_limite"][:10], v["estado"], v["notas"] or ""])
    return Response(
        buffer.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=vencimientos_fiscales.csv"},
    )


@fiscal_bp.route("/vencimientos/export.json")
@login_required
def export_json():
    filas = db.listar_vencimientos_fiscales(
        g.tenant_id,
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None,
        estado=request.args.get("estado") or None,
        cliente_fiscal_id=request.args.get("cliente_id", type=int),
        pais=request.args.get("pais") or None,
    )
    datos = [
        {
            "cliente": v["cliente_nombre"], "modelo": v["modelo"], "periodo": v["periodo"],
            "fecha_limite": v["fecha_limite"][:10], "estado": v["estado"], "notas": v["notas"],
        }
        for v in filas
    ]
    return Response(json.dumps(datos, ensure_ascii=False, indent=2), mimetype="application/json")


VENCIMIENTOS_POR_PAGINA = 100


@fiscal_bp.route("/vencimientos")
@login_required
def vencimientos():
    estado = request.args.get("estado") or None
    cliente_fiscal_id = request.args.get("cliente_id", type=int)
    pais = request.args.get("pais") or None
    # desde/hasta: usados por el enlace de la tarjeta del dashboard
    # ("Vencimientos próximos", próximos 30 días) -- opcionales, sin ellos
    # se ve el listado completo como siempre.
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    # Paginado: con miles de vencimientos la página entera pesaba segundos (lo midió scripts/prueba_carga.py).
    # Se pide una fila de más para saber si hay página siguiente sin un COUNT aparte.
    pagina = max(request.args.get("pagina", 1, type=int) or 1, 1)
    filas = db.listar_vencimientos_fiscales(
        g.tenant_id, estado=estado, cliente_fiscal_id=cliente_fiscal_id, desde=desde, hasta=hasta, pais=pais,
        limite=VENCIMIENTOS_POR_PAGINA + 1, offset=(pagina - 1) * VENCIMIENTOS_POR_PAGINA,
    )
    return render_template(
        "fiscal_vencimientos.html",
        vencimientos=filas[:VENCIMIENTOS_POR_PAGINA],
        pagina=pagina, hay_pagina_anterior=pagina > 1, hay_pagina_siguiente=len(filas) > VENCIMIENTOS_POR_PAGINA,
        filtro_desde=desde, filtro_hasta=hasta,
        clientes=db.listar_clientes_fiscales(g.tenant_id),
        estados=ESTADOS_VENCIMIENTO,
        filtro_estado=estado,
        filtro_cliente_id=cliente_fiscal_id,
        filtro_pais=pais,
        paises_en_uso=db.paises_clientes_fiscales(g.tenant_id),
        # Para pintar en rojo lo pendiente ya vencido sin esperar a que pase
        # el cron de saneo (app/vencimientos_fiscales.py) que marca
        # fuera_plazo -- ese cron corre una vez al día, esto se ve al
        # instante en cuanto la fecha pasa. limite_proximo: a partir de qué
        # fecha ya no se pinta en ámbar (más de 7 días vista, color neutro).
        hoy=date.today().isoformat(),
        limite_proximo=(date.today() + timedelta(days=7)).isoformat(),
    )


@fiscal_bp.route("/vencimientos/calendario")
@login_required
def vencimientos_calendario():
    """Vista de calendario mensual, alternable con la lista de
    /fiscal/vencimientos (mismo patrón que Tiquets tarjetas/kanban: rutas
    separadas, no un parámetro ?vista= en la misma). Reutiliza
    db.listar_vencimientos_fiscales acotado al mes visible en vez de una
    consulta nueva."""
    hoy = date.today()
    anio = request.args.get("anio", type=int) or hoy.year
    mes = request.args.get("mes", type=int) or hoy.month
    if not 1 <= mes <= 12:
        mes = hoy.month
    estado = request.args.get("estado") or None
    cliente_fiscal_id = request.args.get("cliente_id", type=int)
    pais = request.args.get("pais") or None

    primer_dia = date(anio, mes, 1)
    ultimo_dia_mes = calendar.monthrange(anio, mes)[1]
    primer_dia_siguiente = (
        date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    )
    vencimientos_mes = db.listar_vencimientos_fiscales(
        g.tenant_id, desde=primer_dia.isoformat(), hasta=primer_dia_siguiente.isoformat(),
        estado=estado, cliente_fiscal_id=cliente_fiscal_id, pais=pais,
    )
    por_dia: dict[int, list] = {}
    for v in vencimientos_mes:
        dia = int(v["fecha_limite"][8:10])
        por_dia.setdefault(dia, []).append(v)

    mes_anterior = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    mes_siguiente = (anio + 1, 1) if mes == 12 else (anio, mes + 1)

    return render_template(
        "fiscal_vencimientos_calendario.html",
        anio=anio, mes=mes, nombre_mes=MESES[mes - 1], dias_semana=DIAS_SEMANA,
        semanas=calendar.Calendar(firstweekday=0).monthdayscalendar(anio, mes),
        por_dia=por_dia,
        clientes=db.listar_clientes_fiscales(g.tenant_id),
        estados=ESTADOS_VENCIMIENTO,
        filtro_estado=estado,
        filtro_cliente_id=cliente_fiscal_id,
        filtro_pais=pais,
        paises_en_uso=db.paises_clientes_fiscales(g.tenant_id),
        hoy=hoy,
        anio_mes_anterior=mes_anterior, anio_mes_siguiente=mes_siguiente,
    )


def _guardar_justificante(vencimiento_id: int, archivo) -> bool:
    """Guarda el justificante oficial subido por el equipo (imagen o PDF, máx.
    8 MB). False si no hay archivo o no es válido."""
    if archivo is None or not archivo.filename:
        return False
    contenido = archivo.read(db.TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO + 1)
    if archivo.mimetype not in db.MIME_PERMITIDOS_DOCUMENTO_VENCIMIENTO or len(contenido) > db.TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO:
        return False
    db.subir_documento_vencimiento(vencimiento_id, archivo.filename, archivo.mimetype, contenido, origen="justificante")
    return True


def _generar_constancia(vencimiento) -> None:
    """(Re)genera la constancia de presentación en PDF; sustituye a la anterior."""
    cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
    tenant = db.obtener_tenant(g.tenant_id)
    con_justificante = bool(db.listar_documentos_vencimiento(vencimiento["id"], origen="justificante"))
    pdf = constancia_presentacion.generar_pdf(
        tenant["nombre"] if tenant else "", cliente["nombre"] if cliente else "", cliente["nif"] if cliente else None,
        vencimiento["modelo"], vencimiento["periodo"], vencimiento["fecha_limite"], datetime.now(), con_justificante,
    )
    db.eliminar_documentos_vencimiento_por_origen(vencimiento["id"], "constancia")
    db.subir_documento_vencimiento(
        vencimiento["id"], f"constancia-{vencimiento['modelo']}-{vencimiento['periodo']}.pdf".replace("/", "-"),
        "application/pdf", pdf, origen="constancia",
    )


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/constancia", methods=["POST"])
@login_required
def regenerar_constancia(vencimiento_id: int):
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    _generar_constancia(vencimiento)
    return redirect(url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id))


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/justificante", methods=["POST"])
@login_required
def subir_justificante(vencimiento_id: int):
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    if not _guardar_justificante(vencimiento_id, request.files.get("justificante")):
        abort(400, _("Archivo no válido: solo imágenes o PDF, hasta 8MB."))
    if vencimiento["estado"] == "presentado" and db.listar_documentos_vencimiento(vencimiento_id, origen="constancia"):
        _generar_constancia(vencimiento)  # actualiza "Justificante oficial: adjunto"
    return redirect(url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id))


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/presentado", methods=["POST"])
@login_required
def marcar_presentado(vencimiento_id: int):
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    db.marcar_presentado_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    # Justificante oficial (opcional, si el formulario lo trae) y constancia
    # de presentación en PDF: ambos visibles para el cliente en su portal. Un
    # fallo al generar la constancia nunca debe deshacer el "presentado".
    _guardar_justificante(vencimiento_id, request.files.get("justificante"))
    try:
        _generar_constancia(vencimiento)
    except Exception:  # noqa: BLE001
        pass
    try:
        eventos.emitir(
            "vencimiento.presentado", g.tenant_id,
            {"vencimiento_id": vencimiento_id, "modelo": vencimiento["modelo"], "periodo": vencimiento["periodo"]},
        )
    except Exception:
        pass  # un fallo al emitir el evento no debe afectar al vencimiento ya marcado
    # Facturación opcional (bloque 3): solo si el empleado ha rellenado
    # concepto+importe explícitamente en el formulario de la ficha del
    # vencimiento -- NUNCA se factura automáticamente sin que alguien
    # revise el importe (el botón rápido del listado, sin este
    # formulario, solo marca presentado, como siempre).
    concepto = (request.form.get("factura_concepto") or "").strip()
    importe = request.form.get("factura_importe", type=float)
    if concepto and importe:
        cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
        if cliente is not None and cliente["facturascripts_cliente_codigo"]:
            tenant = db.obtener_tenant(g.tenant_id)
            try:
                facturascripts.crear_factura(
                    tenant["facturascripts_url"], tenant["facturascripts_api_key"],
                    cliente["facturascripts_cliente_codigo"],
                    [{"descripcion": concepto, "cantidad": 1, "precio": importe}],
                )
                eventos.emitir(
                    "factura.emitida", g.tenant_id,
                    {"cliente_fiscal_id": cliente["id"], "concepto": concepto, "importe": importe},
                )
            except facturascripts.ErrorFacturaScripts:
                pass
    return redirect(request.referrer or url_for("fiscal.vencimientos"))


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/editar", methods=["GET", "POST"])
@login_required
def editar_vencimiento(vencimiento_id: int):
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    if request.method == "POST":
        usuario_id = request.form.get("usuario_id", type=int)
        documento_solicitado = (request.form.get("documento_solicitado") or "").strip() or None
        db.editar_vencimiento_fiscal(
            g.tenant_id, vencimiento_id,
            modelo=request.form.get("modelo", vencimiento["modelo"]).strip(),
            periodo=request.form.get("periodo", vencimiento["periodo"]).strip(),
            fecha_limite=request.form.get("fecha_limite", vencimiento["fecha_limite"]),
            estado=request.form.get("estado", vencimiento["estado"]),
            notas=request.form.get("notas"),
            usuario_id=usuario_id if usuario_id else None,
            documento_solicitado=documento_solicitado,
        )
        # Avisar al cliente por email solo cuando la petición es NUEVA (no
        # en cada guardado del formulario) -- best-effort, mismo criterio
        # que el resto de integraciones opcionales: un fallo de SMTP nunca
        # debe romper el guardado del vencimiento.
        if documento_solicitado and documento_solicitado != vencimiento["documento_solicitado"]:
            cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
            if cliente is not None and cliente["email"]:
                try:
                    enviar_solicitud_documento(
                        cliente["email"], documento_solicitado, url_for("portal_cliente.entrar", _external=True),
                    )
                except ErrorNotificacionesEmail:
                    pass
        return redirect(url_for("fiscal.vencimientos"))
    db.marcar_mensajes_leidos(vencimiento_id, "empleado")
    usuarios_tenant = [db.obtener_usuario(uid) for uid in db.usuarios_de_tenant(g.tenant_id)]
    tenant = db.obtener_tenant(g.tenant_id)
    cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
    return render_template(
        "fiscal_vencimiento_editar.html",
        vencimiento=vencimiento, estados=ESTADOS_VENCIMIENTO, usuarios=usuarios_tenant,
        # Documentos subidos por el CLIENTE desde el portal (app/rutas_portal_cliente.py)
        # -- así el equipo los ve sin tener que entrar al portal.
        documentos_cliente=db.listar_documentos_vencimiento(vencimiento_id),
        mensajes_cliente=db.listar_mensajes_vencimiento(vencimiento_id),
        # Firma electrónica (app/documenso.py): solo se ofrece si el tenant
        # tiene token configurado y el cliente tiene email (es el firmante).
        puede_enviar_a_firma=bool(tenant and tenant["documenso_api_key"] and cliente and cliente["email"]),
        # Facturación (app/facturascripts.py): solo se ofrece si el cliente
        # ya está vinculado a un código de FacturaScripts.
        puede_facturar=bool(cliente and cliente["facturascripts_cliente_codigo"]),
        # Cobro por Stripe Connect (app/stripe_pagos.py): solo si el tenant
        # ya conectó su propia cuenta y el cliente tiene email al que
        # mandarle el enlace de Checkout.
        puede_cobrar_stripe=bool(tenant and tenant["stripe_account_id"] and cliente and cliente["email"]),
    )


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/enviar-a-firma", methods=["POST"])
@login_required
def enviar_a_firma_vencimiento(vencimiento_id: int):
    """Sube un PDF y lo manda a firmar al cliente fiscal vía Documenso --
    best-effort: si el tenant no tiene documenso_api_key configurada, el
    cliente no tiene email, o Documenso falla, no rompe la edición del
    vencimiento (mismo criterio que la integración de EspoCRM). El
    firmante es siempre el cliente fiscal del vencimiento -- para otros
    firmantes hay que usar la propia interfaz de Documenso."""
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    tenant = db.obtener_tenant(g.tenant_id)
    api_key = tenant["documenso_api_key"] if tenant else None
    cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
    archivo = request.files.get("documento_firma")
    if api_key and cliente is not None and cliente["email"] and archivo and archivo.filename:
        try:
            titulo = f"{vencimiento['modelo']} {vencimiento['periodo']} — {cliente['nombre']}"
            resultado = documenso.crear_documento(
                api_key, titulo, archivo.read(), [{"email": cliente["email"], "nombre": cliente["nombre"]}],
            )
            documento_id = resultado.get("id") or resultado.get("envelopeId")
            if documento_id:
                documenso.enviar_a_firma(api_key, documento_id)
                db.editar_vencimiento_fiscal(g.tenant_id, vencimiento_id, documenso_documento_id=documento_id)
                eventos.emitir(
                    "documento.enviado_a_firma", g.tenant_id,
                    {"vencimiento_id": vencimiento_id, "cliente_fiscal_id": cliente["id"]},
                )
        except documenso.ErrorDocumenso:
            pass
    return redirect(url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id))


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/cobrar-stripe", methods=["POST"])
@login_required
def cobrar_stripe_vencimiento(vencimiento_id: int):
    """Genera un enlace de Stripe Checkout para que el cliente pague este
    vencimiento y se lo manda por email -- best-effort, mismo criterio que
    enviar_a_firma_vencimiento: si el tenant no tiene stripe_account_id, el
    cliente no tiene email, el importe no es válido, o Stripe falla, no
    rompe la edición del vencimiento. El importe se lee del formulario en
    el momento (nunca cacheado) -- lo introduce el empleado a mano, igual
    que el importe de "Marcar presentado y facturar"."""
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    tenant = db.obtener_tenant(g.tenant_id)
    stripe_account_id = tenant["stripe_account_id"] if tenant else None
    cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
    importe_eur = request.form.get("importe_eur", type=float)
    if stripe_account_id and cliente is not None and cliente["email"] and importe_eur and importe_eur > 0:
        try:
            concepto = f"{vencimiento['modelo']} {vencimiento['periodo']} — {cliente['nombre']}"
            url_checkout = stripe_pagos.crear_sesion_pago(
                stripe_account_id, stripe_pagos.euros_a_centimos(importe_eur), concepto,
                url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id, _external=True),
                url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id, _external=True),
                metadata={"vencimiento_id": vencimiento_id},
            )
            enviar_enlace_pago(cliente["email"], concepto, url_checkout)
        except (stripe_pagos.ErrorStripe, ErrorNotificacionesEmail):
            pass
    return redirect(url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id))


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/mensajes", methods=["POST"])
@login_required
def responder_mensaje_vencimiento(vencimiento_id: int):
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    texto = (request.form.get("texto") or "").strip()
    if texto:
        db.crear_mensaje_vencimiento(vencimiento_id, "empleado", texto, usuario_id=g.usuario_id)
        db.marcar_mensajes_leidos(vencimiento_id, "empleado")
        # Aviso por email al cliente -- opt-in (solo si tiene email puesto,
        # igual que el resto del portal) y nunca debe romper la respuesta
        # del empleado si el SMTP falla puntualmente.
        cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
        if cliente is not None and cliente["email"]:
            try:
                enviar_respuesta_portal(cliente["email"], texto, url_for("portal_cliente.entrar", _external=True))
            except ErrorNotificacionesEmail:
                pass
    return redirect(url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id))


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/documentos/<int:documento_id>")
@login_required
def descargar_documento_vencimiento(vencimiento_id: int, documento_id: int):
    if db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id) is None:
        abort(404)
    documento = db.obtener_documento_vencimiento(documento_id)
    if documento is None or documento["vencimiento_id"] != vencimiento_id:
        abort(404)
    try:
        contenido = db.contenido_documento_vencimiento(documento)
    except nextcloud.ErrorNextcloud:
        abort(503)
    venc = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    db.registrar_acceso_cliente(g.tenant_id, venc["cliente_fiscal_id"], g.usuario_id, "vencimiento_documento_descargado", documento["nombre_archivo"])
    respuesta = Response(contenido, mimetype=documento["tipo_mime"])
    respuesta.headers.set("Content-Disposition", "attachment", filename=documento["nombre_archivo"])
    return respuesta


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/eliminar", methods=["POST"])
@login_required
def eliminar_vencimiento(vencimiento_id: int):
    if db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id) is None:
        abort(404)
    db.eliminar_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    return redirect(url_for("fiscal.vencimientos"))


# --- Papelera del calendario fiscal -----------------------------------------
# Aparte de /papelera (que es por g.usuario_id, ver app/main.py): estas dos
# tablas son por tenant_id, así que tienen su propia mini-papelera aquí en
# vez de sumarse al UNION de db.papelera(). Antes de esto, un cliente o
# vencimiento "eliminado" (que en realidad solo va a papelera_en, ver
# db.eliminar_cliente_fiscal/eliminar_vencimiento_fiscal) era invisible e
# irrecuperable desde la UI pese al aviso de "se moverá a la papelera" en
# el diálogo de confirmación de borrado.

@fiscal_bp.route("/papelera")
@login_required
def papelera():
    return render_template("fiscal_papelera.html", items=db.papelera_fiscal(g.tenant_id))


@fiscal_bp.route("/papelera/<tipo>/<int:item_id>/restaurar", methods=["POST"])
@login_required
def restaurar_papelera(tipo: str, item_id: int):
    if tipo == "cliente_fiscal":
        db.restaurar_cliente_fiscal(g.tenant_id, item_id)
    elif tipo == "vencimiento_fiscal":
        db.restaurar_vencimiento_fiscal(g.tenant_id, item_id)
    else:
        abort(404)
    return redirect(url_for("fiscal.papelera"))


@fiscal_bp.route("/papelera/<tipo>/<int:item_id>/eliminar-definitivamente", methods=["POST"])
@login_required
def eliminar_definitivamente_papelera(tipo: str, item_id: int):
    if tipo == "cliente_fiscal":
        db.eliminar_cliente_fiscal_definitivamente(g.tenant_id, item_id)
    elif tipo == "vencimiento_fiscal":
        db.eliminar_vencimiento_fiscal_definitivamente(g.tenant_id, item_id)
    else:
        abort(404)
    return redirect(url_for("fiscal.papelera"))
