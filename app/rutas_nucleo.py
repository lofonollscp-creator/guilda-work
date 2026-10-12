"""Pantallas del núcleo común: Clientes, Expedientes, Plazos y Horas (los comparten los módulos de negocio; ver app/nucleo.py y app/verticales.py).
Cuatro blueprints en un fichero porque comparten ayudas. Todo va acotado por el despacho de quien entra; sin despacho no hay nada que ver (404)."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import almacen_documentos, calendario_plazos, db, generador_documentos, nucleo, verticales
from .auth import login_required

clientes_bp = Blueprint("clientes", __name__, url_prefix="/clientes")
expedientes_bp = Blueprint("expedientes", __name__, url_prefix="/expedientes")
plazos_bp = Blueprint("plazos", __name__, url_prefix="/plazos")
tiempo_bp = Blueprint("tiempo", __name__, url_prefix="/tiempo")

POR_PAGINA = 50


@clientes_bp.app_template_filter("importe")
def _importe(centimos) -> str:
    """Céntimos → «1.234,56 €»."""
    texto = f"{(centimos or 0) / 100:,.2f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".") + " €"
ESTADOS_PLAZO = ("abiertos", "vencido", "hoy", "proximo", "en_plazo", "cumplido")


def _tenant() -> int:
    if g.get("tenant_id") is None:
        abort(404)
    return g.tenant_id


def _supervisor() -> bool:
    return bool(g.get("supervisor_tenant") or g.get("es_admin"))


def _error() -> str | None:
    return (request.args.get("error") or "")[:200] or None


def _volver(endpoint: str, error: str | None = None, **valores):
    if error:
        valores["error"] = error[:200]
    return redirect(url_for(endpoint, **valores))


def _entero(valor) -> int | None:
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _lista(texto: str | None) -> list[str]:
    return [e for e in (texto or "").replace(";", ",").split(",") if e.strip()]


# =============================================================================== Clientes
@clientes_bp.route("/")
@login_required
def lista():
    t = _tenant()
    q, etiqueta, tipo = request.args.get("q") or None, request.args.get("etiqueta") or None, request.args.get("tipo") or None
    pagina = max(1, request.args.get("pagina", 1, type=int))
    filas, total = nucleo.listar_clientes(t, q, etiqueta, tipo, limite=POR_PAGINA, pagina=pagina)
    return render_template("clientes_lista.html", clientes=filas, total=total, pagina=pagina, paginas=max(1, -(-total // POR_PAGINA)), q=q or "", etiqueta=etiqueta or "", tipo=tipo or "",
                           etiquetas=nucleo.etiquetas_del_despacho(t), equipo=nucleo.equipo(t), error=_error(), subnav="clientes")


@clientes_bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    t = _tenant()
    datos = {c: (request.form.get(c) or "").strip() for c in ("nombre", "nif", "email", "telefono", "tipo", "idioma", "origen", "notas", "etiquetas", "responsable_id")}
    if request.method == "POST":
        parecidos = nucleo.posibles_duplicados(t, datos["nombre"], datos["nif"], datos["email"])
        if parecidos and not request.form.get("crear_igualmente"):
            return render_template("cliente_nuevo.html", datos=datos, parecidos=parecidos, equipo=nucleo.equipo(t), error=None, subnav="clientes")
        try:
            cid = nucleo.crear_cliente(t, datos["nombre"], tipo=datos["tipo"] or None, nif=datos["nif"], email=datos["email"], telefono=datos["telefono"], idioma=datos["idioma"] or None,
                                       origen=datos["origen"], notas=datos["notas"], responsable_id=_entero(datos["responsable_id"]), etiquetas=_lista(datos["etiquetas"]))
        except ValueError as e:
            return render_template("cliente_nuevo.html", datos=datos, parecidos=[], equipo=nucleo.equipo(t), error=str(e), subnav="clientes"), 400
        return redirect(url_for("clientes.ficha", cliente_id=cid))
    return render_template("cliente_nuevo.html", datos=datos, parecidos=[], equipo=nucleo.equipo(t), error=_error(), subnav="clientes")


@clientes_bp.route("/<int:cliente_id>")
@login_required
def ficha(cliente_id: int):
    t = _tenant()
    c = nucleo.obtener_cliente(t, cliente_id)
    if c is None:
        abort(404)
    exps, _n = nucleo.listar_expedientes(t, g.usuario_id, _supervisor(), cliente_id=cliente_id, limite=50)
    return render_template(
        "cliente_ficha.html", c=c, contactos=nucleo.listar_contactos(t, cliente_id), etiquetas=nucleo.etiquetas_de(cliente_id), expedientes=exps,
        plazos=nucleo.listar_plazos(t, g.usuario_id, _supervisor(), cliente_id=cliente_id, estado="abiertos", limite=20),
        partes=nucleo.listar_partes(t, g.usuario_id, _supervisor(), ver_todo=_supervisor(), cliente_id=cliente_id, limite=10),
        documentos=almacen_documentos.listar(t, g.usuario_id, cliente_id=cliente_id), equipo=nucleo.equipo(t), error=_error(), subnav="clientes",
        tipos=verticales.tipos_expediente(t), hoy=date.today().isoformat(),
        otros=[o for o in nucleo.listar_clientes(t, limite=500)[0] if o["id"] != cliente_id],
    )


@clientes_bp.route("/<int:cliente_id>/editar", methods=["POST"])
@login_required
def editar(cliente_id: int):
    t = _tenant()
    campos = {c: request.form.get(c) for c in ("nombre", "tipo", "nif", "email", "telefono", "direccion", "idioma", "origen", "notas") if c in request.form}
    if "responsable_id" in request.form:
        campos["responsable_id"] = _entero(request.form.get("responsable_id"))
    try:
        nucleo.editar_cliente(t, cliente_id, **campos)
        if "etiquetas" in request.form:
            nucleo.poner_etiquetas(t, cliente_id, _lista(request.form.get("etiquetas")))
    except ValueError as e:
        return _volver("clientes.ficha", str(e), cliente_id=cliente_id)
    return _volver("clientes.ficha", cliente_id=cliente_id)


@clientes_bp.route("/<int:cliente_id>/contactos", methods=["POST"])
@login_required
def anadir_contacto(cliente_id: int):
    f = request.form
    try:
        nucleo.anadir_contacto(_tenant(), cliente_id, f.get("nombre", ""), cargo=f.get("cargo"), email=f.get("email"), telefono=f.get("telefono"), rol=f.get("rol"), principal=bool(f.get("principal")))
    except ValueError as e:
        return _volver("clientes.ficha", str(e), cliente_id=cliente_id)
    return _volver("clientes.ficha", cliente_id=cliente_id)


@clientes_bp.route("/<int:cliente_id>/contactos/<int:contacto_id>/eliminar", methods=["POST"])
@login_required
def eliminar_contacto(cliente_id: int, contacto_id: int):
    nucleo.eliminar_contacto(_tenant(), contacto_id)
    return _volver("clientes.ficha", cliente_id=cliente_id)


@clientes_bp.route("/<int:cliente_id>/papelera", methods=["POST"])
@login_required
def papelera(cliente_id: int):
    try:
        nucleo.papelera_cliente(_tenant(), cliente_id, request.form.get("restaurar") is None)
    except ValueError:
        abort(404)
    return redirect(url_for("clientes.lista"))


@clientes_bp.route("/<int:cliente_id>/fusionar", methods=["POST"])
@login_required
def fusionar(cliente_id: int):
    destino = _entero(request.form.get("destino_id"))
    try:
        if destino is None:
            raise ValueError(_("Elige el cliente con el que quedarte."))
        nucleo.fusionar_clientes(_tenant(), destino, cliente_id)
    except ValueError as e:
        return _volver("clientes.ficha", str(e), cliente_id=cliente_id)
    return _volver("clientes.ficha", cliente_id=destino)


@clientes_bp.route("/<int:cliente_id>/documentos", methods=["POST"])
@login_required
def subir_documento(cliente_id: int):
    return _subir_documento(cliente_id=cliente_id, volver=("clientes.ficha", {"cliente_id": cliente_id}))


@clientes_bp.route("/<int:cliente_id>/documentos/<int:documento_id>")
@login_required
def descargar_documento(cliente_id: int, documento_id: int):
    return _descargar(documento_id, cliente_id=cliente_id)


@clientes_bp.route("/<int:cliente_id>/documentos/<int:documento_id>/eliminar", methods=["POST"])
@login_required
def eliminar_documento(cliente_id: int, documento_id: int):
    almacen_documentos.eliminar(_tenant(), g.usuario_id, documento_id)
    return _volver("clientes.ficha", cliente_id=cliente_id)


def _subir_documento(*, cliente_id: int | None = None, expediente_id: int | None = None, volver: tuple[str, dict]):
    _tenant()
    archivos = [f for f in request.files.getlist("archivo") if f and f.filename]
    if not archivos:
        return _volver(volver[0], _("Elige un archivo."), **volver[1])
    avisos = []
    for f in archivos[:10]:
        r, _id = almacen_documentos.guardar(g.usuario_id, f.filename, f.mimetype, f.read(db.MAX_DOCUMENTO_CLIENTE_BYTES + 1), cliente_id=cliente_id, expediente_id=expediente_id,
                                            categoria=request.form.get("categoria"))
        if r not in ("ok", "duplicado"):
            avisos.append({"vacio": _("Archivo vacío."), "grande": _("Archivo demasiado grande."), "limite": _("Demasiados documentos."), "cliente": _("Cliente no encontrado."),
                           "expediente": _("Expediente no encontrado.")}.get(r, _("No se pudo guardar.")))
    return _volver(volver[0], " ".join(dict.fromkeys(avisos)) or None, **volver[1])


def _descargar(documento_id: int, *, cliente_id: int | None = None, expediente_id: int | None = None):
    d = almacen_documentos.leer(_tenant(), g.usuario_id, documento_id)
    if d is None or (cliente_id is not None and d["cliente_id"] != cliente_id) or (expediente_id is not None and d["expediente_id"] != expediente_id):
        abort(404)
    nombre = d["nombre_archivo"].replace('"', "")
    return Response(d["contenido"], mimetype=d["tipo_mime"], headers={"Content-Disposition": f'attachment; filename="{nombre}"', "X-Content-Type-Options": "nosniff"})


# =============================================================================== Expedientes
@expedientes_bp.route("/")
@login_required
def lista():
    t = _tenant()
    pagina = max(1, request.args.get("pagina", 1, type=int))
    f = {"estado": request.args.get("estado") or None, "tipo": request.args.get("tipo") or None, "q": request.args.get("q") or None,
         "responsable_id": _entero(request.args.get("responsable_id")), "cliente_id": _entero(request.args.get("cliente_id")), "solo_abiertos": request.args.get("abiertos") == "1"}
    filas, total = nucleo.listar_expedientes(t, g.usuario_id, _supervisor(), limite=POR_PAGINA, pagina=pagina, **f)
    return render_template("expedientes_lista.html", expedientes=filas, total=total, pagina=pagina, paginas=max(1, -(-total // POR_PAGINA)), f=f, tipos=verticales.tipos_expediente(t),
                           equipo=nucleo.equipo(t), error=_error(), subnav="expedientes", tipo_de=verticales.tipo_de)


@expedientes_bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    t = _tenant()
    tipos = verticales.tipos_expediente(t)
    cliente_id = _entero(request.values.get("cliente_id"))
    if request.method == "POST":
        f = request.form
        try:
            xid = nucleo.crear_expediente(t, g.usuario_id, cliente_id or 0, f.get("titulo", ""), tipo=f.get("tipo") or "general", referencia=f.get("referencia"), descripcion=f.get("descripcion"),
                                          responsable_id=_entero(f.get("responsable_id")), confidencial=bool(f.get("confidencial")))
            return redirect(url_for("expedientes.ficha", expediente_id=xid))
        except ValueError as e:
            error = str(e)
    else:
        error = _error()
    clientes, _n = nucleo.listar_clientes(t, limite=500)
    return render_template("expediente_nuevo.html", tipos=tipos, clientes=clientes, cliente_id=cliente_id, equipo=nucleo.equipo(t), error=error, datos=request.form, subnav="expedientes")


def _expediente_o_404(expediente_id: int):
    x = nucleo.obtener_expediente(_tenant(), expediente_id, g.usuario_id, _supervisor())
    if x is None:
        abort(404)
    return x


@expedientes_bp.route("/<int:expediente_id>")
@login_required
def ficha(expediente_id: int):
    x = _expediente_o_404(expediente_id)
    t = g.tenant_id
    tipo = verticales.tipo_de(x["tipo"])
    return render_template(
        "expediente_ficha.html", x=x, tipo=tipo, estados=tipo.estados, linea=nucleo.linea_de_tiempo(t, g.usuario_id, expediente_id, _supervisor()), miembros=nucleo.miembros_de(expediente_id),
        plazos=nucleo.listar_plazos(t, g.usuario_id, _supervisor(), expediente_id=expediente_id), partes=nucleo.listar_partes(t, g.usuario_id, _supervisor(), ver_todo=_supervisor(), expediente_id=expediente_id, limite=30),
        documentos=almacen_documentos.listar(t, g.usuario_id, expediente_id=expediente_id), equipo=nucleo.equipo(t), error=_error(), subnav="expedientes", hoy=date.today().isoformat(),
        horas=nucleo.resumen_horas(t, g.usuario_id, _supervisor(), ver_todo=_supervisor(), agrupar="expediente", expediente_id=expediente_id),
    )


def _accion_expediente(expediente_id: int, f):
    try:
        f()
    except ValueError as e:
        return _volver("expedientes.ficha", str(e), expediente_id=expediente_id)
    return _volver("expedientes.ficha", expediente_id=expediente_id)


@expedientes_bp.route("/<int:expediente_id>/estado", methods=["POST"])
@login_required
def estado(expediente_id: int):
    return _accion_expediente(expediente_id, lambda: nucleo.cambiar_estado_expediente(_tenant(), g.usuario_id, expediente_id, request.form.get("estado", ""), _supervisor()))


@expedientes_bp.route("/<int:expediente_id>/responsable", methods=["POST"])
@login_required
def responsable(expediente_id: int):
    return _accion_expediente(expediente_id, lambda: nucleo.asignar_expediente(_tenant(), g.usuario_id, expediente_id, _entero(request.form.get("responsable_id")) or 0, _supervisor()))


@expedientes_bp.route("/<int:expediente_id>/nota", methods=["POST"])
@login_required
def nota(expediente_id: int):
    return _accion_expediente(expediente_id, lambda: nucleo.anotar_expediente(_tenant(), g.usuario_id, expediente_id, request.form.get("texto", ""), _supervisor()))


@expedientes_bp.route("/<int:expediente_id>/editar", methods=["POST"])
@login_required
def editar(expediente_id: int):
    campos = {c: request.form.get(c) for c in ("titulo", "referencia", "descripcion") if c in request.form}
    if "confidencial_presente" in request.form:
        campos["confidencial"] = bool(request.form.get("confidencial"))
    return _accion_expediente(expediente_id, lambda: nucleo.editar_expediente(_tenant(), g.usuario_id, expediente_id, _supervisor(), **campos))


@expedientes_bp.route("/<int:expediente_id>/miembros", methods=["POST"])
@login_required
def miembros(expediente_id: int):
    miembro = _entero(request.form.get("usuario_id")) or 0
    if request.form.get("quitar"):
        return _accion_expediente(expediente_id, lambda: nucleo.quitar_miembro(_tenant(), g.usuario_id, expediente_id, miembro, _supervisor()))
    return _accion_expediente(expediente_id, lambda: nucleo.anadir_miembro(_tenant(), g.usuario_id, expediente_id, miembro, _supervisor()))


@expedientes_bp.route("/<int:expediente_id>/papelera", methods=["POST"])
@login_required
def papelera(expediente_id: int):
    _expediente_o_404(expediente_id)
    nucleo.papelera_expediente(g.tenant_id, g.usuario_id, expediente_id, _supervisor())
    return redirect(url_for("expedientes.lista"))


@expedientes_bp.route("/<int:expediente_id>/plazos", methods=["POST"])
@login_required
def anadir_plazo(expediente_id: int):
    _expediente_o_404(expediente_id)
    f = request.form
    return _accion_expediente(expediente_id, lambda: nucleo.crear_plazo(g.tenant_id, g.usuario_id, f.get("titulo", ""), f.get("fecha_limite", ""), expediente_id=expediente_id, critico=bool(f.get("critico")),
                                                                         avisos=f.get("avisos") or "7,3,1", responsable_id=_entero(f.get("responsable_id")), supervisor=_supervisor()))


@expedientes_bp.route("/<int:expediente_id>/horas", methods=["POST"])
@login_required
def anadir_horas(expediente_id: int):
    _expediente_o_404(expediente_id)
    f = request.form
    return _accion_expediente(expediente_id, lambda: nucleo.registrar_parte(g.tenant_id, g.usuario_id, f.get("descripcion", ""), minutos=_minutos(f), fecha=f.get("fecha") or None,
                                                                             expediente_id=expediente_id, facturable=bool(f.get("facturable")), supervisor=_supervisor()))


@expedientes_bp.route("/<int:expediente_id>/documentos", methods=["POST"])
@login_required
def subir_documento(expediente_id: int):
    return _subir_documento(expediente_id=expediente_id, volver=("expedientes.ficha", {"expediente_id": expediente_id}))


@expedientes_bp.route("/<int:expediente_id>/documentos/<int:documento_id>")
@login_required
def descargar_documento(expediente_id: int, documento_id: int):
    return _descargar(documento_id, expediente_id=expediente_id)


@expedientes_bp.route("/<int:expediente_id>/documentos/<int:documento_id>/eliminar", methods=["POST"])
@login_required
def eliminar_documento(expediente_id: int, documento_id: int):
    almacen_documentos.eliminar(_tenant(), g.usuario_id, documento_id)
    return _volver("expedientes.ficha", expediente_id=expediente_id)


def _minutos(f) -> float:
    """Tiempo de un formulario: «horas» y «minutos» sueltos (1 h 30 min) o, si no, un total en minutos."""
    try:
        return float(f.get("horas") or 0) * 60 + float(f.get("minutos") or 0)
    except ValueError:
        raise ValueError(_("El tiempo no es válido.")) from None


# =============================================================================== Plazos
@plazos_bp.route("/")
@login_required
def lista():
    t = _tenant()
    estado = request.args.get("estado") if request.args.get("estado") in ESTADOS_PLAZO else "abiertos"
    solo_mios = request.args.get("mios") == "1"
    plazos = nucleo.listar_plazos(t, g.usuario_id, _supervisor(), estado=estado, responsable_id=g.usuario_id if solo_mios else None)
    return render_template("plazos_lista.html", plazos=plazos, estado=estado, solo_mios=solo_mios, equipo=nucleo.equipo(t), error=_error(), subnav="plazos", hoy=date.today().isoformat(),
                           clientes=nucleo.listar_clientes(t, limite=500)[0], expedientes=nucleo.listar_expedientes(t, g.usuario_id, _supervisor(), solo_abiertos=True, limite=500)[0])


@plazos_bp.route("/", methods=["POST"])
@login_required
def crear():
    f = request.form
    try:
        nucleo.crear_plazo(_tenant(), g.usuario_id, f.get("titulo", ""), f.get("fecha_limite", ""), expediente_id=_entero(f.get("expediente_id")), cliente_id=_entero(f.get("cliente_id")),
                           critico=bool(f.get("critico")), avisos=f.get("avisos") or "7,3,1", responsable_id=_entero(f.get("responsable_id")), supervisor=_supervisor())
    except ValueError as e:
        return _volver("plazos.lista", str(e))
    return _volver("plazos.lista")


def _accion_plazo(f):
    try:
        f()
    except ValueError as e:
        return _volver("plazos.lista", str(e))
    destino = request.form.get("volver_expediente", type=int)
    return redirect(url_for("expedientes.ficha", expediente_id=destino)) if destino else _volver("plazos.lista")


@plazos_bp.route("/<int:plazo_id>/cumplido", methods=["POST"])
@login_required
def cumplido(plazo_id: int):
    return _accion_plazo(lambda: nucleo.marcar_cumplido(_tenant(), g.usuario_id, plazo_id, request.form.get("reabrir") is None))


@plazos_bp.route("/<int:plazo_id>/revisar", methods=["POST"])
@login_required
def revisar(plazo_id: int):
    return _accion_plazo(lambda: nucleo.revisar_plazo(_tenant(), g.usuario_id, plazo_id))


@plazos_bp.route("/<int:plazo_id>/mover", methods=["POST"])
@login_required
def mover(plazo_id: int):
    return _accion_plazo(lambda: nucleo.mover_plazo(_tenant(), g.usuario_id, plazo_id, request.form.get("fecha_limite", "")))


@plazos_bp.route("/<int:plazo_id>/eliminar", methods=["POST"])
@login_required
def eliminar(plazo_id: int):
    return _accion_plazo(lambda: nucleo.eliminar_plazo(_tenant(), g.usuario_id, plazo_id))


@plazos_bp.route("/festivos", methods=["GET", "POST"])
@login_required
def festivos():
    t = _tenant()
    error = _error()
    if request.method == "POST":
        if not _supervisor():
            abort(403)
        try:
            if request.form.get("eliminar"):
                nucleo.eliminar_festivo(t, _entero(request.form.get("eliminar")) or 0)
            else:
                nucleo.anadir_festivo(t, request.form.get("fecha", ""), request.form.get("nombre", ""))
        except ValueError as e:
            return _volver("plazos.festivos", str(e))
        return _volver("plazos.festivos")
    anio = request.args.get("anio", date.today().year, type=int)
    return render_template("plazos_festivos.html", festivos=nucleo.listar_festivos(t, anio), anio=anio, nacionales=sorted(calendario_plazos.festivos_nacionales(anio).items()),
                           puede_editar=_supervisor(), error=error, subnav="plazos")


# =============================================================================== Horas
def _rango(f) -> tuple[str | None, str | None]:
    return f.get("desde") or None, f.get("hasta") or None


@tiempo_bp.route("/")
@login_required
def lista():
    t = _tenant()
    ver_todo = _supervisor() and request.args.get("equipo") == "1"
    desde, hasta = _rango(request.args)
    if not desde and not hasta:
        desde = date.today().replace(day=1).isoformat()
    filtros = {"desde": desde, "hasta": hasta, "cliente_id": _entero(request.args.get("cliente_id")), "persona_id": _entero(request.args.get("persona_id")) if ver_todo else None}
    agrupar = request.args.get("agrupar") if request.args.get("agrupar") in ("cliente", "usuario", "expediente") else "cliente"
    try:
        partes = nucleo.listar_partes(t, g.usuario_id, _supervisor(), ver_todo=ver_todo, **filtros)
        resumen = nucleo.resumen_horas(t, g.usuario_id, _supervisor(), ver_todo=ver_todo, agrupar=agrupar, bloque_minutos=request.args.get("bloque", 0, type=int), **filtros)
    except ValueError as e:
        partes, resumen = [], []
        error = str(e)
    else:
        error = _error()
    return render_template("tiempo_lista.html", partes=partes, resumen=resumen, ver_todo=ver_todo, agrupar=agrupar, desde=desde or "", hasta=hasta or "", filtros=filtros, es_supervisor=_supervisor(),
                           clientes=nucleo.listar_clientes(t, limite=500)[0], expedientes=nucleo.listar_expedientes(t, g.usuario_id, _supervisor(), solo_abiertos=True, limite=500)[0],
                           equipo=nucleo.equipo(t), total_segundos=sum(p["segundos"] for p in partes), total_importe=sum(p["importe_centimos"] for p in partes), error=error, subnav="tiempo",
                           hoy=date.today().isoformat(), tarifa=nucleo.tarifa_de(g.usuario_id))


@tiempo_bp.route("/", methods=["POST"])
@login_required
def registrar():
    f = request.form
    try:
        nucleo.registrar_parte(_tenant(), g.usuario_id, f.get("descripcion", ""), minutos=_minutos(f), fecha=f.get("fecha") or None, cliente_id=_entero(f.get("cliente_id")),
                               expediente_id=_entero(f.get("expediente_id")), facturable=bool(f.get("facturable")), supervisor=_supervisor())
    except ValueError as e:
        return _volver("tiempo.lista", str(e))
    return _volver("tiempo.lista")


@tiempo_bp.route("/<int:parte_id>/eliminar", methods=["POST"])
@login_required
def eliminar(parte_id: int):
    nucleo.eliminar_parte(_tenant(), g.usuario_id, parte_id, _supervisor())
    return _volver("tiempo.lista")


@tiempo_bp.route("/tarifa", methods=["POST"])
@login_required
def tarifa():
    t = _tenant()
    try:
        euros = (request.form.get("tarifa") or "").replace(",", ".").strip()
        nucleo.fijar_tarifa_usuario(t, g.usuario_id, int(round(float(euros) * 100)) if euros else None)
    except ValueError:
        return _volver("tiempo.lista", _("La tarifa no es válida."))
    return _volver("tiempo.lista")


@tiempo_bp.route("/facturar", methods=["POST"])
@login_required
def facturar():
    if not _supervisor():
        abort(403)
    ids = [i for i in (_entero(x) for x in request.form.getlist("parte_id")) if i]
    nucleo.marcar_facturado(_tenant(), ids)
    return _volver("tiempo.lista", equipo=1)


def _filas_hoja(t: int):
    ver_todo = _supervisor() and request.args.get("equipo") == "1"
    desde, hasta = _rango(request.args)
    partes = nucleo.listar_partes(t, g.usuario_id, _supervisor(), ver_todo=ver_todo, desde=desde, hasta=hasta, cliente_id=_entero(request.args.get("cliente_id")), limite=2000)
    cols = [_("Fecha"), _("Persona"), _("Cliente"), _("Expediente"), _("Descripción"), _("Horas"), _("Facturable"), _("Importe (€)")]
    filas = [[p["fecha"], p["usuario_nombre"], p["cliente_nombre"] or "", p["expediente_titulo"] or "", p["descripcion"], f"{p['segundos'] / 3600:.2f}", _("Sí") if p["facturable"] else _("No"),
              f"{p['importe_centimos'] / 100:.2f}"] for p in partes]
    return cols, filas, desde, hasta


@tiempo_bp.route("/hoja.csv")
@login_required
def hoja_csv():
    cols, filas, _d, _h = _filas_hoja(_tenant())
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow(cols)
    for fila in filas:
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in fila])     # Excel no debe interpretar un texto como fórmula
    return Response("﻿" + salida.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=hoja_de_horas.csv"})


@tiempo_bp.route("/hoja.pdf")
@login_required
def hoja_pdf():
    cols, filas, desde, hasta = _filas_hoja(_tenant())
    pdf = generador_documentos.tabla_a_pdf(_("Hoja de horas"), cols, filas, notas=f"{_('Periodo')}: {desde or _('inicio')} – {hasta or _('hoy')}")
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=hoja_de_horas.pdf"})
