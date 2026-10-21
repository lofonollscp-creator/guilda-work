"""Resumen semanal de tareas por correo (opcional, de cada persona, solo para ella).

Política, explícita:
- **Opt-in y personal**: nadie recibe nada sin activarlo, y cada resumen va solo al correo de quien lo pidió. No hay destinatarios externos ni envíos «en nombre de» otra persona.
- **Mismo alcance que la pantalla** (`informes_tareas.informe`): solo las tareas que esa persona puede ver; un correo nunca revela más que su pantalla de Informes.
- **Una vez por semana natural** (lunes a domingo): se manda el primer día de la semana en que corre la pasada diaria; si el servidor estuvo parado el lunes, sale el martes, y así. Quien se suscribe a media
  semana empieza la semana siguiente (no recibe un correo al instante ni al día siguiente).
- **Sin ruido**: si no hay nada que contar (ni abiertas, ni próximas, ni actividad en la semana) no se manda, pero la semana queda como atendida.
- **Reintento sin duplicar**: si el envío falla, la semana NO queda marcada y la siguiente pasada diaria lo reintenta; si sale bien, se marca antes de pasar a la siguiente persona.
- Si el correo saliente no está configurado, se corta la pasada entera sin tocar a nadie (se reintenta cuando lo esté).
- Si la persona ya no existe o ya no tiene despacho, la suscripción se desactiva sola."""
from __future__ import annotations

from datetime import date, timedelta

from . import correo_diseno, db, db_plataforma, informes_tareas, notificaciones_email
from .notificaciones_email import _          # texto traducible; fuera de una petición (la pasada diaria) devuelve el español

DIAS_VENTANA = 7
DIAS_PROXIMOS = 7
MAX_LINEAS = 10                      # por sección: el correo es un resumen, no el informe entero


