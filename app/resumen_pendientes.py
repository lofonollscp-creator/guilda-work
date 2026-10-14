"""Resumen diario de PENDIENTES para quien trabaja en Guilda Work (no para el cliente): tareas vencidas y de hoy, visitas
agendadas hoy, plazos y vencimientos que apremian y correos recibidos sin contestar.

Es opt-in por persona (`usuario_perfil.resumen_diario`), llega a la campana y al móvil y, si el correo saliente está
configurado, también por email. Una sola función reúne los datos (`reunir`) y la usan la entrega programada, la herramienta
`resumen_del_dia` del asistente y las pruebas.

Lo protegido sigue protegido: el resumen se arma SOLO con lo que está en claro en la base (el hilo de fondo no tiene la clave
del despacho). Un correo cuyo asunto o remitente está sellado cuenta como «correo protegido» y no revela nada más."""
import email.utils
import re
import time
from datetime import date, datetime, timedelta
from html import escape

from . import correo_diseno, db, notificaciones_email, nucleo, salud, verticales

INTERVALO_SEGUNDOS = 15 * 60
HORA_POR_DEFECTO = 8
DIAS_CORREO = 14                # solo se echan en falta los correos recientes
LIMITE_LINEAS = 8               # por sección, en el texto; el resto se resume en «y N más»
DIAS_PLAZO_CERCANO = 3
_AUTOMATICOS = re.compile(r"no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|notifications?@|newsletter", re.I)


def _dia(valor: str | None) -> str:
    return (valor or "")[:10]


