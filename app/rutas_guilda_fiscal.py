"""Guilda Fiscal (web): cartera de titulares, perfil fiscal, apuntes aprobados, periodos y declaraciones del 303 (ver app/fiscal_nucleo.py y app/fiscal_perfiles.py). Aprueba la dirección del despacho o el revisor
fiscal; el resto de la gestoría ve y prepara. Guilda Work no presenta: genera el fichero y anota que se presentó.

(«/fiscal» ya es el calendario fiscal: esto vive en «/guilda-fiscal».)"""
from __future__ import annotations

from datetime import date
from urllib.parse import quote

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from . import acceso, db, facturas_contables as fc, fiscal_nucleo as fn, fiscal_perfiles as fp, verticales
from .auth import login_required
from .fiscal_modelos.apuntes import Apunte
from .fiscal_perfiles import ErrorFiscal

guilda_fiscal_bp = Blueprint("guilda_fiscal", __name__, url_prefix="/guilda-fiscal")

PERIODOS = ("1T", "2T", "3T", "4T")
CLAVES_EXPEDIDAS = (("01", "01 · Régimen general"), ("11", "11 · Arrendamiento de local (sin retención)"), ("12", "12 · Arrendamiento de local (con retención)"), ("13", "13 · Arrendamiento de local (mixto)"),
                    ("02", "02 · Exportación"), ("15", "15 · Tracto sucesivo"), ("03", "03 · Bienes usados / arte"), ("05", "05 · Agencias de viaje"))
CLAVES_RECIBIDAS = (("01", "01 · Régimen general"), ("12", "12 · Arrendamiento de local"), ("09", "09 · Adquisición intracomunitaria"))
TIPOS_FACTURA = ("F1", "F2", "F3", "F4", "F5", "F6", "R1", "R2", "R3", "R4", "R5", "AJ", "LC")
CALIFICACIONES = (("S1", "S1 · Sujeta y no exenta"), ("S2", "S2 · Sujeta con inversión del sujeto pasivo"), ("N1", "N1 · No sujeta (art. 7, 14)"), ("N2", "N2 · No sujeta por localización"), ("", "—"))
EXENCIONES = (("", "—"), ("E1", "E1 · Art. 20"), ("E2", "E2 · Art. 21"), ("E3", "E3 · Art. 22"), ("E4", "E4 · Art. 23-24"), ("E5", "E5 · Art. 25 (entrega intracomunitaria)"), ("E6", "E6 · Otras"))


@guilda_fiscal_bp.before_request
def _solo_con_el_modulo():
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "fiscal"):
        abort(404)
    if request.method not in ("GET", "HEAD", "OPTIONS") and g.get("usuario_id") is not None and acceso.es_solo_auditor(g.tenant_id, g.usuario_id):
        abort(403)


@guilda_fiscal_bp.context_processor
def _plantilla():
    return {"puede_aprobar": bool(g.get("usuario_id") and g.get("tenant_id") and acceso.puede_autorizar(g.tenant_id, g.usuario_id)), "etiqueta_casilla": fn.etiqueta_casilla}


def _atras(destino: str, error) -> Response:
    return redirect(f"{destino}{'&' if '?' in destino else '?'}error={quote(str(error)[:300])}")


def _error() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _euros(texto: str) -> int:
    """«-1.234,56» → céntimos con signo (las rectificativas llevan importes negativos)."""
    texto = (texto or "").strip()
    negativo = texto.startswith("-")
    n = fc.importe_a_centimos(texto.lstrip("-+ "))
    return -n if negativo else n


def _cliente_o_404(cliente_id: int) -> dict:
    if not acceso.puede_ver_cliente(g.tenant_id, g.usuario_id, cliente_id):
        abort(404)
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT id, nombre, nif FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_id, g.tenant_id)).fetchone()
    finally:
        conn.close()
    if not c:
        abort(404)
    return dict(c)


@guilda_fiscal_bp.route("/")
@login_required
def cartera():
    return render_template("fiscal_cartera.html", filas=fn.resumen_cartera(g.tenant_id, g.usuario_id), error=_error())


@guilda_fiscal_bp.route("/<int:cliente_id>")
@login_required
def cliente(cliente_id: int):
    c = _cliente_o_404(cliente_id)
    ejercicio = request.args.get("ejercicio", date.today().year, type=int)
    return render_template("fiscal_cliente.html", c=c, ejercicio=ejercicio, perfil=fp.perfil_en(g.tenant_id, cliente_id, date.today().isoformat()),
                           apuntes=fn.listar_apuntes(g.tenant_id, g.usuario_id, cliente_id, ejercicio=ejercicio), declaraciones=fn.listar_declaraciones(g.tenant_id, g.usuario_id, cliente_id),
                           periodos=PERIODOS, por_registrar=fn.facturas_por_registrar(g.tenant_id, g.usuario_id, cliente_id, ejercicio), error=_error())