def _lunes(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def esta_suscrito(usuario_id: int) -> bool:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT activa FROM informes_tareas_suscripciones WHERE usuario_id = ?", (usuario_id,)).fetchone()
        return bool(f and f["activa"])
    finally:
        conn.close()


def suscribir(usuario_id: int, activa: bool, hoy: date | None = None) -> bool:
    """Activa o desactiva el resumen semanal de esa persona. False si no pertenece a ningún despacho (no hay informe que mandarle)."""
    hoy = hoy or date.today()
    tenant = db_plataforma.tenant_de_usuario(usuario_id)
    if tenant is None:
        return False
    conn = db.get_connection()
    try:
        # Al activar se da por atendida la semana en curso: el primer correo llega el lunes siguiente.
        conn.execute(
            """INSERT INTO informes_tareas_suscripciones (usuario_id, tenant_id, activa, ultimo_envio, creada_en) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(usuario_id) DO UPDATE SET activa = excluded.activa, tenant_id = excluded.tenant_id,
                   ultimo_envio = CASE WHEN excluded.activa = 1 AND informes_tareas_suscripciones.activa = 0 THEN excluded.ultimo_envio ELSE informes_tareas_suscripciones.ultimo_envio END""",
            (usuario_id, tenant["id"], int(bool(activa)), hoy.isoformat(), hoy.isoformat()))
        conn.commit()
    finally:
        conn.close()
    return True


def _desactivar(usuario_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE informes_tareas_suscripciones SET activa = 0 WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def _marcar_enviado(usuario_id: int, hoy: date) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE informes_tareas_suscripciones SET ultimo_envio = ? WHERE usuario_id = ?", (hoy.isoformat(), usuario_id))
        conn.commit()
    finally:
        conn.close()


def _hay_algo_que_contar(r: dict) -> bool:
    p = r["proximas"]
    return bool(r["ahora"]["abiertas"] or r["creadas_en_ventana"] or r["en_ventana"]["completadas"] or p["tareas"] or p["vencimientos_fiscales"] or p["certificados"])


def componer(r: dict) -> tuple[str, list[str], str]:
    """(titulo, parrafos, preformateado) del resumen a partir de un informe ya calculado. Texto de usuarios (asuntos, clientes) solo va en el bloque preformateado, que el diseño escapa."""
    ahora, hist, v, p = r["ahora"], r["en_ventana"], r["ventana"], r["proximas"]
    tasa = "—" if hist["tasa_en_plazo"] is None else f'{str(hist["tasa_en_plazo"]).replace(".", ",")} % ({hist["en_plazo"]}/{hist["con_fecha"]})'
    parrafos = [
        _("Tu semana en tareas, del %(desde)s al %(hasta)s. Solo cuenta lo que tú puedes ver.", desde=v["desde"], hasta=v["hasta"]),
        _("Ahora: %(a)s abiertas, %(v)s vencidas, %(b)s bloqueadas. En estos días: %(c)s creadas, %(h)s completadas, cumplimiento en plazo %(t)s.",
          a=ahora["abiertas"], v=ahora["vencidas"], b=ahora["bloqueadas"], c=r["creadas_en_ventana"], h=hist["completadas"], t=tasa),
    ]
    lineas: list[str] = []

    def seccion(titulo: str, filas: list[str], total: int) -> None:
        if not filas:
            return
        lineas.extend([titulo, *[f"  · {f}" for f in filas[:MAX_LINEAS]]])
        if total > MAX_LINEAS:
            lineas.append("  " + _("… y %(n)s más", n=total - MAX_LINEAS))
        lineas.append("")

    seccion(_("Tareas que vencen en los próximos %(n)s días", n=p["dias"]), [f'{t["fecha"]}  {t["asunto"]}' for t in p["tareas"]], len(p["tareas"]))
    seccion(_("Vencimientos fiscales"), [f'{x["fecha_limite"]}  {x["modelo"]} {x["periodo"]} · {x["cliente"] or "—"}' for x in p["vencimientos_fiscales"]], len(p["vencimientos_fiscales"]))
    seccion(_("Certificados que caducan"), [f'{c["caduca"]}  {c["titular"] or "—"}' for c in p["certificados"]], len(p["certificados"]))
    seccion(_("Bloqueadas"), [f'{b["dias"]} {_("días")}  {b["asunto"]}' + (f' — {b["motivo"]}' if b["motivo"] else "") for b in r["bloqueadas"]], len(r["bloqueadas"]))
    return _("Tu resumen semanal de tareas"), parrafos, "\n".join(lineas).rstrip()


def _correo_de(usuario_id: int) -> str | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT email FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return f["email"] if f else None
    finally:
        conn.close()


def enviar_pendientes(hoy: date | None = None, enviar=None) -> dict:
    """Manda el resumen a quien toca esta semana. `enviar(destino, asunto, plano, html)` se puede sustituir (pruebas). Devuelve {enviados, vacios, errores, desactivados, sin_correo_saliente}."""
    hoy = hoy or date.today()
    enviar = enviar or notificaciones_email._enviar
    res = {"enviados": 0, "vacios": 0, "errores": 0, "desactivados": 0, "sin_correo_saliente": False}
    if enviar is notificaciones_email._enviar and not notificaciones_email.configurado():
        res["sin_correo_saliente"] = True
        return res
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT usuario_id, tenant_id FROM informes_tareas_suscripciones WHERE activa = 1 AND (ultimo_envio IS NULL OR ultimo_envio < ?) ORDER BY usuario_id",
                             (_lunes(hoy).isoformat(),)).fetchall()
    finally:
        conn.close()
    for f in filas:
        uid = f["usuario_id"]
        try:
            tenant = db_plataforma.tenant_de_usuario(uid)
            correo = _correo_de(uid)
            if tenant is None or not correo:
                _desactivar(uid)
                res["desactivados"] += 1
                continue
            r = informes_tareas.informe(tenant["id"], uid, (hoy - timedelta(days=DIAS_VENTANA - 1)).isoformat(), hoy.isoformat(), DIAS_PROXIMOS, hoy)
            if not _hay_algo_que_contar(r):
                _marcar_enviado(uid, hoy)
                res["vacios"] += 1
                continue
            titulo, parrafos, detalle = componer(r)
            marca = notificaciones_email._marca(tenant["id"])
            plano, html = correo_diseno.construir(titulo, parrafos, preformateado=detalle or None, boton=(_("Ver el informe completo"), f"{correo_diseno.BASE}/tareas/informes"),
                                                  aviso=_("Recibes este resumen porque lo activaste en Tareas › Informes. Puedes desactivarlo allí cuando quieras."), preencabezado=parrafos[1], marca=marca)
            enviar(correo, notificaciones_email._asunto(titulo, tenant["id"]), plano, html)
            _marcar_enviado(uid, hoy)
            res["enviados"] += 1
        except Exception as e:                            # noqa: BLE001 -- una persona con problemas no corta al resto; la semana no queda marcada y se reintenta mañana
            res["errores"] += 1
            res.setdefault("detalle", []).append(f"{uid}: {type(e).__name__}: {e}")
    return res