def correos_sin_contestar(usuario_id: int, hoy: date, limite: int = 50) -> list[dict]:
    """Correos de la bandeja de entrada de las cuentas de la persona, de los últimos DIAS_CORREO días, que no tienen
    después ninguna respuesta suya en el mismo hilo. Ni automáticos ni pospuestos."""
    desde = (hoy - timedelta(days=DIAS_CORREO)).isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT m.id, m.cuenta_id, m.asunto, m.remitente, m.fecha, m.cifrado, m.destacado, m.cliente_fiscal_id, lower(c.usuario) AS propia
               FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE c.usuario_id = ? AND m.carpeta = 'INBOX' AND COALESCE(m.cifrado, 0) != 2
                 AND substr(m.fecha, 1, 10) >= ? AND substr(m.fecha, 1, 10) <= ?
                 AND (m.pospuesto_hasta IS NULL OR m.pospuesto_hasta <= ?)
                 AND NOT EXISTS (
                     SELECT 1 FROM correo_mensajes r
                     WHERE r.cuenta_id = m.cuenta_id AND r.hilo_clave = m.hilo_clave AND m.hilo_clave IS NOT NULL
                       AND r.id != m.id AND r.fecha > m.fecha AND r.carpeta != 'INBOX'
                       AND lower(COALESCE(r.remitente, '')) LIKE '%' || lower(c.usuario) || '%')
               ORDER BY m.fecha DESC LIMIT ?""",
            (usuario_id, desde, hoy.isoformat(), hoy.isoformat() + "T23:59:59", max(1, limite) * 3)).fetchall()
    finally:
        conn.close()
    res = []
    for f in filas:
        direccion = email.utils.parseaddr(f["remitente"] or "")[1].strip().lower()
        if direccion and direccion == f["propia"]:
            continue
        if _AUTOMATICOS.search(f["remitente"] or ""):
            continue
        res.append({"id": f["id"], "asunto": (f["asunto"] or "").strip() or None, "remitente": (f["remitente"] or "").strip() or None,
                    "fecha": _dia(f["fecha"]), "importante": bool(f["destacado"] or f["cliente_fiscal_id"]), "protegido": not f["asunto"] and not f["remitente"] and bool(f["cifrado"])})
        if len(res) >= limite:
            break
    return res


def reunir(usuario_id: int, hoy: date | None = None) -> dict:
    """Todo lo pendiente de una persona hoy. Cada sección es una lista (vacía si no hay nada o el módulo no está contratado)."""
    hoy = hoy or date.today()
    iso = hoy.isoformat()
    tenant = db.tenant_de_usuario(usuario_id)
    mi_dia = db.tareas_para_hoy(usuario_id)
    r = {
        "fecha": iso,
        "tareas_vencidas": [{"id": t["id"], "titulo": t["asunto"], "fecha": _dia(t["fecha_vencimiento"])} for t in mi_dia["vencidas"]],
        "tareas_hoy": [{"id": t["id"], "titulo": t["asunto"]} for t in mi_dia["hoy"]],
        "visitas_hoy": [], "plazos": [], "vencimientos": [], "ausencias_por_aprobar": [], "correos_sin_contestar": correos_sin_contestar(usuario_id, hoy),
    }
    if tenant is None:
        return r
    tid = tenant["id"]
    activos = verticales.activos_de(tid)
    if "inmobiliaria" in activos:
        from . import inmobiliaria
        for v in inmobiliaria.listar_visitas(tid, usuario_id, False, agente_id=usuario_id, desde=iso, hasta=iso, estado="prevista"):
            r["visitas_hoy"].append({"id": v["id"], "hora": (v["fecha_hora"] or "")[11:16], "direccion": v["direccion"], "visitante": v["visitante_nombre"]})
    if r["visitas_hoy"]:        # cada visita crea su propia tarea de recordatorio: no se cuenta dos veces
        propias = {f"Visita: {v['direccion']}" for v in r["visitas_hoy"]}
        r["tareas_hoy"] = [t for t in r["tareas_hoy"] if t["titulo"] not in propias]
    if activos:
        hasta = (hoy + timedelta(days=DIAS_PLAZO_CERCANO)).isoformat()
        for z in nucleo.listar_plazos(tid, usuario_id, False, estado="abiertos", responsable_id=usuario_id, hasta=hasta, hoy=hoy):
            r["plazos"].append({"id": z["id"], "titulo": z["titulo"], "fecha": z["fecha_limite"], "estado": z["estado_calculado"], "cliente": z["cliente_nombre"]})
    from . import ausencias
    if ausencias.puede_gestionar(usuario_id, tid):
        r["ausencias_por_aprobar"] = [{"id": x["id"], "persona": x["persona"], "desde": x["desde"], "hasta": x["hasta"]} for x in ausencias.listar(tid, estado="pendiente")]
    hasta = (hoy + timedelta(days=DIAS_PLAZO_CERCANO)).isoformat()
    for v in db.listar_vencimientos_fiscales(tid, estado="pendiente", hasta=hasta):
        if v["usuario_id"] == usuario_id:
            r["vencimientos"].append({"id": v["id"], "modelo": v["modelo"], "cliente": v["cliente_nombre"], "fecha": _dia(v["fecha_limite"])})
    return r


def total(r: dict) -> int:
    return sum(len(r[k]) for k in ("tareas_vencidas", "tareas_hoy", "visitas_hoy", "plazos", "vencimientos", "ausencias_por_aprobar", "correos_sin_contestar"))


def _cuando(fecha: str, hoy: str) -> str:
    dias = (date.fromisoformat(fecha) - date.fromisoformat(hoy)).days
    return notificaciones_email.texto_cuando(dias)


def _quien(c: dict) -> str:
    nombre, direccion = email.utils.parseaddr(c["remitente"] or "")
    return (nombre or direccion or "alguien").strip()


def frase_correos(correos: list[dict]) -> str:
    """«4 correos sin contestar · importantes: Marta Puig, Joan Vila». Sin asuntos ni lista uno a uno."""
    n = len(correos)
    frase = f"{n} correo{'s' if n != 1 else ''} sin contestar"
    quienes = []
    for c in correos:
        if c["importante"] and not c["protegido"]:
            nombre = _quien(c)
            if nombre not in quienes:
                quienes.append(nombre)
    if quienes:
        frase += " · importantes: " + ", ".join(quienes[:3]) + (f" y {len(quienes) - 3} más" if len(quienes) > 3 else "")
    return frase


def redactar(r: dict) -> tuple[str, str, list[str]]:
    """(título, resumen de una línea para el móvil, líneas del cuerpo)."""
    hoy = r["fecha"]
    lineas: list[str] = []

    def seccion(titulo: str, items: list[str]) -> None:
        if not items:
            return
        lineas.append(f"{titulo} ({len(items)})")
        lineas.extend("  · " + i for i in items[:LIMITE_LINEAS])
        if len(items) > LIMITE_LINEAS:
            lineas.append(f"  · … y {len(items) - LIMITE_LINEAS} más")
        lineas.append("")

    seccion("Visitas de hoy", [f"{v['hora'] or '--:--'} · {v['direccion']}" + (f" · {v['visitante']}" if v["visitante"] else "") for v in r["visitas_hoy"]])
    seccion("Plazos", [f"{z['titulo']}" + (f" ({z['cliente']})" if z["cliente"] else "") + f" · {_cuando(z['fecha'], hoy)}" for z in r["plazos"]])
    seccion("Vencimientos fiscales", [f"{v['modelo']} · {v['cliente']} · {_cuando(v['fecha'], hoy)}" for v in r["vencimientos"]])
    seccion("Ausencias por aprobar", [f"{x['persona']} · {x['desde']}" + (f" → {x['hasta']}" if x["hasta"] != x["desde"] else "") for x in r["ausencias_por_aprobar"]])
    seccion("Tareas atrasadas", [f"{t['titulo']} · {_cuando(t['fecha'], hoy)}" for t in r["tareas_vencidas"]])
    seccion("Tareas de hoy", [t["titulo"] for t in r["tareas_hoy"]])
    if r["correos_sin_contestar"]:
        lineas.append(frase_correos(r["correos_sin_contestar"]))
        lineas.append("")
    n = total(r)
    partes = []
    for clave, etiqueta in (("visitas_hoy", "visitas"), ("plazos", "plazos"), ("vencimientos", "vencimientos"), ("tareas_vencidas", "atrasadas"),
                            ("tareas_hoy", "tareas hoy"), ("ausencias_por_aprobar", "ausencias por aprobar"), ("correos_sin_contestar", "correos sin contestar")):
        if r[clave]:
            partes.append(f"{len(r[clave])} {etiqueta}")
    return f"Tu día: {n} pendiente" + ("s" if n != 1 else ""), ", ".join(partes), [ln for ln in lineas]


DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_C = correo_diseno
AVISO = "#ff9b80"               # atrasado: cálido, con contraste AA sobre la tarjeta oscura
FILAS_HTML = 5


def _fecha_larga(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _baldosas(datos: list[tuple[int, str, str]]) -> str:
    """Cifras grandes, hasta 3 por fila (tabla: los clientes de correo no entienden flex ni grid)."""
    filas = []
    for i in range(0, len(datos), 3):
        celdas = []
        for n, etiqueta, color in datos[i:i + 3]:
            celdas.append(
                f'<td align="center" width="33%" style="padding:4px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
                f'<td align="center" style="background:#171a20;border:1px solid {_C.BORDE};border-radius:16px;padding:14px 6px;font-family:{_C.FUENTE};">'
                f'<div style="font-size:30px;line-height:1.1;font-weight:800;color:{color};">{n}</div>'
                f'<div style="margin-top:4px;font-size:12px;line-height:1.3;color:{_C.TEXTO_SUAVE};">{escape(etiqueta)}</div></td></tr></table></td>')
        celdas += ['<td width="33%"></td>'] * (3 - len(celdas))
        filas.append("<tr>" + "".join(celdas) + "</tr>")
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 22px;">{"".join(filas)}</table>'


def _seccion_html(titulo: str, filas: list[tuple[str, str, str]], color: str = _C.ACENTO) -> str:
    """filas = (etiqueta corta a la izquierda, texto, detalle gris)."""
    if not filas:
        return ""
    trs = []
    filas = [(et or "•", t, d) for et, t, d in filas]          # sin etiqueta, un punto del color de la sección
    for et, texto, detalle in filas[:FILAS_HTML]:
        trs.append(
            f'<tr><td width="1" valign="top" style="padding:7px 14px 7px 0;font-family:{_C.FUENTE_CODIGO};font-size:13px;line-height:1.4;color:{color};white-space:nowrap;">{escape(et)}</td>'
            f'<td valign="top" style="padding:7px 0;border-bottom:1px solid {_C.BORDE};font-family:{_C.FUENTE};font-size:15px;line-height:1.4;color:{_C.TEXTO};">{escape(texto)}'
            + (f'<div style="font-size:13px;color:{_C.TEXTO_APAGADO};">{escape(detalle)}</div>' if detalle else "") + "</td></tr>")
    if len(filas) > FILAS_HTML:
        trs.append(f'<tr><td></td><td style="padding:8px 0 0;font-family:{_C.FUENTE};font-size:13px;color:{_C.TEXTO_APAGADO};">… y {len(filas) - FILAS_HTML} más</td></tr>')
    return (f'<p style="margin:0 0 4px;font-family:{_C.FUENTE};font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:{color};">{escape(titulo)}</p>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 22px;">{"".join(trs)}</table>')


def html_resumen(r: dict) -> str:
    hoy = r["fecha"]
    plazos_y_venc = len(r["plazos"]) + len(r["vencimientos"])
    baldosas = [(n, e, c) for n, e, c in (
        (len(r["visitas_hoy"]), "visitas hoy", _C.ACENTO), (plazos_y_venc, "plazos y vencimientos", _C.ACENTO),
        (len(r["tareas_vencidas"]), "tareas atrasadas", AVISO), (len(r["tareas_hoy"]), "tareas para hoy", _C.ACENTO),
        (len(r["ausencias_por_aprobar"]), "ausencias por aprobar", _C.ACENTO),
        (len(r["correos_sin_contestar"]), "correos sin contestar", _C.ACENTO)) if n]
    partes = [_baldosas(baldosas)]
    partes.append(_seccion_html("Visitas de hoy", [(v["hora"] or "--:--", v["direccion"] or "", v["visitante"] or "") for v in r["visitas_hoy"]]))
    urgentes = ([(_cuando(z["fecha"], hoy), z["titulo"], z["cliente"] or "Plazo") for z in r["plazos"]]
                + [(_cuando(v["fecha"], hoy), f"Modelo {v['modelo']}", v["cliente"] or "Vencimiento fiscal") for v in r["vencimientos"]])
    partes.append(_seccion_html("Plazos y vencimientos", urgentes))
    partes.append(_seccion_html("Ausencias por aprobar", [("", x["persona"], f"{x['desde']}" + (f" → {x['hasta']}" if x["hasta"] != x["desde"] else "")) for x in r["ausencias_por_aprobar"]]))
    partes.append(_seccion_html("Atrasadas", [(_cuando(t["fecha"], hoy) if t["fecha"] else "", t["titulo"], "") for t in r["tareas_vencidas"]], AVISO))
    partes.append(_seccion_html("Para hoy", [("", t["titulo"], "") for t in r["tareas_hoy"]]))
    if r["correos_sin_contestar"]:
        frase = frase_correos(r["correos_sin_contestar"])
        principal, _sep, importantes = frase.partition(" · importantes: ")
        partes.append(
            f'<p style="margin:0 0 4px;font-family:{_C.FUENTE};font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:{_C.ACENTO};">Correo</p>'
            f'<p style="margin:0 0 22px;padding:12px 14px;background:#171a20;border-left:3px solid {_C.ACENTO};border-radius:0 12px 12px 0;font-family:{_C.FUENTE};font-size:15px;line-height:1.5;color:{_C.TEXTO};">'
            f'{escape(principal)}' + (f'<br><span style="color:{_C.ACENTO};font-weight:700;">Importantes:</span> {escape(importantes)}' if importantes else "") + "</p>")
    return "".join(partes)


def saludo(usuario_id: int, r: dict) -> str:
    nombre = db.nombre_mostrado_usuario(usuario_id)
    if not nombre:
        u = db.obtener_usuario(usuario_id)
        nombre = (u["email"].split("@")[0] if u is not None and u["email"] else "").replace(".", " ").title()
    return f"Buenos días{', ' + nombre.split()[0] if nombre else ''}. Esto es lo que tienes pendiente este {_fecha_larga(r['fecha'])}."


def _url(ruta: str) -> str:
    return correo_diseno.BASE + ruta


def construir_correo(usuario_id: int, r: dict) -> tuple[str, str, str]:
    """(asunto, texto plano, html) del correo del resumen."""
    titulo, corto, lineas = redactar(r)
    enlace = _url("/tareas/hoy")
    pie = "Resumen diario de pendientes · lo activas o quitas en Ajustes › Perfil"
    _plano, html = correo_diseno.construir(titulo, [saludo(usuario_id, r)], bloques_html=html_resumen(r), boton=("Abrir mi día", enlace), preencabezado=corto, pie=pie)
    plano = f"{saludo(usuario_id, r)}\n\n" + "\n".join(lineas).strip() + f"\n\nAbrir mi día: {enlace}\n\n--\n{pie}\n"
    return titulo, plano, html


def entregar(usuario_id: int, por_email: bool = True, hoy: date | None = None) -> dict:
    """Reúne y entrega el resumen de esa persona (campana + móvil, y email si procede). No hace nada si no hay pendientes."""
    from . import notificaciones

    r = reunir(usuario_id, hoy)
    if total(r) == 0:
        return {"enviado": False, "motivo": "nada pendiente"}
    titulo, corto, lineas = redactar(r)
    notificaciones.crear_y_enviar(usuario_id, "resumen_diario", titulo, corto, url="/tareas/hoy", datos={"tipo": "resumen_diario"})
    enviado_email = False
    usuario = db.obtener_usuario(usuario_id)
    destino = usuario["email"] if usuario is not None and "email" in usuario.keys() else None
    if por_email and destino and notificaciones_email.configurado():
        titulo, plano, html = construir_correo(usuario_id, r)
        try:
            notificaciones_email._enviar(destino, titulo, plano, html)
            enviado_email = True
        except notificaciones_email.ErrorNotificacionesEmail:
            pass
    return {"enviado": True, "email": enviado_email, "pendientes": total(r)}


def _toca(perfil, ahora: datetime) -> bool:
    if ahora.weekday() >= 5:                        # sábado y domingo no se molesta
        return False
    if (perfil["resumen_diario_ultimo"] or "") == ahora.date().isoformat():
        return False
    return ahora.hour >= (perfil["resumen_diario_hora"] if perfil["resumen_diario_hora"] is not None else HORA_POR_DEFECTO)


def entregar_a_quien_toca(ahora: datetime | None = None) -> int:
    """Una pasada: entrega a quien tiene el resumen activado y le toca ya. Devuelve cuántos resúmenes se entregaron."""
    ahora = ahora or datetime.now()
    hechos = 0
    for p in db.perfiles_con_resumen_diario():
        if not _toca(p, ahora):
            continue
        db.marcar_resumen_diario_entregado(p["usuario_id"], ahora.date().isoformat())      # antes de enviar: nunca dos veces el mismo día
        try:
            if entregar(p["usuario_id"], bool(p["resumen_diario_email"]), ahora.date()).get("enviado"):
                hechos += 1
        except Exception as e:  # noqa: BLE001  (un usuario con datos raros no puede tumbar a los demás)
            salud.registrar_error("resumen_diario", INTERVALO_SEGUNDOS, f"{type(e).__name__}: {e}")
    return hechos


def bucle() -> None:
    salud.registrar_ok("resumen_diario", INTERVALO_SEGUNDOS * 2, "arrancado")
    while True:
        time.sleep(INTERVALO_SEGUNDOS)
        try:
            entregar_a_quien_toca()
            salud.registrar_ok("resumen_diario", INTERVALO_SEGUNDOS * 2)
        except Exception as e:  # noqa: BLE001
            salud.registrar_error("resumen_diario", INTERVALO_SEGUNDOS * 2, f"{type(e).__name__}: {e}")
