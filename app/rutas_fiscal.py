"""Rutas del "Calendario fiscal": clientes fiscales y sus vencimientos
(modelos 303/390/130/111/115/200...) por tenant. Vive en su propio
Blueprint, mismo patrón que app/rutas_tareas.py.

A diferencia de tareas/notas/categorías (que se filtran por g.usuario_id,
propiedad de un miembro concreto del equipo), esto son datos de la
GESTORÍA -- se filtran por g.tenant_id en cada consulta a db.py. Es
autoservicio por tenant, sin pantallas de backoffice: cualquier usuario
con tenant asignado puede gestionar los clientes fiscales y vencimientos
de SU tenant."""
from datetime import date

from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from flask_babel import lazy_gettext as _l

from . import db
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


@fiscal_bp.route("/clientes")
@login_required
def clientes():
    return render_template("fiscal_clientes.html", clientes=db.listar_clientes_fiscales(g.tenant_id))


@fiscal_bp.route("/clientes", methods=["POST"])
@login_required
def crear_cliente():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        db.crear_cliente_fiscal(g.tenant_id, nombre, nif=request.form.get("nif"), notas=request.form.get("notas"))
    return redirect(url_for("fiscal.clientes"))


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
            )
        return redirect(url_for("fiscal.clientes"))
    return render_template("fiscal_cliente_editar.html", cliente=cliente)


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

    modelos_disponibles = {**MODELOS_TRIMESTRALES, **MODELOS_ANUALES}

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

    modelos_pedidos = request.args.getlist("modelo") or list(modelos_disponibles.keys())
    anio = request.args.get("anio", type=int) or date.today().year
    propuestas = generar_vencimientos_propuestos(modelos_pedidos, anio)
    return render_template(
        "fiscal_generar_vencimientos.html",
        cliente=cliente, propuestas=propuestas, anio=anio,
        modelos_disponibles=modelos_disponibles, modelos_pedidos=modelos_pedidos,
    )


@fiscal_bp.route("/vencimientos")
@login_required
def vencimientos():
    estado = request.args.get("estado") or None
    cliente_fiscal_id = request.args.get("cliente_id", type=int)
    return render_template(
        "fiscal_vencimientos.html",
        vencimientos=db.listar_vencimientos_fiscales(g.tenant_id, estado=estado, cliente_fiscal_id=cliente_fiscal_id),
        clientes=db.listar_clientes_fiscales(g.tenant_id),
        estados=ESTADOS_VENCIMIENTO,
        filtro_estado=estado,
        filtro_cliente_id=cliente_fiscal_id,
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
