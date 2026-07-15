"""Guilda Work — Registro Diario de Actividad.

Punto de entrada: arranca un servidor Flask local y lo muestra en una
ventana nativa de Windows (WebView2, vía pywebview) en lugar de abrir el
navegador del sistema.
"""
import os
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import webview
from flask import Flask, Response, abort, redirect, render_template, request, url_for

from . import ai_local, correo, db, export, ia_asistente, importador
from .rutas_correo import correo_bp
from .rutas_ia import ia_bp
from .rutas_tareas import tareas_bp

HOST = "127.0.0.1"
PORT = 5057
ATAJO_CAPTURA = "ctrl+alt+g"

# Si se empaqueta en modo ventana (--windowed / --noconsole), Windows no da
# stdout/stderr al proceso y quedan en None: el logging de Flask/Werkzeug
# escribe ahí por defecto y reventaría al arrancar. Los redirigimos a nada.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

PROMPT_IA_POR_DEFECTO = "Resume mis actividades agrupadas por categoría, destacando lo más relevante y el tiempo dedicado a cada una."

# Cuando se empaqueta con PyInstaller, los recursos (templates/static) viajan
# dentro de sys._MEIPASS/app (--add-data "app/templates;app/templates" los
# coloca ahí). En desarrollo normal, usamos la carpeta de este paquete.
if hasattr(sys, "_MEIPASS"):
    BASE_DIR = Path(sys._MEIPASS) / "app"
else:
    BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
# Sin esto, con debug=False Jinja cachea las plantillas compiladas la primera
# vez y no recoge cambios en los .html hasta reiniciar el proceso. El coste
# (comprobar mtime en cada render) es insignificante para una app de un solo
# usuario local.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.register_blueprint(tareas_bp)
app.register_blueprint(correo_bp)
app.register_blueprint(ia_bp)


@app.context_processor
def inyectar_correo_badge():
    # El rail de iconos necesita este contador en cualquier página (para el
    # badge sobre el icono de Correo). La lista de menús ya no vive en un
    # sidebar global — cada ruta que la necesita (inicio(), captura()) la
    # pasa explícitamente en su propio contexto.
    return {"correo_no_leidos_sidebar": db.contar_no_leidos_total_correo()}


@app.context_processor
def inyectar_ia_flotante():
    # El panel flotante del Asistente IA vive en base.html, así que necesita
    # su propio contexto en cualquier página que no sea ya /ia (ahí la ruta
    # pasa mensajes/pendiente explícitamente para el chat de página completa).
    if request.endpoint and request.endpoint.startswith("ia."):
        return {}
    return {
        "ia_mensajes_flotante": db.listar_mensajes_ia(),
        "ia_pendiente_flotante": ia_asistente.pendiente_actual(),
    }


@app.route("/")
def inicio():
    menus = db.listar_categorias()
    activas = db.tareas_activas()
    activas_por_menu: dict[int, list] = {}
    for t in activas:
        activas_por_menu.setdefault(t["categoria_id"], []).append(t)
    entradas_hoy = {m["id"]: db.contar_entradas_hoy(m["id"]) for m in menus}
    hoy = datetime.now().strftime("%Y-%m-%d")
    log_hoy = db.historial(desde=hoy, hasta=hoy)
    return render_template(
        "inicio.html",
        menus=menus,
        activas_por_menu=activas_por_menu,
        entradas_hoy=entradas_hoy,
        log_hoy=log_hoy,
        total_activas=len(activas),
        total_notas_hoy=len([f for f in log_hoy if f["origen"] == "nota"]),
    )


@app.route("/menus", methods=["POST"])
def crear_menu():
    nombre = request.form.get("nombre", "").strip()
    color = request.form.get("color", "").strip() or None
    if nombre:
        db.crear_categoria(nombre, color)
    return redirect(url_for("inicio"))


