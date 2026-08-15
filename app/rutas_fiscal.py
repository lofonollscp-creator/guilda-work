"""Rutas del "Calendario fiscal": clientes fiscales y sus vencimientos
(modelos 303/390/130/111/115/200...) por tenant. Vive en su propio
Blueprint, mismo patrón que app/rutas_tareas.py.

A diferencia de tareas/notas/categorías (que se filtran por g.usuario_id,
propiedad de un miembro concreto del equipo), esto son datos de la
GESTORÍA -- se filtran por g.tenant_id en cada consulta a db.py. Es
autoservicio por tenant, sin pantallas de backoffice: cualquier usuario
con tenant asignado puede gestionar los clientes fiscales y vencimientos
de SU tenant."""
import csv
import io
import json
from datetime import date, timedelta

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import lazy_gettext as _l

from . import db, espocrm
from .auth import login_required
from .vencimientos_fiscales import MODELOS_ANUALES, MODELOS_TRIMESTRALES, generar_vencimientos_propuestos

fiscal_bp = Blueprint("fiscal", __name__, url_prefix="/fiscal")

ESTADOS_VENCIMIENTO = [
    ("pendiente", _l("Pendiente")),
    ("presentado", _l("Presentado")),
    ("fuera_plazo", _l("Fuera de plazo")),
]


@fiscal_bp.before_request
def _exigir_tenant():
    # Un blueprint before_request corre ANTES que @login_required de la
    # vista -- si abortáramos aquí para cualquier g.tenant_id None,
    # un visitante sin sesión (g.usuario_id también None) recibiría un 403
    # en seco en vez del redirect a /login habitual. Dejar pasar cuando no
    # hay sesión: login_required se encarga de esa parte tal cual siempre.
    if g.usuario_id is not None and g.tenant_id is None:
        abort(403)


MODELOS_DISPONIBLES = {**MODELOS_TRIMESTRALES, **MODELOS_ANUALES}


@fiscal_bp.route("/clientes")
@login_required
def clientes():
    q = request.args.get("q") or None
    return render_template("fiscal_clientes.html", clientes=db.listar_clientes_fiscales(g.tenant_id, q=q), filtro_q=q)


