"""Pantallas del Asistente jurídico: consultar con IA, biblioteca, ficha documental, informes del expediente y fuentes (ver `docs/adr-asistente-juridico.md` y `app/juridico/`).

Sin `LEGAL_AI_ENABLED` o sin el vertical activo en el despacho, todo es 404. Las acciones sobre el corpus común y sus políticas son solo del administrador de la plataforma; la dirección del despacho
decide qué fuentes usa su despacho. Todos los servicios comprueban permisos de nuevo: estas pantallas no son la barrera."""
from __future__ import annotations

import threading
from datetime import date, timedelta
from urllib.parse import quote

from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import acceso, db, nucleo, verticales
from .auth import login_required
from .juridico import adjuntos, asistente, busqueda, catalogo, corpus, informes, ingesta, modulo
from .juridico.esquema import COLECCIONES

juridico_bp = Blueprint("juridico", __name__, url_prefix="/juridico")


@juridico_bp.before_request
def _solo_con_el_modulo():
    if not modulo.habilitado() or g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "juridico"):
        abort(404)


def _error() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _con_error(destino: str, mensaje: str, **valores):
    return redirect(url_for(destino, error=mensaje, **valores))


def _es_admin() -> bool:
    return bool(db.es_admin(g.usuario_id))


def _clientes() -> list:
    cond, params = acceso.condicion_nucleo(g.tenant_id, g.usuario_id, "c.id")
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT c.id, c.nombre FROM clientes c WHERE c.tenant_id = ? AND c.papelera_en IS NULL{' AND ' + cond if cond else ''} ORDER BY c.nombre LIMIT 1000", [g.tenant_id, *params]).fetchall()
    finally:
        conn.close()


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _estado_ia() -> bool:
    from . import reuniones
    return reuniones.configurada(g.usuario_id)


# --- Consultar ---------------------------------------------------------------------------------------------------------------------------------

@juridico_bp.route("/")
@login_required
def inicio():
    usables = set(corpus.fuentes_para_despacho(g.tenant_id, "indexar"))
    return render_template("juridico_inicio.html", conversaciones=asistente.listar_conversaciones(g.tenant_id, g.usuario_id, 15), clientes=_clientes(), hoy=date.today().isoformat(),
                           colecciones=COLECCIONES, cobertura=[c for c in corpus.cobertura() if c["fuente_id"] in usables], ia_configurada=_estado_ia(), error=_error(), puede_escribir=not acceso.es_solo_auditor(g.tenant_id, g.usuario_id),
                           adjuntos_recientes=adjuntos.listar(g.tenant_id, g.usuario_id, limite=10))


@juridico_bp.route("/consultar", methods=["POST"])
@login_required
def consultar():
    f = request.form
    try:
        conv = asistente.crear_conversacion(g.tenant_id, g.usuario_id, cliente_id=_int(f.get("cliente_id")), expediente_id=_int(f.get("expediente_id")), titulo=(f.get("pregunta") or "")[:80])
        ids = [int(x) for x in f.getlist("adjunto_id") if x.isdigit()]
        for archivo in request.files.getlist("archivos"):
            if archivo and archivo.filename:
                ids.append(adjuntos.subir(g.tenant_id, g.usuario_id, archivo.filename, archivo.read(adjuntos.MAX_BYTES + 1), cliente_id=_int(f.get("cliente_id")), expediente_id=_int(f.get("expediente_id")))["id"])
        r = asistente.consultar(g.tenant_id, g.usuario_id, conv, f.get("pregunta", ""), colecciones=f.getlist("coleccion") or None, materia=f.get("materia") or None, territorio=f.get("territorio") or None,
                                fecha_juridica=f.get("fecha_juridica") or None, modo_temporal=f.get("modo_temporal") or "actual", objetivo=f.get("objetivo") or "consulta", adjunto_ids=ids,
                                clave_idempotencia=f.get("clave") or None)
    except (asistente.ErrorJuridico, adjuntos.ErrorAdjunto) as e:
        return _con_error("juridico.inicio", _(str(e)))
    return redirect(url_for("juridico.consulta", run_id=r["runId"]))


@juridico_bp.route("/consulta/<int:run_id>")
@login_required
def consulta(run_id: int):
    e = asistente.ejecucion(g.tenant_id, g.usuario_id, run_id)
    if e is None:
        abort(404)
    return render_template("juridico_consulta.html", e=e, r=e["respuesta"], error=_error(), puede_guardar=not acceso.es_solo_auditor(g.tenant_id, g.usuario_id))