@app.route("/menu/<int:menu_id>")
def ver_menu(menu_id: int):
    menu = db.obtener_categoria(menu_id)
    if menu is None:
        abort(404)
    q = request.args.get("q") or None
    activas = [t for t in db.tareas_activas() if t["categoria_id"] == menu_id]
    log = db.historial(categoria_id=menu_id, texto=q)
    plantillas = db.listar_plantillas(menu_id)
    return render_template("menu.html", menu=menu, activas=activas, log=log, q=q or "", plantillas=plantillas)


@app.route("/menu/<int:menu_id>/plantillas", methods=["POST"])
def crear_plantilla(menu_id: int):
    if db.obtener_categoria(menu_id) is None:
        abort(404)
    texto = request.form.get("texto", "").strip()
    if texto:
        db.crear_plantilla(menu_id, texto)
    return redirect(url_for("ver_menu", menu_id=menu_id))


@app.route("/plantilla/<int:plantilla_id>/eliminar", methods=["POST"])
def eliminar_plantilla(plantilla_id: int):
    db.eliminar_plantilla(plantilla_id)
    return redirect(request.form.get("volver_a") or request.referrer or url_for("inicio"))


@app.route("/menu/<int:menu_id>/renombrar", methods=["POST"])
def renombrar_menu(menu_id: int):
    if db.obtener_categoria(menu_id) is None:
        abort(404)
    nombre = request.form.get("nombre", "").strip()
    color = request.form.get("color", "").strip() or None
    if nombre:
        db.renombrar_categoria(menu_id, nombre, color)
    return redirect(url_for("ver_menu", menu_id=menu_id))


@app.route("/menu/<int:menu_id>/mover", methods=["POST"])
def mover_menu(menu_id: int):
    direccion = request.form.get("direccion")
    if direccion in ("arriba", "abajo"):
        db.mover_categoria(menu_id, direccion)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/menu/<int:menu_id>/favorito", methods=["POST"])
