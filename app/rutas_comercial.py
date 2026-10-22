"""Pantallas del módulo Comercial: embudo de oportunidades, su ficha con cronología, las etapas, los informes y las notas de reunión con acta de IA (ver app/comercial.py y app/reuniones.py)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import acceso, alta_cliente, comercial, db, nucleo, reuniones, verticales
from .auth import login_required
from .comercial import ErrorComercial
from .reuniones import ErrorReunion

comercial_bp = Blueprint("comercial", __name__, url_prefix="/comercial")


@comercial_bp.before_request
def _solo_con_el_modulo():
    """Es del módulo Comercial: sin él no existe (404); y quien solo audita puede mirar, no cambiar (los servicios lo vuelven a comprobar)."""
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "comercial"):
        abort(404)


@comercial_bp.app_context_processor
def _para_la_ficha_del_cliente():
    """`crm_de_cliente(cliente_id)` para el panel «Comercial» de la ficha del cliente: devuelve None si el despacho no tiene el módulo."""
    def crm_de_cliente(cliente_id: int):
        if g.get("tenant_id") is None or g.get("usuario_id") is None or not verticales.esta_activo(g.tenant_id, "comercial"):
            return None
        return {"oportunidades": comercial.listar_oportunidades(g.tenant_id, g.usuario_id, estado=None, cliente_id=cliente_id, limite=20),
                "reuniones": reuniones.listar(g.tenant_id, g.usuario_id, cliente_id=cliente_id, limite=5)}
    return {"crm_de_cliente": crm_de_cliente}


def _error() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _volver(destino: str, **valores):
    return redirect(url_for(destino, **valores))


def _con_error(destino: str, e: Exception, **valores):
    return redirect(url_for(destino, error=_(str(e)) if str(e) else None, **valores))


def _clientes() -> list:
    cond, params = acceso.condicion_nucleo(g.tenant_id, g.usuario_id, "c.id")
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT c.id, c.nombre FROM clientes c WHERE c.tenant_id = ? AND c.papelera_en IS NULL{' AND ' + cond if cond else ''} ORDER BY c.nombre LIMIT 1000",
                            [g.tenant_id, *params]).fetchall()
    finally:
        conn.close()


def _equipo() -> list:
    return db.listar_companeros_tenant(g.usuario_id)


def _int(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


# --- Embudo ------------------------------------------------------------------------------------------------------------------

@comercial_bp.route("/")
@login_required
def tablero():
    vista = "lista" if request.args.get("vista") == "lista" else "tablero"
    estado = request.args.get("estado") or "abierta"
    if estado not in ("abierta", "ganada", "perdida", "todas"):
        estado = "abierta"
    filtros = dict(estado=None if estado == "todas" else estado, responsable_id=_int(request.args.get("responsable_id")), q=request.args.get("q"))
    oportunidades = comercial.listar_oportunidades(g.tenant_id, g.usuario_id, **filtros)
    etapas = comercial.listar_etapas(g.tenant_id)
    columnas = {e["clave"]: [o for o in oportunidades if o["etapa"] == e["clave"]] for e in etapas}
    mostradas = [e for e in etapas if e["tipo"] == "abierta"] if estado == "abierta" else etapas
    total = sum(o["importe_centimos"] for o in oportunidades if o["estado"] == "abierta")
    ponderado = sum(round(o["importe_centimos"] * o["probabilidad"] / 100) for o in oportunidades if o["estado"] == "abierta")
    return render_template("comercial_tablero.html", oportunidades=oportunidades, etapas=etapas, mostradas=mostradas, columnas=columnas, vista=vista, estado=estado,
                           responsable_id=filtros["responsable_id"], q=request.args.get("q") or "", equipo=_equipo(), total=total, ponderado=ponderado, error=_error(),
                           estancadas={o["id"] for o in comercial.estancadas(g.tenant_id, g.usuario_id)})


@comercial_bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    if request.method == "POST":
        try:
            oid = comercial.crear_oportunidad(
                g.tenant_id, g.usuario_id, request.form.get("titulo", ""), cliente_id=request.form.get("cliente_id"), contacto_nombre=request.form.get("contacto_nombre"),
                contacto_email=request.form.get("contacto_email"), contacto_telefono=request.form.get("contacto_telefono"), empresa=request.form.get("empresa"),
                importe=request.form.get("importe"), cierre_previsto=request.form.get("cierre_previsto"), responsable_id=request.form.get("responsable_id"),
                origen=request.form.get("origen"), notas=request.form.get("notas"), etapa=request.form.get("etapa") or None)
        except ErrorComercial as e:
            return render_template("comercial_form.html", o=request.form, etapas=[x for x in comercial.listar_etapas(g.tenant_id) if x["tipo"] == "abierta"], clientes=_clientes(),
                                   equipo=_equipo(), error=_(str(e)), nueva=True), 422
        return _volver("comercial.ficha", oportunidad_id=oid)
    return render_template("comercial_form.html", o={"cliente_id": request.args.get("cliente_id", type=int), "responsable_id": g.usuario_id}, nueva=True, error=_error(),
                           etapas=[x for x in comercial.listar_etapas(g.tenant_id) if x["tipo"] == "abierta"], clientes=_clientes(), equipo=_equipo())


def _oportunidad_o_404(oportunidad_id: int) -> dict:
    o = comercial.obtener_oportunidad(g.tenant_id, g.usuario_id, oportunidad_id)
    if o is None:
        abort(404)
    return o


@comercial_bp.route("/<int:oportunidad_id>")
@login_required
def ficha(oportunidad_id: int):
    o = _oportunidad_o_404(oportunidad_id)
    return render_template("comercial_ficha.html", o=o, cronologia=comercial.cronologia(g.tenant_id, g.usuario_id, oportunidad_id=oportunidad_id), etapas=comercial.listar_etapas(g.tenant_id),
                           tipos=comercial.TIPOS_ACTIVIDAD, hoy=date.today().isoformat(), gestion_fiscal=alta_cliente.gestion_fiscal_disponible(g.tenant_id), error=_error(),
                           reuniones=reuniones.listar(g.tenant_id, g.usuario_id, oportunidad_id=oportunidad_id))


@comercial_bp.route("/<int:oportunidad_id>/editar", methods=["GET", "POST"])
@login_required
def editar(oportunidad_id: int):
    o = _oportunidad_o_404(oportunidad_id)
    if request.method == "POST":
        campos = {c: request.form.get(c) for c in ("titulo", "contacto_nombre", "contacto_email", "contacto_telefono", "empresa", "importe", "cierre_previsto", "origen", "notas", "responsable_id", "cliente_id")
                  if c in request.form}
        try:
            comercial.editar_oportunidad(g.tenant_id, g.usuario_id, oportunidad_id, **campos)
        except ErrorComercial as e:
            return render_template("comercial_form.html", o={**o, **request.form.to_dict()}, etapas=[], clientes=_clientes(), equipo=_equipo(), error=_(str(e)), nueva=False), 422
        return _volver("comercial.ficha", oportunidad_id=oportunidad_id)
    return render_template("comercial_form.html", o={**o, "importe": f"{o['importe']:.2f}".replace(".", ",") if o["importe_centimos"] else ""}, etapas=[], clientes=_clientes(), equipo=_equipo(),
                           error=_error(), nueva=False)


@comercial_bp.route("/<int:oportunidad_id>/etapa", methods=["POST"])
@login_required
def etapa(oportunidad_id: int):
    destino = request.form.get("volver_a", "")
    destino = destino if destino.startswith("/comercial") else url_for("comercial.ficha", oportunidad_id=oportunidad_id)
    try:
        comercial.mover_oportunidad(g.tenant_id, g.usuario_id, oportunidad_id, request.form.get("etapa", ""), request.form.get("motivo"))
    except ErrorComercial as e:
        return redirect(url_for("comercial.ficha", oportunidad_id=oportunidad_id, error=_(str(e))) if not request.form.get("volver_a") else f"{destino}{'&' if '?' in destino else '?'}error={_(str(e))}")
    return redirect(destino)


@comercial_bp.route("/<int:oportunidad_id>/actividad", methods=["POST"])
@login_required
def actividad(oportunidad_id: int):
    try:
        comercial.registrar_actividad(g.tenant_id, g.usuario_id, tipo=request.form.get("tipo", ""), asunto=request.form.get("asunto", ""), oportunidad_id=oportunidad_id,
                                      texto=request.form.get("texto"), fecha=request.form.get("fecha"), proxima_accion=request.form.get("proxima_accion") or None,
                                      proxima_fecha=request.form.get("proxima_fecha") or None)
    except ErrorComercial as e:
        return _con_error("comercial.ficha", e, oportunidad_id=oportunidad_id)
    return _volver("comercial.ficha", oportunidad_id=oportunidad_id)


@comercial_bp.route("/<int:oportunidad_id>/convertir", methods=["POST"])
@login_required
def convertir(oportunidad_id: int):
    try:
        res = comercial.convertir_en_cliente(g.tenant_id, g.usuario_id, oportunidad_id, gestion_fiscal=bool(request.form.get("gestion_fiscal")), nif=request.form.get("nif"),
                                             ganar=bool(request.form.get("ganar", "1")))
    except ErrorComercial as e:
        return _con_error("comercial.ficha", e, oportunidad_id=oportunidad_id)
    return redirect(url_for("clientes.ficha", cliente_id=res["cliente_id"])) if request.form.get("ir_al_cliente") else _volver("comercial.ficha", oportunidad_id=oportunidad_id)


@comercial_bp.route("/<int:oportunidad_id>/papelera", methods=["POST"])
@login_required
def papelera(oportunidad_id: int):
    try:
        comercial.papelera_oportunidad(g.tenant_id, g.usuario_id, oportunidad_id)
    except ErrorComercial as e:
        return _con_error("comercial.ficha", e, oportunidad_id=oportunidad_id)
    return _volver("comercial.tablero")


# --- Etapas e informes -------------------------------------------------------------------------------------------------------

@comercial_bp.route("/etapas", methods=["GET", "POST"])
@login_required
def etapas():
    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            if accion == "guardar":
                comercial.renombrar_etapa(g.tenant_id, g.usuario_id, request.form.get("clave", ""), request.form.get("nombre", ""), request.form.get("probabilidad"))
            elif accion in ("subir", "bajar"):
                comercial.mover_etapa(g.tenant_id, g.usuario_id, request.form.get("clave", ""), -1 if accion == "subir" else 1)
            elif accion == "crear":
                comercial.crear_etapa(g.tenant_id, g.usuario_id, request.form.get("nombre", ""), request.form.get("probabilidad") or 50)
            elif accion == "borrar":
                comercial.borrar_etapa(g.tenant_id, g.usuario_id, request.form.get("clave", ""))
        except ErrorComercial as e:
            return _con_error("comercial.etapas", e)
        return _volver("comercial.etapas")
    return render_template("comercial_etapas.html", etapas=comercial.listar_etapas(g.tenant_id), puede_editar=acceso.es_directivo(g.usuario_id), error=_error())


@comercial_bp.route("/informes")
@login_required
def informes():
    try:
        e = comercial.embudo(g.tenant_id, g.usuario_id, request.args.get("desde"), request.args.get("hasta"))
        error = _error()
    except ErrorComercial as ex:
        e, error = comercial.embudo(g.tenant_id, g.usuario_id), _(str(ex))
    return render_template("comercial_informes.html", e=e, error=error)


# --- Notas de reunión ----------------------------------------------------------------------------------------------------------

@comercial_bp.route("/reuniones")
@login_required
def reuniones_lista():
    return render_template("reuniones_lista.html", reuniones=reuniones.listar(g.tenant_id, g.usuario_id), error=_error())


@comercial_bp.route("/reuniones/nueva", methods=["GET", "POST"])
@login_required
def reunion_nueva():
    if request.method == "POST":
        try:
            rid = reuniones.crear(g.tenant_id, g.usuario_id, request.form.get("titulo", ""), fecha=request.form.get("fecha"), plantilla=request.form.get("plantilla") or "cliente",
                                  cliente_id=request.form.get("cliente_id"), oportunidad_id=request.form.get("oportunidad_id"), participantes=request.form.get("participantes"), notas=request.form.get("notas"))
        except (ErrorReunion, ErrorComercial) as e:
            return render_template("reunion_nueva.html", r=request.form, plantillas=reuniones.PLANTILLAS, clientes=_clientes(), hoy=date.today().isoformat(), error=_(str(e))), 422
        return _volver("comercial.reunion", reunion_id=rid)
    oportunidad = comercial.obtener_oportunidad(g.tenant_id, g.usuario_id, request.args.get("oportunidad_id", type=int)) if request.args.get("oportunidad_id") else None
    return render_template("reunion_nueva.html", r={"cliente_id": request.args.get("cliente_id", type=int), "oportunidad_id": oportunidad["id"] if oportunidad else "",
                                                    "titulo": f"Reunión: {oportunidad['titulo']}" if oportunidad else "", "plantilla": "comercial" if oportunidad else "cliente"},
                           plantillas=reuniones.PLANTILLAS, clientes=_clientes(), hoy=date.today().isoformat(), error=_error())


def _reunion_o_404(reunion_id: int) -> dict:
    r = reuniones.obtener(g.tenant_id, g.usuario_id, reunion_id)
    if r is None:
        abort(404)
    return r


@comercial_bp.route("/reuniones/<int:reunion_id>")
@login_required
def reunion(reunion_id: int):
    r = _reunion_o_404(reunion_id)
    return render_template("reunion_ficha.html", r=r, plantillas=reuniones.PLANTILLAS, equipo=_equipo(), ia_lista=reuniones.configurada(g.usuario_id), error=_error())


def _accion_reunion(reunion_id: int, funcion, ancla: str = ""):
    try:
        funcion()
    except ErrorReunion as e:
        return redirect(url_for("comercial.reunion", reunion_id=reunion_id, error=_(str(e))) + ancla)
    return redirect(url_for("comercial.reunion", reunion_id=reunion_id) + ancla)


@comercial_bp.route("/reuniones/<int:reunion_id>/notas", methods=["POST"])
@login_required
def reunion_notas(reunion_id: int):
    return _accion_reunion(reunion_id, lambda: reuniones.editar(
        g.tenant_id, g.usuario_id, reunion_id, **{c: request.form.get(c) for c in ("titulo", "fecha", "plantilla", "participantes", "notas") if c in request.form}), "#notas")


@comercial_bp.route("/reuniones/<int:reunion_id>/transcripcion", methods=["POST"])
@login_required
def reunion_transcripcion(reunion_id: int):
    return _accion_reunion(reunion_id, lambda: reuniones.guardar_transcripcion(g.tenant_id, g.usuario_id, reunion_id, request.form.get("transcripcion", ""), bool(request.form.get("aviso_grabacion"))),
                           "#transcripcion")


@comercial_bp.route("/reuniones/<int:reunion_id>/transcripcion/borrar", methods=["POST"])
@login_required
def reunion_borrar_transcripcion(reunion_id: int):
    return _accion_reunion(reunion_id, lambda: reuniones.borrar_transcripcion(g.tenant_id, g.usuario_id, reunion_id), "#transcripcion")


@comercial_bp.route("/reuniones/<int:reunion_id>/acta", methods=["POST"])
@login_required
def reunion_acta(reunion_id: int):
    return _accion_reunion(reunion_id, lambda: reuniones.generar_acta(g.tenant_id, g.usuario_id, reunion_id), "#acta")


@comercial_bp.route("/reuniones/<int:reunion_id>/acta/guardar", methods=["POST"])
@login_required
def reunion_guardar_acta(reunion_id: int):
    """Guarda lo que la persona ha editado del acta y, con el botón «Crear las tareas marcadas», crea además las tareas que marcó (con el responsable y la fecha que eligió)."""
    def _guardar():
        lineas = lambda c: [x.strip() for x in request.form.get(c, "").splitlines() if x.strip()]    # noqa: E731
        r = _reunion_o_404(reunion_id)
        tareas = []
        indices = {}                                                  # índice del acta antes de guardar -> índice después (por si se borró alguna)
        for i, t in enumerate((r["acta"] or {}).get("tareas", [])):
            if request.form.get(f"t{i}_borrar"):
                continue
            indices[i] = len(tareas)
            tareas.append({"texto": request.form.get(f"t{i}_texto", t["texto"]), "responsable": t.get("responsable"), "fecha": request.form.get(f"t{i}_fecha") or None, "tarea_id": t.get("tarea_id")})
        if request.form.get("tarea_nueva"):
            tareas.append({"texto": request.form["tarea_nueva"], "responsable": None, "fecha": request.form.get("tarea_nueva_fecha") or None})
        reuniones.guardar_acta(g.tenant_id, g.usuario_id, reunion_id, {"resumen": request.form.get("resumen", ""), "temas": lineas("temas"), "decisiones": lineas("decisiones"),
                                                                       "tareas": tareas, "proximos_pasos": lineas("proximos_pasos")})
        if request.form.get("accion") == "crear":
            elegidas = [{"indice": indices[i], "responsable_id": _int(request.form.get(f"resp_{i}")), "fecha": request.form.get(f"t{i}_fecha") or None}
                        for i in request.form.getlist("crear", type=int) if i in indices]
            reuniones.crear_tareas(g.tenant_id, g.usuario_id, reunion_id, elegidas)
    return _accion_reunion(reunion_id, _guardar, "#acta")


@comercial_bp.route("/reuniones/<int:reunion_id>/papelera", methods=["POST"])
@login_required
def reunion_papelera(reunion_id: int):
    try:
        reuniones.papelera(g.tenant_id, g.usuario_id, reunion_id)
    except ErrorReunion as e:
        return redirect(url_for("comercial.reunion", reunion_id=reunion_id, error=_(str(e))))
    return _volver("comercial.reuniones_lista")