@juridico_bp.route("/consulta/<int:run_id>/informe", methods=["POST"])
@login_required
def guardar_informe(run_id: int):
    try:
        inf = informes.guardar(g.tenant_id, g.usuario_id, run_id, titulo=request.form.get("titulo"))
    except informes.ErrorInforme as e:
        return _con_error("juridico.consulta", _(str(e)), run_id=run_id)
    return redirect(url_for("juridico.informe", informe_id=inf["id"]))


# --- Biblioteca -----------------------------------------------------------------------------------------------------------------------------------

@juridico_bp.route("/biblioteca")
@login_required
def biblioteca():
    q = request.args
    colecciones = [c for c in q.getlist("coleccion") if c in COLECCIONES]
    resultados, error = None, None
    hay_filtro = any(q.get(k) for k in ("q", "emisor", "tipo", "materia", "territorio", "desde", "hasta", "fecha_juridica")) or colecciones
    if hay_filtro:
        try:
            resultados = busqueda.buscar(g.tenant_id, q.get("q", ""), colecciones=colecciones or None, materia=q.get("materia") or None, territorio=q.get("territorio") or None, emisor=q.get("emisor") or None,
                                         tipo=q.get("tipo") or None, desde=q.get("desde") or None, hasta=q.get("hasta") or None, fecha_juridica=q.get("fecha_juridica") or None, cursor=q.get("cursor") or None)
        except busqueda.ErrorBusqueda as e:
            error = _(str(e))
    usables = set(corpus.fuentes_para_despacho(g.tenant_id, "indexar"))
    cobertura = [c for c in corpus.cobertura() if c["fuente_id"] in usables]
    pendientes = [f for f in corpus.listar_fuentes() if f["id"] not in usables]
    return render_template("juridico_biblioteca.html", resultados=resultados, q=q, colecciones_sel=colecciones, colecciones=COLECCIONES, cobertura=cobertura, pendientes=pendientes, error=error or _error(),
                           params=[(k, quote(v)) for k, v in q.items(multi=True) if k != "cursor" and v])


@juridico_bp.route("/documento/<int:documento_id>")
@login_required
def documento(documento_id: int):
    try:
        d = busqueda.documento(g.tenant_id, documento_id)
        if d is None:
            abort(404)
        t = busqueda.texto_de_version(g.tenant_id, documento_id, _int(request.args.get("version")), request.args.get("fecha_juridica") or None)
    except busqueda.ErrorBusqueda as e:
        return _con_error("juridico.biblioteca", _(str(e)))
    if t is None:
        abort(404)
    return render_template("juridico_documento.html", d=d, t=t, fecha=request.args.get("fecha_juridica") or "", localizador=request.args.get("fragmento"))


# --- Informes ---------------------------------------------------------------------------------------------------------------------------------------

@juridico_bp.route("/informes")
@login_required
def lista_informes():
    return render_template("juridico_informes.html", informes=informes.listar(g.tenant_id, g.usuario_id, expediente_id=_int(request.args.get("expediente_id")), cliente_id=_int(request.args.get("cliente_id"))), error=_error())


@juridico_bp.route("/informes/<int:informe_id>")
@login_required
def informe(informe_id: int):
    inf = informes.obtener(g.tenant_id, g.usuario_id, informe_id)
    if inf is None:
        abort(404)
    return render_template("juridico_informe.html", inf=inf, r=inf["instantanea"]["respuesta"], texto=informes.texto_para_copiar(inf), error=_error(),
                           puede_revisar=inf["estado"] == "borrador" and (acceso.es_directivo(g.usuario_id) or acceso.puede_autorizar(g.tenant_id, g.usuario_id)))


@juridico_bp.route("/informes/<int:informe_id>/revisar", methods=["POST"])
@login_required
def revisar_informe(informe_id: int):
    try:
        informes.revisar(g.tenant_id, g.usuario_id, informe_id, request.form.get("decision") or "revisado", request.form.get("nota"))
    except informes.ErrorInforme as e:
        return _con_error("juridico.informe", _(str(e)), informe_id=informe_id)
    return redirect(url_for("juridico.informe", informe_id=informe_id))


# --- Fuentes -----------------------------------------------------------------------------------------------------------------------------------------