def _opciones_perfil() -> dict:
    return {"formas": fp.FORMAS_JURIDICAS, "residencias": fp.RESIDENCIAS, "territorios": fp.TERRITORIOS_IVA, "regimenes": fp.REGIMENES_IVA, "periodicidades": fp.PERIODICIDADES, "banderas": fp.BANDERAS}


@guilda_fiscal_bp.route("/<int:cliente_id>/perfil", methods=["GET", "POST"])
@login_required
def perfil(cliente_id: int):
    c = _cliente_o_404(cliente_id)
    actual = fp.perfil_en(g.tenant_id, cliente_id, date.today().isoformat())
    if request.method == "POST":
        datos = {k: request.form.get(k, "") for k in ("forma_juridica", "residencia", "pais", "territorio_iva", "regimen_iva", "periodicidad", "notas")}
        datos.update({k: request.form.get(k) for k in fp.BANDERAS})
        try:
            datos["prorrata_centesimas"] = fc.porcentaje_a_centesimas(request.form["prorrata"]) if request.form.get("prorrata", "").strip() else None
            datos["saldo_a_compensar_centimos"] = fc.importe_a_centimos(request.form.get("saldo_a_compensar", "0") or "0")
            fp.guardar_perfil(g.tenant_id, g.usuario_id, cliente_id, datos, vigente_desde=request.form.get("vigente_desde"))
        except (ErrorFiscal, ValueError) as e:
            return render_template("fiscal_perfil.html", c=c, perfil=datos, f=request.form, opciones=_opciones_perfil(), error=str(e)), 400
        return redirect(url_for("guilda_fiscal.cliente", cliente_id=cliente_id))
    return render_template("fiscal_perfil.html", c=c, perfil=actual or {}, f={}, opciones=_opciones_perfil(), error=_error())


