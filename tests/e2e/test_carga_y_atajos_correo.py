"""Cobertura de lo que antes no tenía prueba de navegador (X2): arrastrar una tarea en el plan de carga y los atajos de teclado del correo (j, k, u, #)."""
from datetime import date, timedelta

from app import db


def test_arrastrar_una_tarea_a_otro_dia_en_el_plan_de_carga(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho carga e2e")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "carga-e2e@ejemplo.com", despacho=t, direccion=True)
    lunes = date.today() - timedelta(days=date.today().weekday())
    martes, jueves = (lunes + timedelta(days=1)).isoformat(), (lunes + timedelta(days=3)).isoformat()
    tid = db.crear_tarea_outlook(uid, "Preparar el 303", fecha_vencimiento=martes, estimacion_min=60)

    pagina.goto(f"{servidor.url}/tareas/carga")
    pagina.wait_for_load_state("networkidle")
    origen = pagina.locator(f".carga-tarea[data-tarea='{tid}']")
    destino = pagina.locator(f".carga-celda[data-persona='{uid}'][data-fecha='{jueves}']")
    origen.drag_to(destino)
    pagina.wait_for_load_state("networkidle")
    pagina.wait_for_function("(a) => document.querySelector(`.carga-celda[data-fecha='${a.f}'] .carga-tarea[data-tarea='${a.t}']`) !== null", arg={"f": jueves, "t": tid})
    assert db.obtener_tarea_outlook(uid, tid)["fecha_vencimiento"].startswith(jueves) and not errores


def test_atajos_de_teclado_del_correo(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho atajos correo e2e")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "atajos-correo-e2e@ejemplo.com", despacho=t, direccion=True)
    cuenta = db.crear_cuenta_correo(uid, "info@despacho.es", "imap", "imap.ejemplo.com", 993, "info@despacho.es")
    ids = [db.guardar_mensaje_correo(cuenta, f"u{i}", f"Asunto {i}", "ana@ejemplo.com", "info@despacho.es", f"2026-11-0{i}T09:00:00", "texto", None, leido=True) for i in (1, 2, 3)]

    pagina.goto(f"{servidor.url}/correo/?cuenta_id={cuenta}")
    pagina.wait_for_load_state("networkidle")
    pagina.keyboard.press("j")                                                         # abre el primero de la lista
    pagina.wait_for_url("**mensaje_id=*")
    primero = pagina.url
    pagina.keyboard.press("j")
    pagina.wait_for_function("(u) => location.href !== u", arg=primero)
    segundo = pagina.url
    pagina.keyboard.press("k")                                                         # y vuelve atrás
    pagina.wait_for_function("(u) => location.href !== u", arg=segundo)
    assert pagina.url == primero

    abierto = int(pagina.url.split("mensaje_id=")[1].split("&")[0])
    pagina.keyboard.press("u")                                                         # lo marca como no leído y vuelve a la lista
    pagina.wait_for_function("() => !location.search.includes('mensaje_id')")
    assert db.obtener_mensaje_correo(abierto)["leido"] == 0

    pagina.keyboard.press("j")
    pagina.wait_for_url("**mensaje_id=*")
    por_borrar = int(pagina.url.split("mensaje_id=")[1].split("&")[0])
    pagina.keyboard.press("#")
    pagina.wait_for_function("(id) => !location.href.includes('mensaje_id=' + id)", arg=por_borrar)
    assert db.obtener_mensaje_correo(por_borrar) is None and not errores