def alternar_favorito_menu(menu_id: int):
    if db.obtener_categoria(menu_id) is None:
        abort(404)
    db.alternar_favorito_categoria(menu_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/menus/reordenar", methods=["POST"])
def reordenar_menus():
    """Recibe el orden final tras arrastrar en la barra lateral (fetch en
    segundo plano, sin recarga de página — ver app/static/sidebar.js)."""
    datos = request.get_json(silent=True) or {}
    orden_ids = [int(i) for i in datos.get("orden", []) if str(i).isdigit()]
    db.reordenar_categorias(orden_ids)
    return "", 204


@app.route("/menu/<int:menu_id>/eliminar", methods=["POST"])
def eliminar_menu(menu_id: int):
    if db.obtener_categoria(menu_id) is None:
        abort(404)
    db.eliminar_categoria(menu_id)
    return redirect(url_for("inicio"))


@app.route("/notas", methods=["POST"])
def crear_nota():
    texto = request.form.get("texto", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    if texto:
        db.crear_nota(texto, categoria_id=categoria_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/nota/<int:nota_id>/editar", methods=["GET", "POST"])
def editar_nota(nota_id: int):
    nota = db.obtener_nota(nota_id)
    if nota is None:
        abort(404)
    if request.method == "POST":
        texto = request.form.get("texto", "").strip()
        volver_a = request.form.get("volver_a") or url_for("inicio")
        if texto:
            db.editar_nota(nota_id, texto)
        return redirect(volver_a)
    volver_a = request.args.get("volver_a") or request.referrer or url_for("inicio")
    return render_template("editar_nota.html", nota=nota, volver_a=volver_a)


@app.route("/nota/<int:nota_id>/eliminar", methods=["POST"])
def eliminar_nota(nota_id: int):
    if db.obtener_nota(nota_id) is None:
        abort(404)
    db.eliminar_nota(nota_id)
    return redirect(request.form.get("volver_a") or request.referrer or url_for("inicio"))


@app.route("/tareas", methods=["POST"])
def crear_tarea():
    nombre = request.form.get("nombre", "").strip()
    categoria_id = request.form.get("categoria_id")
    tipo = request.form.get("tipo", "duracion")
    if nombre and categoria_id:
        db.crear_tarea(nombre, int(categoria_id), tipo)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/tarea/<int:tarea_id>/editar", methods=["GET", "POST"])
def editar_tarea(tarea_id: int):
    tarea = db.obtener_tarea(tarea_id)
    if tarea is None:
        abort(404)
    error = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        inicio = request.form.get("inicio") or None
        fin = request.form.get("fin") or None
        volver_a = request.form.get("volver_a") or url_for("inicio")
        if nombre:
            db.editar_tarea(tarea_id, nombre)
        if inicio:
            error = db.editar_tiempos_tarea(tarea_id, inicio, fin)
        if error is None:
            return redirect(volver_a)
        tarea = db.obtener_tarea(tarea_id)
    volver_a = (
        request.form.get("volver_a")
        or request.args.get("volver_a")
        or request.referrer
        or url_for("inicio")
    )
    return render_template("editar_tarea.html", tarea=tarea, error=error, volver_a=volver_a)


@app.route("/tarea/<int:tarea_id>/eliminar", methods=["POST"])
def eliminar_tarea(tarea_id: int):
    if db.obtener_tarea(tarea_id) is None:
        abort(404)
    db.eliminar_tarea(tarea_id)
    return redirect(request.form.get("volver_a") or request.referrer or url_for("inicio"))


@app.route("/tareas/<int:tarea_id>/pausar", methods=["POST"])
def pausar_tarea(tarea_id: int):
    db.pausar_tarea(tarea_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/tareas/<int:tarea_id>/reanudar", methods=["POST"])
def reanudar_tarea(tarea_id: int):
    db.reanudar_tarea(tarea_id)
    return redirect(request.referrer or url_for("inicio"))


@app.route("/tareas/<int:tarea_id>/finalizar", methods=["POST"])
def finalizar_tarea(tarea_id: int):
    db.finalizar_tarea(tarea_id)
    return redirect(request.referrer or url_for("inicio"))


def _contexto_historial(desde, hasta, categoria_id, q=None, **extra):
    filas = db.historial(desde=desde, hasta=hasta, categoria_id=categoria_id, texto=q)
    ctx = {
        "filas": filas,
        "categorias": db.listar_categorias(),
        "desde": desde or "",
        "hasta": hasta or "",
        "categoria_id": categoria_id or "",
        "q": q or "",
        "proveedor_ia": "ollama",
        "modelo_ia": "",
        "prompt_ia": PROMPT_IA_POR_DEFECTO,
        "informe_texto": None,
        "informe_error": None,
    }
    ctx.update(extra)
    return ctx


@app.route("/historial")
def historial():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    categoria_id = request.args.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    q = request.args.get("q") or None
    return render_template("historial.html", **_contexto_historial(desde, hasta, categoria_id, q=q))


@app.route("/export")
def exportar():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    categoria_id = request.args.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    formato = request.args.get("formato", "json")

    if formato == "csv":
        contenido = export.a_csv(desde, hasta, categoria_id)
        mimetype = "text/csv"
        nombre_archivo = "guilda_work_export.csv"
    elif formato == "md":
        contenido = export.a_markdown(desde, hasta, categoria_id)
        mimetype = "text/markdown"
        nombre_archivo = "guilda_work_resumen.md"
    else:
        contenido = export.a_json(desde, hasta, categoria_id)
        mimetype = "application/json"
        nombre_archivo = "guilda_work_export.json"

    return Response(
        contenido,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )


@app.route("/importar", methods=["GET"])
def importar():
    return render_template("importar.html", resumen=None, error=None)


@app.route("/importar", methods=["POST"])
def procesar_importacion():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return render_template("importar.html", resumen=None, error="Elige un archivo JSON o CSV exportado desde Guilda Work.")

    contenido = archivo.read().decode("utf-8", errors="replace")
    try:
        if archivo.filename.lower().endswith(".csv"):
            resumen = importador.importar_csv(contenido)
        else:
            resumen = importador.importar_json(contenido)
    except importador.ErrorImportacion as e:
        return render_template("importar.html", resumen=None, error=str(e))

    return render_template("importar.html", resumen=resumen, error=None)


@app.route("/informe-ia", methods=["POST"])
def informe_ia():
    desde = request.form.get("desde") or None
    hasta = request.form.get("hasta") or None
    categoria_id = request.form.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    proveedor = request.form.get("proveedor", "ollama")
    modelo = request.form.get("modelo", "").strip()
    prompt = request.form.get("prompt", "").strip() or PROMPT_IA_POR_DEFECTO

    datos = export.construir_export(desde, hasta, categoria_id)
    informe_texto = None
    informe_error = None
    try:
        informe_texto = ai_local.generar_informe(datos, prompt, proveedor, modelo)
    except ai_local.ErrorIALocal as e:
        informe_error = str(e)

    return render_template(
        "historial.html",
        **_contexto_historial(
            desde, hasta, categoria_id,
            proveedor_ia=proveedor, modelo_ia=modelo, prompt_ia=prompt,
            informe_texto=informe_texto, informe_error=informe_error,
        ),
    )


@app.route("/pregunta-ia", methods=["POST"])
def pregunta_ia():
    """Modo "pregunta libre": chat con memoria contra los datos filtrados.

    Recibe y devuelve JSON (lo llama el JS del histórico por fetch), no HTML
    — el historial de la conversación lo guarda el navegador y lo reenvía en
    cada pregunta; el servidor no guarda nada de la conversación.
    """
    payload = request.get_json(silent=True) or {}
    desde = payload.get("desde") or None
    hasta = payload.get("hasta") or None
    categoria_id = payload.get("categoria_id") or None
    categoria_id = int(categoria_id) if categoria_id else None
    proveedor = payload.get("proveedor") or "ollama"
    modelo = str(payload.get("modelo") or "")
    pregunta = str(payload.get("pregunta") or "")

    historial_bruto = payload.get("historial") or []
    historial_mensajes = [
        {"role": m["role"], "content": m["content"]}
        for m in historial_bruto
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
    ]

    datos = export.construir_export(desde, hasta, categoria_id)
    try:
        respuesta = ai_local.preguntar(datos, historial_mensajes, pregunta, proveedor, modelo)
        return {"ok": True, "respuesta": respuesta}
    except ai_local.ErrorIALocal as e:
        return {"ok": False, "error": str(e)}


@app.route("/estadisticas")
def estadisticas():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    return render_template(
        "estadisticas.html",
        desde=desde or "",
        hasta=hasta or "",
        por_categoria=db.estadisticas_por_categoria(desde, hasta),
        por_dia=db.estadisticas_por_dia(desde, hasta),
    )


@app.route("/captura")
def captura():
    menus = db.listar_categorias()
    menu_id = request.args.get("menu")
    menu_id = int(menu_id) if menu_id and menu_id.isdigit() else (menus[0]["id"] if menus else None)
    return render_template("captura.html", menus=menus, menu_id=menu_id)


@app.route("/captura", methods=["POST"])
def crear_captura():
    texto = request.form.get("texto", "").strip()
    categoria_id = request.form.get("categoria_id") or None
    if texto and categoria_id:
        db.crear_nota(texto, categoria_id=categoria_id)
    return {"ok": True}


@app.route("/papelera")
def papelera():
    return render_template("papelera.html", items=db.papelera())


@app.route("/papelera/nota/<int:nota_id>/restaurar", methods=["POST"])
def restaurar_nota(nota_id: int):
    db.restaurar_nota(nota_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/nota/<int:nota_id>/eliminar-definitivamente", methods=["POST"])
def eliminar_nota_definitivamente(nota_id: int):
    db.eliminar_nota_definitivamente(nota_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/tarea/<int:tarea_id>/restaurar", methods=["POST"])
def restaurar_tarea(tarea_id: int):
    db.restaurar_tarea(tarea_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/tarea/<int:tarea_id>/eliminar-definitivamente", methods=["POST"])
def eliminar_tarea_definitivamente(tarea_id: int):
    db.eliminar_tarea_definitivamente(tarea_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/menu/<int:menu_id>/restaurar", methods=["POST"])
def restaurar_menu(menu_id: int):
    db.restaurar_categoria(menu_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/menu/<int:menu_id>/eliminar-definitivamente", methods=["POST"])
def eliminar_menu_definitivamente(menu_id: int):
    db.eliminar_categoria_definitivamente(menu_id)
    return redirect(url_for("papelera"))


@app.route("/papelera/vaciar", methods=["POST"])
def vaciar_papelera():
    db.vaciar_papelera_antigua(dias=0)
    return redirect(url_for("papelera"))


@app.route("/apagar", methods=["POST"])
def apagar():
    """Cierra el servidor y termina el proceso por completo (evita procesos zombis).

    Todo lo que ya se ha guardado (notas, tareas, menús) está en SQLite con
    commit inmediato en cada operación, así que no hay nada "pendiente" que
    perder al cerrar: no hace falta guardar nada aquí, solo terminar el proceso.
    """
    def _cerrar_proceso():
        time.sleep(0.6)  # da tiempo a que la respuesta llegue a la ventana
        os._exit(0)

    threading.Thread(target=_cerrar_proceso, daemon=True).start()
    return render_template("cerrado.html")


def _servidor_listo(host: str, port: int, timeout: float = 8.0) -> bool:
    """Espera a que el servidor Flask acepte conexiones antes de abrir la ventana."""
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _iniciar_servidor():
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


# --- Ventana principal, bandeja del sistema y captura rápida ---------------
# Estado global sencillo: solo hay un proceso y una ventana principal, así
# que no hace falta nada más elaborado que unas variables de módulo.
_ventana_principal = None
_icono_bandeja = None
_ventana_captura = None


class _AppAPI:
    """Puente JS↔Python expuesto a las ventanas (window.pywebview.api.*)."""

    def abrir_captura(self):
        _abrir_captura()

    def cerrar_captura(self):
        _cerrar_captura()


def _abrir_captura():
    global _ventana_captura
    if _ventana_captura is not None:
        try:
            _ventana_captura.show()
            return
        except Exception:
            _ventana_captura = None
    _ventana_captura = webview.create_window(
        "Captura rápida — Guilda Work",
        f"http://{HOST}:{PORT}/captura",
        width=440,
        height=170,
        frameless=True,
        easy_drag=True,
        on_top=True,
        js_api=_AppAPI(),
    )

    def _al_cerrar_captura():
        global _ventana_captura
        _ventana_captura = None

    _ventana_captura.events.closed += _al_cerrar_captura


def _cerrar_captura():
    global _ventana_captura
    if _ventana_captura is not None:
        try:
            _ventana_captura.destroy()
        except Exception:
            pass
        _ventana_captura = None


def _mostrar_ventana_principal(icon=None, item=None):
    if _ventana_principal is not None:
        _ventana_principal.show()


def _salir_completamente(icon=None, item=None):
    if _icono_bandeja is not None:
        try:
            _icono_bandeja.stop()
        except Exception:
            pass
    os._exit(0)


def _al_intentar_cerrar_principal():
    """Si hay bandeja del sistema, ocultar en vez de cerrar; si no, cerrar de verdad."""
    if _icono_bandeja is not None:
        _ventana_principal.hide()
        return False
    return True


def _crear_icono_bandeja():
    """Icono en la bandeja del sistema. Si falla (entorno sin soporte), la app
    sigue funcionando con el comportamiento normal de cerrar al pulsar la X."""
    global _icono_bandeja
    try:
        import pystray
        from PIL import Image

        imagen = Image.open(BASE_DIR / "static" / "logo.png")
        menu = pystray.Menu(
            pystray.MenuItem("Abrir Guilda Work", _mostrar_ventana_principal, default=True),
            pystray.MenuItem("Captura rápida", lambda icon, item: _abrir_captura()),
            pystray.MenuItem("Cerrar", _salir_completamente),
        )
        _icono_bandeja = pystray.Icon("guilda_work", imagen, "Guilda Work", menu)
        _icono_bandeja.run_detached()
    except Exception:
        _icono_bandeja = None


def _registrar_atajo_global():
    """Atajo global (funciona con la ventana minimizada/en segundo plano).

    Si la librería no puede engancharse al teclado (permisos, entorno sin
    soporte...), la app sigue funcionando sin este atajo.
    """
    try:
        import keyboard

        keyboard.add_hotkey(ATAJO_CAPTURA, _abrir_captura)
    except Exception:
        pass


SINCRONIZACION_CORREO_INTERVALO_MINUTOS = 10


def _sincronizacion_correo_periodica():
    """Cada SINCRONIZACION_CORREO_INTERVALO_MINUTOS, sincroniza todas las
    cuentas de correo configuradas, para que el badge de "correo nuevo" de
    la barra lateral refleje mensajes recién llegados sin tener que pulsar
    "Sincronizar" a mano. Cada cuenta se sincroniza en su propio try/except:
    una cuenta con credenciales caducadas o sin red no debe impedir que se
    sincronicen las demás, ni tumbar este hilo."""
    while True:
        time.sleep(SINCRONIZACION_CORREO_INTERVALO_MINUTOS * 60)
        try:
            cuentas = db.listar_cuentas_correo()
        except Exception:
            continue
        for cuenta in cuentas:
            try:
                correo.sincronizar_bandeja(cuenta["id"])
            except Exception:
                pass  # un fallo de esta cuenta no debe impedir sincronizar las demás


RECORDATORIO_INTERVALO_MINUTOS = 60


def _recordatorio_periodico():
    """Cada RECORDATORIO_INTERVALO_MINUTOS, si no ha habido ninguna nota ni
    tarea nueva en ese rato, envía un aviso a la bandeja recordando anotar.
    No es un temporizador rígido: si ya estás anotando cosas, no molesta.
    """
    while True:
        time.sleep(RECORDATORIO_INTERVALO_MINUTOS * 60)
        if _icono_bandeja is None:
            continue
        try:
            if not db.hubo_actividad_reciente(RECORDATORIO_INTERVALO_MINUTOS):
                _icono_bandeja.notify(
                    "¿Qué has hecho en la última hora? Ctrl+Alt+G lo anota en dos segundos.",
                    "Guilda Work",
                )
        except Exception:
            pass  # un fallo del recordatorio no debe tumbar el hilo ni la app


def main():
    global _ventana_principal
    db.init_db()
    try:
        db.hacer_backup_si_hace_falta()
    except Exception:
        pass  # una copia de seguridad fallida no debe impedir arrancar la app
    try:
        db.vaciar_papelera_antigua()
    except Exception:
        pass  # idem para la purga automática de la papelera
    try:
        export.generar_resumen_automatico_si_hace_falta()
    except Exception:
        pass  # idem para el resumen automático de ayer
    threading.Thread(target=_iniciar_servidor, daemon=True).start()
    _servidor_listo(HOST, PORT)

    _ventana_principal = webview.create_window(
        "Guilda Work",
        f"http://{HOST}:{PORT}/",
        width=1280,
        height=860,
        min_size=(960, 640),
        js_api=_AppAPI(),
    )
    _ventana_principal.events.closing += _al_intentar_cerrar_principal

    _crear_icono_bandeja()
    _registrar_atajo_global()
    threading.Thread(target=_recordatorio_periodico, daemon=True).start()
    threading.Thread(target=_sincronizacion_correo_periodica, daemon=True).start()

    webview.start()

    # Solo se llega aquí si no hay bandeja (o algo la desactivó) y se cerró
    # la ventana principal de verdad: terminamos el proceso por completo
    # para no dejar el servidor de fondo corriendo (evita procesos zombis).
    os._exit(0)


if __name__ == "__main__":
    main()