@juridico_bp.route("/fuentes")
@login_required
def fuentes():
    admin = _es_admin()
    director = acceso.es_directivo(g.usuario_id)
    cob = {c["fuente_id"]: c for c in corpus.cobertura()}
    conn = db.get_connection()
    try:
        del_despacho = {r["fuente_id"]: bool(r["habilitada"]) for r in conn.execute("SELECT fuente_id, habilitada FROM jur_fuente_despacho WHERE tenant_id = ?", (g.tenant_id,))}
    finally:
        conn.close()
    usables = set(corpus.fuentes_para_despacho(g.tenant_id, "indexar"))
    filas = []
    for f in corpus.listar_fuentes():
        c = catalogo.CONECTORES[f["conector"]]
        filas.append({**f, "cob": cob[f["id"]], "politica": corpus.politica_vigente(f["id"]), "verificacion": catalogo.VERIFICACION.get(f["id"], ""), "usable": f["id"] in usables,
                      "despacho": del_despacho.get(f["id"]), "capaz": c.capacidades.descubrir, "ejecuciones": ingesta.ultimas_ejecuciones(f["id"], 3) if admin else [],
                      "problemas": ingesta.registros_con_problemas(f["id"], 10) if admin else []})
    return render_template("juridico_fuentes.html", fuentes=filas, admin=admin, director=director, hoy=date.today().isoformat(), hace_semana=(date.today() - timedelta(days=7)).isoformat(), error=_error())


@juridico_bp.route("/fuentes/<fuente_id>/despacho", methods=["POST"])
@login_required
def fuente_despacho(fuente_id: str):
    if not acceso.es_directivo(g.usuario_id):
        abort(403)
    try:
        corpus.fijar_fuente_despacho(g.tenant_id, fuente_id, request.form.get("habilitada") == "1", g.usuario_id)
    except corpus.ErrorCorpus as e:
        return _con_error("juridico.fuentes", _(str(e)))
    return redirect(url_for("juridico.fuentes"))


@juridico_bp.route("/fuentes/<fuente_id>/politica", methods=["POST"])
@login_required
def fuente_politica(fuente_id: str):
    if not _es_admin():
        abort(403)
    f = request.form
    try:
        corpus.registrar_politica(fuente_id, evidencia=f.get("evidencia", ""), almacenar=f.get("almacenar") == "1", indexar=f.get("indexar") == "1", enviar_llm=f.get("enviar_llm") == "1",
                                  citar=f.get("citar") == "1", exportar=f.get("exportar") == "1", atribucion=f.get("atribucion") or None, usuario_id=g.usuario_id)
    except corpus.ErrorCorpus as e:
        return _con_error("juridico.fuentes", _(str(e)))
    return redirect(url_for("juridico.fuentes"))


@juridico_bp.route("/fuentes/<fuente_id>/habilitar", methods=["POST"])
@login_required
def fuente_habilitar(fuente_id: str):
    if not _es_admin():
        abort(403)
    try:
        corpus.habilitar_fuente(fuente_id, request.form.get("habilitada") == "1", g.usuario_id)
    except corpus.ErrorCorpus as e:
        return _con_error("juridico.fuentes", _(str(e)))
    return redirect(url_for("juridico.fuentes"))


@juridico_bp.route("/fuentes/<fuente_id>/sincronizar", methods=["POST"])
@login_required
def fuente_sincronizar(fuente_id: str):
    """Lanza la sincronización en segundo plano (no bloquea la petición). Solo el administrador de la plataforma; con la fuente habilitada y con política."""
    if not _es_admin():
        abort(403)
    f = corpus.obtener_fuente(fuente_id)
    if f is None:
        abort(404)
    try:
        desde, hasta = request.form.get("desde") or "", request.form.get("hasta") or ""
        if corpus.fecha_iso(desde) is None or corpus.fecha_iso(hasta) is None or desde > hasta:
            raise corpus.ErrorCorpus("Indica un intervalo de fechas válido.")
        if (date.fromisoformat(hasta) - date.fromisoformat(desde)).days > 400:
            raise corpus.ErrorCorpus("El intervalo es demasiado largo para una sola ejecución (máximo 400 días).")
        conector = catalogo.crear_conector(fuente_id)
        if not conector.capacidades.descubrir:
            raise corpus.ErrorCorpus("Este conector todavía no tiene transporte: está pendiente de habilitación.")
    except corpus.ErrorCorpus as e:
        return _con_error("juridico.fuentes", _(str(e)))
    threading.Thread(target=ingesta.sincronizar, args=(fuente_id, conector, desde, hasta), kwargs={"usuario_id": g.usuario_id}, daemon=True).start()
    return redirect(url_for("juridico.fuentes"))