@fiscal_bp.route("/clientes", methods=["POST"])
@login_required
def crear_cliente():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        cliente_id = db.crear_cliente_fiscal(
            g.tenant_id, nombre, nif=request.form.get("nif"), notas=request.form.get("notas"),
            modelos_fiscales=request.form.getlist("modelos_fiscales") or None,
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
    return render_template(
        "fiscal_cliente_detalle.html",
        cliente=cliente,
        modelos_cliente=db.modelos_fiscales_de_cliente(cliente),
        modelos_disponibles=MODELOS_DISPONIBLES,
        vencimientos=db.listar_vencimientos_fiscales(g.tenant_id, cliente_fiscal_id=cliente_id),
        hoy=date.today().isoformat(),
        limite_proximo=(date.today() + timedelta(days=7)).isoformat(),
    )


@fiscal_bp.route("/clientes/<int:cliente_id>/espocrm")
@login_required
def ver_en_espocrm(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None or not cliente["espocrm_cuenta_id"]:
        abort(404)
    return redirect(espocrm.url_cuenta(cliente["espocrm_cuenta_id"]))


@fiscal_bp.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required
def editar_cliente(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404)
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if nombre:
            db.editar_cliente_fiscal(
                g.tenant_id, cliente_id,
                nombre=nombre, nif=request.form.get("nif"), notas=request.form.get("notas"),
                modelos_fiscales=db.serializar_modelos_fiscales(request.form.getlist("modelos_fiscales") or None),
                generacion_automatica=1 if request.form.get("generacion_automatica") else 0,
            )
        return redirect(url_for("fiscal.clientes"))
    return render_template(
        "fiscal_cliente_editar.html",
        cliente=cliente, modelos_cliente=db.modelos_fiscales_de_cliente(cliente), modelos_disponibles=MODELOS_DISPONIBLES,
    )


@fiscal_bp.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
@login_required
def eliminar_cliente(cliente_id: int):
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404)
    db.eliminar_cliente_fiscal(g.tenant_id, cliente_id)
    return redirect(url_for("fiscal.clientes"))


@fiscal_bp.route("/clientes/<int:cliente_id>/generar-vencimientos", methods=["GET", "POST"])
@login_required
def generar_vencimientos(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404)

    modelos_disponibles = MODELOS_DISPONIBLES

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
    propuestas = generar_vencimientos_propuestos(modelos_pedidos, anio)
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
            for p in generar_vencimientos_propuestos(modelos, anio):
                db.crear_vencimiento_fiscal(g.tenant_id, cliente["id"], p["modelo"], p["periodo"], p["fecha_limite"])
                creados += 1
        return redirect(url_for("fiscal.vencimientos"))

    anio = request.args.get("anio", type=int) or date.today().year
    previa = [
        {"cliente": cliente, "propuestas": generar_vencimientos_propuestos(modelos, anio)}
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
    )
    datos = [
        {
            "cliente": v["cliente_nombre"], "modelo": v["modelo"], "periodo": v["periodo"],
            "fecha_limite": v["fecha_limite"][:10], "estado": v["estado"], "notas": v["notas"],
        }
        for v in filas
    ]
    return Response(json.dumps(datos, ensure_ascii=False, indent=2), mimetype="application/json")


@fiscal_bp.route("/vencimientos")
@login_required
def vencimientos():
    estado = request.args.get("estado") or None
    cliente_fiscal_id = request.args.get("cliente_id", type=int)
    # desde/hasta: usados por el enlace de la tarjeta del dashboard
    # ("Vencimientos próximos", próximos 30 días) -- opcionales, sin ellos
    # se ve el listado completo como siempre.
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    return render_template(
        "fiscal_vencimientos.html",
        vencimientos=db.listar_vencimientos_fiscales(
            g.tenant_id, estado=estado, cliente_fiscal_id=cliente_fiscal_id, desde=desde, hasta=hasta,
        ),
        clientes=db.listar_clientes_fiscales(g.tenant_id),
        estados=ESTADOS_VENCIMIENTO,
        filtro_estado=estado,
        filtro_cliente_id=cliente_fiscal_id,
        # Para pintar en rojo lo pendiente ya vencido sin esperar a que pase
        # el cron de saneo (app/vencimientos_fiscales.py) que marca
        # fuera_plazo -- ese cron corre una vez al día, esto se ve al
        # instante en cuanto la fecha pasa. limite_proximo: a partir de qué
        # fecha ya no se pinta en ámbar (más de 7 días vista, color neutro).
        hoy=date.today().isoformat(),
        limite_proximo=(date.today() + timedelta(days=7)).isoformat(),
    )


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/presentado", methods=["POST"])
@login_required
def marcar_presentado(vencimiento_id: int):
    if db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id) is None:
        abort(404)
    db.marcar_presentado_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    return redirect(request.referrer or url_for("fiscal.vencimientos"))


@fiscal_bp.route("/vencimientos/<int:vencimiento_id>/editar", methods=["GET", "POST"])
@login_required
def editar_vencimiento(vencimiento_id: int):
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404)
    if request.method == "POST":
        usuario_id = request.form.get("usuario_id", type=int)
        db.editar_vencimiento_fiscal(
            g.tenant_id, vencimiento_id,
            modelo=request.form.get("modelo", vencimiento["modelo"]).strip(),
            periodo=request.form.get("periodo", vencimiento["periodo"]).strip(),
            fecha_limite=request.form.get("fecha_limite", vencimiento["fecha_limite"]),
            estado=request.form.get("estado", vencimiento["estado"]),
            notas=request.form.get("notas"),
            usuario_id=usuario_id if usuario_id else None,
        )
        return redirect(url_for("fiscal.vencimientos"))
    usuarios_tenant = [db.obtener_usuario(uid) for uid in db.usuarios_de_tenant(g.tenant_id)]
    return render_template(
        "fiscal_vencimiento_editar.html",
        vencimiento=vencimiento, estados=ESTADOS_VENCIMIENTO, usuarios=usuarios_tenant,
    )


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