def _apunte_del_formulario() -> tuple[Apunte, str | None]:
    f = request.form
    fecha = lambda k: date.fromisoformat(f[k]) if f.get(k) else None          # noqa: E731
    base = _euros(f.get("base", ""))
    tipo = fc.porcentaje_a_centesimas(f.get("tipo_iva", "") or "0")
    cuota = _euros(f["cuota"]) if f.get("cuota", "").strip() else (1 if base >= 0 else -1) * ((abs(base) * tipo + 5000) // 10000)
    deduccion = None
    if f.get("deducible_periodo_posterior") and f.get("periodo_deduccion"):
        ej, per = f["periodo_deduccion"].split("-")
        deduccion = (int(ej), per)
    e = f["libro"] == "E"
    return Apunte(libro=f["libro"], tipo_factura=f.get("tipo_factura", "F1"), fecha_expedicion=date.fromisoformat(f["fecha_expedicion"]), numero=f.get("numero", "").strip(), serie=f.get("serie", "").strip(),
                  clave=f.get("clave", "01"), base=base, tipo_iva=tipo, cuota=cuota, total=_euros(f["total"]) if f.get("total", "").strip() else None, fecha_operacion=fecha("fecha_operacion"),
                  contraparte_nombre=f.get("contraparte_nombre", "").strip(), contraparte_nif=f.get("contraparte_nif", "").strip().upper().replace(" ", ""),
                  contraparte_nif_tipo=f.get("contraparte_nif_tipo", ""), contraparte_pais=f.get("contraparte_pais", "").strip().upper(), calificacion=f.get("calificacion", "S1") if e else "",
                  exenta=f.get("exenta", "") if e else "", fecha_recepcion=None if e else fecha("fecha_recepcion"), isp=bool(f.get("isp")), bien_inversion=bool(f.get("bien_inversion")),
                  cuota_deducible=_euros(f["cuota_deducible"]) if f.get("cuota_deducible", "").strip() else None, deducible_periodo_posterior=bool(f.get("deducible_periodo_posterior")),
                  periodo_deduccion=deduccion, inmueble_situacion=f.get("inmueble_situacion", ""), inmueble_referencia=f.get("inmueble_referencia", "").strip().upper()), (f.get("causa") or None)


def _plantilla_apunte(c: dict, datos: dict, apunte_id: int | None, error: str | None, estado: int = 200):
    return render_template("fiscal_apunte.html", c=c, datos=datos, apunte_id=apunte_id, tipos=TIPOS_FACTURA, claves_e=CLAVES_EXPEDIDAS, claves_r=CLAVES_RECIBIDAS, calificaciones=CALIFICACIONES,
                           exenciones=EXENCIONES, error=error), estado


def _euros_texto(centimos: int | None) -> str:
    return "" if centimos is None else f"{centimos / 100:.2f}".replace(".", ",")


@guilda_fiscal_bp.route("/<int:cliente_id>/apuntes/nuevo", methods=["GET", "POST"])
@login_required
def apunte_nuevo(cliente_id: int):
    c = _cliente_o_404(cliente_id)
    if request.method == "POST":
        try:
            apunte, causa = _apunte_del_formulario()
            fn.aprobar_apunte(g.tenant_id, g.usuario_id, cliente_id, apunte, causa=causa, factura_id=request.form.get("factura_id", type=int))
        except (ErrorFiscal, ValueError, KeyError) as e:
            return _plantilla_apunte(c, request.form.to_dict(), None, str(e), 400)
        return redirect(url_for("guilda_fiscal.cliente", cliente_id=cliente_id, ejercicio=apunte.fecha_expedicion.year))
    datos = {"libro": request.args.get("libro", "E"), "tipo_factura": "F1", "clave": "01", "calificacion": "S1", "tipo_iva": "21"}
    factura_id, n = request.args.get("factura_id", type=int), request.args.get("n", 1, type=int)
    if factura_id:                                                       # propuesta a partir de una factura ya anotada: se revisa y se aprueba aquí
        try:
            p = fn.proponer_desde_factura(g.tenant_id, g.usuario_id, factura_id)[max(n - 1, 0)]
        except (ErrorFiscal, IndexError) as e:
            return _atras(url_for("guilda_fiscal.cliente", cliente_id=cliente_id), e)
        datos.update({"libro": p["libro"], "tipo_factura": p["tipo_factura"], "numero": p["numero"], "fecha_expedicion": p["fecha_expedicion"], "fecha_recepcion": p["fecha_recepcion"] or "",
                      "base": _euros_texto(p["base_centimos"]), "tipo_iva": f"{p['tipo_iva_centesimas'] / 100:g}".replace(".", ","), "contraparte_nombre": p["contraparte_nombre"],
                      "contraparte_nif": p["contraparte_nif"], "factura_id": factura_id, "calificacion": p["calificacion"] if p["libro"] == "E" else ""})
    return _plantilla_apunte(c, datos, None, _error())


@guilda_fiscal_bp.route("/<int:cliente_id>/apuntes/<int:apunte_id>", methods=["GET", "POST"])
@login_required
def apunte_ver(cliente_id: int, apunte_id: int):
    c = _cliente_o_404(cliente_id)
    fila = next((a for a in fn.listar_apuntes(g.tenant_id, g.usuario_id, cliente_id, incluir_anulados=True) if a["id"] == apunte_id), None)
    if not fila:
        abort(404)
    if request.method == "POST":
        try:
            apunte, causa = _apunte_del_formulario()
            fn.aprobar_apunte(g.tenant_id, g.usuario_id, cliente_id, apunte, causa=causa, apunte_id=apunte_id, version=request.form.get("version", type=int))
        except (ErrorFiscal, ValueError, KeyError) as e:
            return _plantilla_apunte(c, request.form.to_dict(), apunte_id, str(e), 400)
        return redirect(url_for("guilda_fiscal.cliente", cliente_id=cliente_id, ejercicio=apunte.fecha_expedicion.year))
    datos = dict(fila)
    datos.update({"base": _euros_texto(fila["base_centimos"]), "cuota": _euros_texto(fila["cuota_centimos"]), "tipo_iva": f"{fila['tipo_iva_centesimas'] / 100:g}".replace(".", ","),
                  "total": _euros_texto(fila["total_centimos"]), "cuota_deducible": _euros_texto(fila["cuota_deducible_centimos"])})
    return _plantilla_apunte(c, datos, apunte_id, _error())


@guilda_fiscal_bp.route("/<int:cliente_id>/apuntes/<int:apunte_id>/anular", methods=["POST"])
@login_required
def apunte_anular(cliente_id: int, apunte_id: int):
    _cliente_o_404(cliente_id)
    try:
        fn.anular_apunte(g.tenant_id, g.usuario_id, cliente_id, apunte_id, request.form.get("motivo", ""))
    except ErrorFiscal as e:
        return _atras(url_for("guilda_fiscal.cliente", cliente_id=cliente_id), e)
    return redirect(url_for("guilda_fiscal.cliente", cliente_id=cliente_id))


@guilda_fiscal_bp.route("/<int:cliente_id>/registrar-facturas", methods=["POST"])
@login_required
def registrar_facturas(cliente_id: int):
    """Aprueba de golpe los apuntes de las facturas revisadas que se marquen (las automáticas); cada una es independiente."""
    _cliente_o_404(cliente_id)
    try:
        r = fn.aprobar_facturas(g.tenant_id, g.usuario_id, cliente_id, request.form.getlist("factura_id", type=int))
    except ErrorFiscal as e:
        return _atras(url_for("guilda_fiscal.cliente", cliente_id=cliente_id), e)
    if r["errores"]:
        return _atras(url_for("guilda_fiscal.cliente", cliente_id=cliente_id), "; ".join(f"#{x['factura_id']}: {x['motivo']}" for x in r["errores"][:3]))
    return redirect(url_for("guilda_fiscal.cliente", cliente_id=cliente_id))


@guilda_fiscal_bp.route("/<int:cliente_id>/periodo", methods=["POST"])
@login_required
def periodo(cliente_id: int):
    """Congela el periodo (instantánea) y calcula el borrador del 303."""
    _cliente_o_404(cliente_id)
    try:
        inst = fn.crear_instantanea(g.tenant_id, g.usuario_id, cliente_id, ejercicio=request.form.get("ejercicio", type=int) or date.today().year, periodo=request.form.get("periodo", ""))
        dec = fn.calcular_declaracion(g.tenant_id, g.usuario_id, inst["id"], destino_negativo=request.form.get("destino_negativo", "C"))
    except ErrorFiscal as e:
        return _atras(url_for("guilda_fiscal.cliente", cliente_id=cliente_id), e)
    return redirect(url_for("guilda_fiscal.declaracion", declaracion_id=dec["id"]))


@guilda_fiscal_bp.route("/declaracion/<int:declaracion_id>")
@login_required
def declaracion(declaracion_id: int):
    try:
        d = fn.obtener_declaracion(g.tenant_id, g.usuario_id, declaracion_id)
        inst = fn.obtener_instantanea(g.tenant_id, g.usuario_id, d["instantanea_id"])
    except ErrorFiscal:
        abort(404)
    c = _cliente_o_404(d["cliente_fiscal_id"])
    return render_template("fiscal_declaracion.html", d=d, c=c, inst=inst, apuntes={a["apunte_id"]: a for a in inst["datos"]["apuntes"]}, error=_error())


@guilda_fiscal_bp.route("/declaracion/<int:declaracion_id>/<accion>", methods=["POST"])
@login_required
def declaracion_accion(declaracion_id: int, accion: str):
    acciones = {"revisar": lambda: fn.revisar_declaracion(g.tenant_id, g.usuario_id, declaracion_id), "exportar": lambda: fn.exportar_declaracion(g.tenant_id, g.usuario_id, declaracion_id),
                "presentada": lambda: fn.marcar_presentada(g.tenant_id, g.usuario_id, declaracion_id, request.form.get("referencia", "")),
                "anular": lambda: fn.anular_declaracion(g.tenant_id, g.usuario_id, declaracion_id)}
    if accion not in acciones:
        abort(404)
    try:
        acciones[accion]()
    except ErrorFiscal as e:
        return _atras(url_for("guilda_fiscal.declaracion", declaracion_id=declaracion_id), e)
    return redirect(url_for("guilda_fiscal.declaracion", declaracion_id=declaracion_id))


@guilda_fiscal_bp.route("/declaracion/<int:declaracion_id>/descargar/<tipo>")
@login_required
def descargar(declaracion_id: int, tipo: str):
    if tipo not in ("303", "libro_xlsx", "resumen"):
        abort(404)
    try:
        datos, nombre = fn.descargar_artefacto(g.tenant_id, g.usuario_id, declaracion_id, tipo)
    except ErrorFiscal:
        abort(404)
    tipos = {"303": "application/octet-stream", "libro_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "resumen": "text/plain; charset=utf-8"}
    return Response(datos, mimetype=tipos[tipo], headers={"Content-Disposition": f'attachment; filename="{nombre}"', "X-Content-Type-Options": "nosniff"})


from . import rutas_api_guilda_fiscal  # noqa: E402,F401 -- registra las rutas de la API REST de este módulo en api_bp
