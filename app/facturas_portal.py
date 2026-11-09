"""Facturas entre el despacho y el cliente: el despacho devuelve una factura con su motivo, el cliente la corrige o la da por vista desde el portal, y el cliente ve cómo va cada trimestre.

Sin tablas nuevas: «devuelta» es una factura `descartada` cuyo motivo está en la auditoría (`factura_contable.devuelta`); cuando el cliente la atiende (la vuelve a enviar o la da por vista) se anota
`factura_contable.devuelta_atendida` y deja de pedirle nada. Una descartada sin motivo sigue siendo lo que era: «el despacho te contactará»."""
from __future__ import annotations

import json
import re
from datetime import date

from . import auditoria, db, facturas_contables as fc

ACCION_DEVUELTA = "factura_contable.devuelta"
ACCION_ATENDIDA = "factura_contable.devuelta_atendida"
MAX_MOTIVO = 300
MAX_FILAS_TRIMESTRE = 200
MODELOS_DEL_TRIMESTRE = ("303", "130", "131", "115", "111")


# --- El despacho devuelve la factura ------------------------------------------------------------------------------------------------------------------

def devolver(tenant_id: int, usuario_id: int, factura_id: int, motivo: str) -> bool:
    """Saca del circuito una factura que anotó el cliente y le dice por qué, para que la corrija o la vuelva a enviar. Solo las del portal, y mientras no estén exportadas.
    Avisa al cliente (correo con el botón que lleva a la factura y, si lo tiene activado, un aviso en el móvil) a quien tenga acceso para corregirla. Devuelve si salió algún correo."""
    motivo = re.sub(r"\s+", " ", motivo or "").strip()
    if not motivo:
        raise ValueError("Explica al cliente qué ha de corregir.")
    if len(motivo) > MAX_MOTIVO:
        raise ValueError(f"El motivo no puede pasar de {MAX_MOTIVO} caracteres.")
    f = fc.obtener(tenant_id, usuario_id, factura_id)
    if f is None:
        raise ValueError("Factura no encontrada.")
    if f["origen"] != "portal":
        raise ValueError("Solo se pueden devolver las facturas que ha enviado el cliente desde su portal.")
    if f["estado"] not in ("pendiente", "revisada"):
        raise ValueError("Solo se puede devolver una factura pendiente o revisada.")
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        notas = ((f.get("notas") or "") + f"\nDevuelta al cliente el {ahora[:10]}: {motivo}").strip()
        conn.execute("UPDATE facturas_contables SET estado = 'descartada', actualizado_en = ?, revisado_por = NULL, revisado_en = NULL, lote_id = NULL, notas = ? WHERE id = ? AND tenant_id = ?",
                     (ahora, notas, factura_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, ACCION_DEVUELTA, "factura_contable", factura_id, {"motivo": motivo, "antes": f["estado"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return _avisar_devolucion(f, factura_id, motivo)


def _avisar_devolucion(f: dict, factura_id: int, motivo: str) -> bool:
    """Nunca rompe la devolución, que ya está hecha: un fallo de correo solo significa que el cliente se entera al entrar."""
    try:
        from . import portal_avisos, portal_recordatorios
        cliente = db.obtener_cliente_fiscal_por_id(f["cliente_fiscal_id"])
        if cliente is None:
            return False
        trimestre = fc.trimestre_de(f["fecha"])
        _ = portal_recordatorios._
        tercero = f.get("tercero_nombre") or ""

        def texto():
            return {"asunto": _("Tu gestoría te devuelve una factura: %(tercero)s", tercero=tercero), "boton": _("Corregir la factura"),
                    "lineas": [_("Hola, %(nombre)s.", nombre=cliente["nombre"]), _("Tu gestoría no ha podido tratar esta factura y te explica por qué:"), motivo,
                               _("Puedes volver a enviarla corregida o darla por vista desde tu portal.")],
                    "push": _("Tienes una factura por corregir: %(tercero)s", tercero=tercero)}
        return portal_avisos.avisar(cliente, f"/portal/facturas?trimestre={trimestre}", texto, accion="subir") > 0
    except Exception:  # noqa: BLE001
        return False


def _eventos(conn, tenant_id: int, ids: list[int]) -> dict[int, dict]:
    """{factura_id: {motivo, en, atendida}} según el último evento de devolución de cada una."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    filas = conn.execute(f"SELECT id, entidad_id, accion, detalle, creado_en FROM auditoria_eventos WHERE tenant_id = ? AND entidad = 'factura_contable' AND accion IN (?, ?) "
                         f"AND entidad_id IN ({marcas}) ORDER BY id", (tenant_id, ACCION_DEVUELTA, ACCION_ATENDIDA, *[str(i) for i in ids])).fetchall()
    res: dict[int, dict] = {}
    for e in filas:
        fid = int(e["entidad_id"])
        if e["accion"] == ACCION_DEVUELTA:
            try:
                motivo = (json.loads(e["detalle"] or "{}") or {}).get("motivo") or ""
            except ValueError:
                motivo = ""
            res[fid] = {"motivo": motivo, "en": e["creado_en"][:10], "atendida": False}
        elif fid in res:
            res[fid]["atendida"] = True
    return res


# --- Lo que ve el cliente ---------------------------------------------------------------------------------------------------------------------------

def facturas_del_cliente(cliente_fiscal_id: int, limite: int = 500) -> list[dict]:
    """Las facturas del cliente con su trimestre y, si el despacho la devolvió, el motivo (`devuelta`) y si ya la atendió (`atendida`)."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return []
    filas = fc.listar_del_cliente(cliente_fiscal_id, limite)
    conn = db.get_connection()
    try:
        eventos = _eventos(conn, cliente["tenant_id"], [f["id"] for f in filas if f["estado"] == "descartada"])
    finally:
        conn.close()
    for f in filas:
        f["trimestre"] = fc.trimestre_de(f["fecha"])
        ev = eventos.get(f["id"]) if f["estado"] == "descartada" else None
        f["devuelta"] = ev["motivo"] if ev else None
        f["devuelta_en"] = ev["en"] if ev else None
        f["atendida"] = bool(ev and ev["atendida"])
        f["pasos"] = pasos_de(f)
    mediana = mediana_dias_de_revision(cliente["tenant_id"])
    for f in filas:
        f["explicacion"], f["retraso"] = explicar(f, mediana)
    return filas


MUESTRAS_MINIMAS = 5


def mediana_dias_de_revision(tenant_id: int, hoy: date | None = None) -> int | None:
    """Los días que suele tardar este despacho en revisar una factura (mediana de las de los últimos 90 días), o None si aún hay pocas para saberlo."""
    from datetime import datetime, timedelta
    desde = ((hoy or date.today()) - timedelta(days=90)).isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT creado_en, revisado_en FROM facturas_contables WHERE tenant_id = ? AND revisado_en IS NOT NULL AND estado IN ('revisada', 'exportada') AND revisado_en >= ? LIMIT 1000", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    dias = []
    for f in filas:
        try:
            dias.append(max(0, (datetime.fromisoformat(f["revisado_en"][:19]) - datetime.fromisoformat(f["creado_en"][:19])).days))
        except (ValueError, TypeError):
            continue
    if len(dias) < MUESTRAS_MINIMAS:
        return None
    dias.sort()
    return dias[len(dias) // 2]


def explicar(f: dict, mediana: int | None, hoy: date | None = None) -> tuple[str, bool]:
    """(frase, con_retraso): qué le pasa a esta factura, quién la tiene y cuánto suele tardar. `con_retraso` si lleva esperando bastante más de lo habitual (se le ofrece avisar a la gestoría)."""
    from datetime import datetime
    from flask_babel import gettext as _, ngettext
    if f["estado"] == "descartada":
        return "", False
    hoy = hoy or date.today()
    tarda = (" " + ngettext("Suele tardar %(n)s día.", "Suele tardar unos %(n)s días.", max(1, mediana), n=max(1, mediana))) if mediana is not None else ""
    if f["estado"] == "exportada":
        return _("Contabilizada: ya cuenta en tus impuestos del trimestre."), False
    if f["estado"] == "revisada":
        return _("Revisada por tu gestoría. Entrará en la contabilidad de tu trimestre."), False
    try:
        esperando = (hoy - datetime.fromisoformat((f.get("creado_en") or "")[:10]).date()).days
    except ValueError:
        esperando = 0
    retraso = mediana is not None and esperando > max(3, 2 * mediana)
    leida = f.get("lectura") not in ("pendiente", "fallida", None)
    if retraso:
        return ngettext("Lleva %(n)s día esperando, más de lo habitual. Si tienes prisa, escribe a tu gestoría.", "Lleva %(n)s días esperando, más de lo habitual. Si tienes prisa, escribe a tu gestoría.", esperando, n=esperando), True
    if leida:
        return _("Ya está leída. Falta que alguien de tu gestoría la revise.") + tarda, False
    return _("Tu gestoría ya la tiene. Ahora toca leerla y revisarla.") + tarda, False


PASOS = ("recibida", "leida", "revisada", "contabilizada")


def pasos_de(f: dict) -> list[dict]:
    """Las cuatro etapas de una factura para el cliente (recibida → leída → revisada → contabilizada): cuáles están hechas y cuál es la actual. Una factura devuelta o descartada no tiene camino."""
    if f["estado"] == "descartada":
        return []
    hechas = {"recibida": True, "leida": f.get("lectura") not in ("pendiente", "fallida") or f["estado"] != "pendiente", "revisada": f["estado"] in ("revisada", "exportada"), "contabilizada": f["estado"] == "exportada"}
    actual = next((p for p in PASOS if not hechas[p]), None)
    return [{"clave": p, "hecho": hechas[p], "actual": p == actual} for p in PASOS]


def devueltas_por_cliente(tenant_id: int) -> dict[int, int]:
    """{cliente_fiscal_id: facturas devueltas que aún no ha atendido} de todo el despacho, en dos consultas."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, cliente_fiscal_id FROM facturas_contables WHERE tenant_id = ? AND estado = 'descartada'", (tenant_id,)).fetchall()
        ev = _eventos(conn, tenant_id, [f["id"] for f in filas])
    finally:
        conn.close()
    res: dict[int, int] = {}
    for f in filas:
        if f["id"] in ev and not ev[f["id"]]["atendida"]:
            res[f["cliente_fiscal_id"]] = res.get(f["cliente_fiscal_id"], 0) + 1
    return res


def devueltas_sin_atender(cliente_fiscal_id: int) -> list[dict]:
    return [f for f in facturas_del_cliente(cliente_fiscal_id) if f["devuelta"] is not None and not f["atendida"]]


def _devuelta_del_cliente(cliente_fiscal_id: int, factura_id: int) -> dict:
    for f in devueltas_sin_atender(cliente_fiscal_id):
        if f["id"] == factura_id:
            return f
    raise ValueError("Esa factura ya no está pendiente de corregir.")


def _marcar_atendida(cliente: dict, factura_id: int, detalle: dict) -> None:
    auditoria.registrar(cliente["tenant_id"], None, ACCION_ATENDIDA, "factura_contable", factura_id, detalle)


def reenviar(cliente_fiscal_id: int, factura_id: int, archivos: list[tuple[str, str | None, bytes]]) -> list[int]:
    """El cliente sube de nuevo la factura devuelta (la foto o el PDF corregidos). Entra como una factura nueva por leer y la devuelta deja de pedirle nada."""
    previa = _devuelta_del_cliente(cliente_fiscal_id, factura_id)
    ids = fc.subir_desde_portal(cliente_fiscal_id, previa["tipo"], archivos, nota=f"Reenviada por el cliente tras devolverle la factura {previa['numero']}: {previa['devuelta']}"[:300])
    _marcar_atendida(db.obtener_cliente_fiscal_por_id(cliente_fiscal_id), factura_id, {"nueva": ids})
    return ids


def dar_por_vista(cliente_fiscal_id: int, factura_id: int) -> None:
    """El cliente ya ha leído el motivo y no tiene nada que reenviar (no era suya, la ha corregido por otro camino…)."""
    _devuelta_del_cliente(cliente_fiscal_id, factura_id)
    _marcar_atendida(db.obtener_cliente_fiscal_por_id(cliente_fiscal_id), factura_id, {"vista": True})


# --- El tablero del trimestre -----------------------------------------------------------------------------------------------------------------------

def _trimestre_de_periodo(periodo: str | None) -> str | None:
    return periodo if re.fullmatch(r"\d{4}-T[1-4]", periodo or "") else None


def trimestre_actual(hoy: date | None = None) -> str:
    return fc.trimestre_de((hoy or date.today()).isoformat())


def _trimestres_vecinos(base: str, antes: int = 4) -> list[str]:
    anio, t = int(base[:4]), int(base[-1])
    res = []
    for _ in range(antes + 1):
        res.append(f"{anio}-T{t}")
        t -= 1
        if t == 0:
            anio, t = anio - 1, 4
    return res


def etapas(filas: list[dict]) -> dict[str, int]:
    """Cuántas facturas hay en cada etapa para el cliente. Las devueltas ya atendidas no cuentan: el reenvío entró como otra factura."""
    c = {"total": 0, "en_revision": 0, "revisadas": 0, "contabilizadas": 0, "para_corregir": 0, "no_validas": 0}
    for f in filas:
        if f["estado"] == "descartada":
            if f["devuelta"] is not None and not f["atendida"]:
                c["para_corregir"] += 1
            elif f["devuelta"] is None:
                c["no_validas"] += 1
            continue
        c["total"] += 1
        c[{"pendiente": "en_revision", "revisada": "revisadas", "exportada": "contabilizadas"}[f["estado"]]] += 1
    c["total"] += c["para_corregir"]
    return c


def tablero(cliente_fiscal_id: int, trimestre: str | None = None, hoy: date | None = None) -> dict:
    """Todo lo que el cliente necesita saber de un trimestre: sus facturas, en qué etapa está cada una, si el trimestre está cerrado y qué modelos vencen con él.
    Sin trimestre pedido (o uno inválido) enseña el del próximo modelo por presentar y, si no hay, el actual."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        raise ValueError("Cliente no encontrado.")
    hoy = hoy or date.today()
    todas = facturas_del_cliente(cliente_fiscal_id)
    vencimientos = [v for v in db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente_fiscal_id, sin_internos=True)]
    pendientes = [v for v in vencimientos if v["estado"] != "presentado" and v["modelo"] in MODELOS_DEL_TRIMESTRE and _trimestre_de_periodo(v["periodo"])]
    proximo = min(pendientes, key=lambda v: v["fecha_limite"], default=None)
    try:
        fc.rango_del_trimestre(trimestre or "")
    except ValueError:
        trimestre = _trimestre_de_periodo(proximo["periodo"]) if proximo else trimestre_actual(hoy)
    disponibles = sorted({f["trimestre"] for f in todas} | set(_trimestres_vecinos(trimestre_actual(hoy), 3)) | {trimestre}, reverse=True)
    del_trimestre = [f for f in todas if f["trimestre"] == trimestre][:MAX_FILAS_TRIMESTRE]
    cuentas = etapas(del_trimestre)
    cierre = fc.periodos_cerrados(cliente["tenant_id"], cliente_fiscal_id, [trimestre]).get(trimestre)
    modelos = [{"id": v["id"], "modelo": v["modelo"], "fecha_limite": v["fecha_limite"], "presentado": v["estado"] == "presentado"} for v in vencimientos if v["periodo"] == trimestre and v["modelo"] in MODELOS_DEL_TRIMESTRE]
    modelos.sort(key=lambda m: (m["fecha_limite"], m["modelo"]))
    if cuentas["para_corregir"]:
        situacion = "corregir"
    elif cuentas["total"] == 0:
        situacion = "vacio"
    elif cuentas["en_revision"] or cuentas["revisadas"]:
        situacion = "revision"
    else:
        situacion = "al_dia"
    otras_devueltas: dict[str, int] = {}
    for f in todas:
        if f["trimestre"] != trimestre and f["devuelta"] is not None and not f["atendida"]:
            otras_devueltas[f["trimestre"]] = otras_devueltas.get(f["trimestre"], 0) + 1
    atendidas = cuentas["contabilizadas"] + cuentas["revisadas"]
    return {"trimestre": trimestre, "disponibles": disponibles, "facturas": del_trimestre, "cuentas": cuentas, "situacion": situacion, "cerrado": cierre, "modelos": modelos,
            "avance": atendidas, "otras_devueltas": dict(sorted(otras_devueltas.items(), reverse=True)), "hay_mas": len([f for f in todas if f["trimestre"] == trimestre]) > MAX_FILAS_TRIMESTRE}


def etiqueta_trimestre(trimestre: str) -> str:
    """«2026-T2» → «2T 2026»."""
    return f"{trimestre[-1]}T {trimestre[:4]}"


def para_el_inicio(cliente_fiscal_id: int) -> dict:
    """Lo mínimo que la portada del portal necesita de las facturas: cuántas debe corregir y cuántas esperan al despacho."""
    cuentas = etapas(facturas_del_cliente(cliente_fiscal_id))
    return {"para_corregir": cuentas["para_corregir"], "en_revision": cuentas["en_revision"]}



# --- Hilo de mensajes de cada factura ---------------------------------------------------------------------------------------------------------------

MAX_MENSAJE = 1000
MAX_MENSAJES_POR_FACTURA = 200


def _texto_valido(texto: str) -> str:
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Escribe el mensaje.")
    if len(texto) > MAX_MENSAJE:
        raise ValueError(f"El mensaje no puede pasar de {MAX_MENSAJE} caracteres.")
    return texto


def mensajes(tenant_id: int, factura_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(m) for m in conn.execute("SELECT m.id, m.autor, m.texto, m.creado_en, m.leido_en, u.email AS usuario_email FROM facturas_contables_mensajes m LEFT JOIN usuarios u ON u.id = m.usuario_id "
                                              "WHERE m.tenant_id = ? AND m.factura_id = ? ORDER BY m.id", (tenant_id, factura_id))]
    finally:
        conn.close()


def _insertar_mensaje(tenant_id: int, factura_id: int, autor: str, usuario_id: int | None, texto: str) -> int:
    conn = db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM facturas_contables_mensajes WHERE tenant_id = ? AND factura_id = ?", (tenant_id, factura_id)).fetchone()[0] >= MAX_MENSAJES_POR_FACTURA:
            raise ValueError("Esta conversación ya es muy larga: escribe a tu gestoría por otra vía.")
        cur = conn.execute("INSERT INTO facturas_contables_mensajes (tenant_id, factura_id, autor, usuario_id, texto, creado_en) VALUES (?, ?, ?, ?, ?, ?)", (tenant_id, factura_id, autor, usuario_id, texto, db.now_iso()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def escribir_como_cliente(cliente_fiscal_id: int, factura_id: int, texto: str) -> int:
    """El cliente escribe en una factura SUYA (cualquier otra es «no encontrada»). Avisa a quien lleva al cliente."""
    texto = _texto_valido(texto)
    f = detalle_del_cliente(cliente_fiscal_id, factura_id)
    if f is None:
        raise ValueError("Factura no encontrada.")
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    mid = _insertar_mensaje(cliente["tenant_id"], factura_id, "cliente", None, texto)
    fc._avisar_al_despacho(cliente, factura_id, {"tercero_nombre": f["tercero_nombre"], "numero": f["numero"]}, titulo=f"{cliente['nombre']} ha escrito sobre una factura")
    return mid


def escribir_como_despacho(tenant_id: int, usuario_id: int, factura_id: int, texto: str) -> int:
    texto = _texto_valido(texto)
    if fc.obtener(tenant_id, usuario_id, factura_id) is None:
        raise ValueError("Factura no encontrada.")
    return _insertar_mensaje(tenant_id, factura_id, "empleado", usuario_id, texto)


def marcar_leidos(tenant_id: int, factura_id: int, lee: str) -> None:
    """Quien abre la conversación marca como leídos los mensajes del otro lado (`lee`: «cliente» o «empleado»)."""
    otro = "empleado" if lee == "cliente" else "cliente"
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables_mensajes SET leido_en = ? WHERE tenant_id = ? AND factura_id = ? AND autor = ? AND leido_en IS NULL", (db.now_iso(), tenant_id, factura_id, otro))
        conn.commit()
    finally:
        conn.close()


def sin_leer_para_cliente(cliente_fiscal_id: int) -> list[dict]:
    """Facturas del cliente en las que el despacho le ha escrito sin que lo haya leído: [{factura_id, numero, tercero_nombre, n}]."""
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT x.id AS factura_id, x.numero, x.tercero_nombre, COUNT(*) AS n FROM facturas_contables_mensajes m JOIN facturas_contables x ON x.id = m.factura_id AND x.tenant_id = m.tenant_id "
            "WHERE x.cliente_fiscal_id = ? AND m.autor = 'empleado' AND m.leido_en IS NULL GROUP BY x.id, x.numero, x.tercero_nombre ORDER BY MIN(m.id)", (cliente_fiscal_id,))]
    finally:
        conn.close()


def con_mensajes_sin_leer_del_cliente(tenant_id: int, ids: list[int]) -> set[int]:
    ids = [int(i) for i in ids]
    if not ids:
        return set()
    conn = db.get_connection()
    try:
        return {r["factura_id"] for r in conn.execute(f"SELECT DISTINCT factura_id FROM facturas_contables_mensajes WHERE tenant_id = ? AND autor = 'cliente' AND leido_en IS NULL AND factura_id IN ({','.join('?' * len(ids))})", (tenant_id, *ids))}
    finally:
        conn.close()


def detalle_del_cliente(cliente_fiscal_id: int, factura_id: int) -> dict | None:
    """Lo que el cliente ve de UNA de sus facturas (como en `facturas_del_cliente`), o None si no es suya."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, tipo, fecha, numero, tercero_nombre, total_centimos, estado, origen, documento_id FROM facturas_contables WHERE id = ? AND cliente_fiscal_id = ? AND tenant_id = ?",
                         (factura_id, cliente_fiscal_id, cliente["tenant_id"])).fetchone()
        if f is None:
            return None
        f = dict(f)
        ev = _eventos(conn, cliente["tenant_id"], [factura_id]).get(factura_id) if f["estado"] == "descartada" else None
    finally:
        conn.close()
    f["trimestre"] = fc.trimestre_de(f["fecha"])
    f["devuelta"], f["devuelta_en"], f["atendida"] = (ev["motivo"], ev["en"], ev["atendida"]) if ev else (None, None, False)
    return f


# --- Archivos que ya se enviaron --------------------------------------------------------------------------------------------------------------------

def archivos_ya_enviados(cliente_fiscal_id: int, huellas: list[str]) -> dict[str, str]:
    """{huella SHA-256: fecha de envío} de los archivos que el cliente ya tiene anotados en una factura no descartada. Solo mira huellas válidas y como mucho 20."""
    huellas = [h.lower() for h in huellas if re.fullmatch(r"[0-9a-fA-F]{64}", h or "")][:20]
    if not huellas:
        return {}
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT d.hash_sha256 AS huella, MIN(x.creado_en) AS desde FROM cliente_documentos d JOIN facturas_contables x ON x.documento_id = d.id AND x.cliente_fiscal_id = d.cliente_fiscal_id "
                             f"WHERE d.cliente_fiscal_id = ? AND x.estado != 'descartada' AND d.hash_sha256 IN ({','.join('?' * len(huellas))}) GROUP BY d.hash_sha256", (cliente_fiscal_id, *huellas)).fetchall()
    finally:
        conn.close()
    return {f["huella"]: f["desde"][:10] for f in filas}


def trimestres_cerrados(cliente_fiscal_id: int, hoy: date | None = None) -> list[str]:
    """Los últimos ocho trimestres que el despacho tiene cerrados para este cliente (para avisarle al escribir la fecha de una factura)."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return []
    candidatos = _trimestres_vecinos(trimestre_actual(hoy), 7)
    return sorted(fc.periodos_cerrados(cliente["tenant_id"], cliente_fiscal_id, candidatos))
