"""Flujo de trabajo de las obligaciones fiscales (especificación de control fiscal, RF-02 y RF-03).

Una obligación (un `vencimiento_fiscal`: cliente + modelo + período) tiene una **fase de trabajo** además del estado de siempre:

    pendiente → en_preparacion → en_revision → aprobada → presentada → cerrada          (alternativas: no_aplica, anulada)

- `estado` (pendiente / presentado / fuera_plazo) sigue siendo lo que leen pantallas, API, recordatorios y portal: es la **proyección** de la fase (presentada y cerrada = «presentado»).
- `vencida`, `en_riesgo` y `bloqueada` son **indicadores independientes** de la fase, no estados de trabajo (`indicadores()`); una obligación presentada tarde conserva la marca `presentada_tarde`.
- **Flujo flexible (por defecto) o estricto** (por despacho, `fiscal_config.flujo_estricto`): en el flexible se puede presentar desde cualquier fase de trabajo y no hace falta aprobar;
  en el estricto hay que pasar por revisión y aprobación. Así nadie pierde su forma de trabajar el día que se estrena esto.
- **Evidencias**: presentar exige declarar cuándo se presentó (y, si se quiere, organismo, referencia/CSV y justificante). Una evidencia declarada a mano se muestra como «presentación declarada por
  el gestor», no como confirmada. Ni subir un documento ni enviar un correo presentan nada solos. Con `exigir_justificante`, cerrar exige un justificante subido.
- **Quién puede qué**: aprobar y declarar «no aplica» o «anulada» (siempre con motivo) es de la dirección o del revisor fiscal; devolver una obligación a preparación exige motivo y queda anotado;
  el auditor solo lee. Todo cambio guarda su evento de auditoría **en la misma transacción**.
- **Concurrencia**: si se indica `version` y la obligación ya cambió, se rechaza (`ConflictoDeVersion`) en vez de pisar el trabajo de otra persona."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import acceso, auditoria, db

FASES = ("pendiente", "en_preparacion", "en_revision", "aprobada", "presentada", "cerrada", "no_aplica", "anulada")
ACTIVAS = ("pendiente", "en_preparacion", "en_revision", "aprobada")
FINALES = ("cerrada", "no_aplica", "anulada")
PRESENTADAS = ("presentada", "cerrada")
_ESTRICTO = {
    "pendiente": {"en_preparacion", "no_aplica", "anulada"},
    "en_preparacion": {"en_revision", "pendiente", "no_aplica", "anulada"},
    "en_revision": {"aprobada", "en_preparacion", "no_aplica", "anulada"},
    "aprobada": {"presentada", "en_preparacion", "no_aplica", "anulada"},
    "presentada": {"cerrada"},
}
DIAS_RIESGO = 7


class ConflictoDeVersion(ValueError):
    """Otra persona cambió la obligación mientras se editaba: hay que volver a leerla y decidir."""


def config(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT flujo_estricto, exigir_justificante FROM fiscal_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return {"flujo_estricto": bool(f["flujo_estricto"]) if f else False, "exigir_justificante": bool(f["exigir_justificante"]) if f else False}


def guardar_config(tenant_id: int, usuario_id: int, *, flujo_estricto: bool, exigir_justificante: bool) -> None:
    if not acceso.es_directivo(usuario_id) or db.tenant_de_usuario(usuario_id) is None or db.tenant_de_usuario(usuario_id)["id"] != tenant_id:
        raise ValueError("Solo la dirección del despacho (supervisores) puede cambiar el flujo de trabajo fiscal.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO fiscal_config (tenant_id, flujo_estricto, exigir_justificante) VALUES (?, ?, ?) ON CONFLICT(tenant_id) DO UPDATE SET "
                     "flujo_estricto = excluded.flujo_estricto, exigir_justificante = excluded.exigir_justificante", (tenant_id, int(flujo_estricto), int(exigir_justificante)))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.config", "despacho", tenant_id, {"flujo_estricto": flujo_estricto, "exigir_justificante": exigir_justificante}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def indicadores(v, hoy: date | None = None) -> dict:
    """`vencida`, `en_riesgo`, `bloqueada` y `presentada_tarde`: se calculan, no son estados de trabajo (se pueden dar con cualquier fase activa)."""
    hoy = hoy or date.today()
    activa = v["fase"] in ACTIVAS
    try:
        dias = (date.fromisoformat(v["fecha_limite"][:10]) - hoy).days
    except ValueError:
        dias = None
    vencida = bool(activa and dias is not None and dias < 0)
    sin_empezar = v["fase"] in ("pendiente", "en_preparacion")
    riesgo = bool(activa and not vencida and dias is not None and ((dias <= 3) or (dias <= DIAS_RIESGO and sin_empezar) or (v["bloqueada"] and dias <= 15)))
    return {"vencida": vencida, "en_riesgo": riesgo, "bloqueada": bool(v["bloqueada"]), "presentada_tarde": bool(v["presentada_tarde"]), "dias_restantes": dias}


def _destinos(fase: str, estricto: bool) -> set[str]:
    base = set(_ESTRICTO.get(fase, set()))
    if not estricto and fase in ACTIVAS:
        base.add("presentada")                      # flujo flexible: se presenta desde cualquier fase de trabajo
    return base


def destinos_permitidos(tenant_id: int, usuario_id: int, v) -> list[str]:
    """Las fases a las que ESTA persona puede mover ahora la obligación (para los botones de la ficha)."""
    if not acceso.puede_modificar_cliente(tenant_id, usuario_id, v["cliente_fiscal_id"]):
        return []
    autoriza = acceso.puede_autorizar(tenant_id, usuario_id)
    res = []
    for d in sorted(_destinos(v["fase"], config(tenant_id)["flujo_estricto"]), key=FASES.index):
        if d in ("aprobada", "no_aplica", "anulada") and not autoriza:
            continue
        if d == "en_preparacion" and v["fase"] == "en_revision" and not autoriza:
            continue
        res.append(d)
    return res


def _fecha_presentacion(valor) -> str:
    texto = (valor or "").strip() if isinstance(valor, str) else ""
    if not texto:
        return datetime.now().isoformat(timespec="minutes")
    try:
        d = datetime.fromisoformat(texto.replace("Z", "+00:00")) if "T" in texto or " " in texto else datetime.strptime(texto[:10], "%Y-%m-%d")
    except ValueError:
        raise ValueError("La fecha de presentación no es válida (usa AAAA-MM-DD o AAAA-MM-DDTHH:MM).") from None
    d = d.astimezone().replace(tzinfo=None) if d.tzinfo else d
    if d > datetime.now() + timedelta(hours=1):
        raise ValueError("La fecha de presentación no puede estar en el futuro.")
    return d.isoformat(timespec="minutes")


def evidencias(tenant_id: int, vencimiento_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT e.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS actor FROM obligaciones_evidencias e LEFT JOIN usuarios u ON u.id = e.declarada_por "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = e.declarada_por WHERE e.tenant_id = ? AND e.vencimiento_id = ? ORDER BY e.id DESC", (tenant_id, vencimiento_id))]
    finally:
        conn.close()


def _tiene_justificante(conn, vencimiento_id: int) -> bool:
    return conn.execute("SELECT 1 FROM vencimientos_fiscales_documentos WHERE vencimiento_id = ? AND origen = 'justificante' LIMIT 1", (vencimiento_id,)).fetchone() is not None


def transicionar(tenant_id: int, usuario_id: int, vencimiento_id: int, destino: str, *, motivo: str | None = None, presentacion: dict | None = None, version: int | None = None) -> dict:
    """Mueve la obligación a otra fase si el flujo y los permisos de quien lo pide lo permiten. `presentacion` (para «presentada»): `{"presentado_en", "organismo", "referencia", "documento_id"}`.
    Devuelve `{"fase", "estado", "version"}`. Lanza `ValueError` con el motivo (o `ConflictoDeVersion`) y no cambia nada si algo falla."""
    if destino not in FASES:
        raise ValueError("Fase no válida.")
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT * FROM vencimientos_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (vencimiento_id, tenant_id)).fetchone()
        if v is None or not acceso.puede_ver_cliente(tenant_id, usuario_id, v["cliente_fiscal_id"]):
            raise ValueError("No existe esa obligación.")
        if not acceso.puede_modificar_cliente(tenant_id, usuario_id, v["cliente_fiscal_id"]):
            raise ValueError("Con tu rol solo puedes consultar esta obligación.")
        if version is not None and int(version) != v["version"]:
            raise ConflictoDeVersion("Otra persona ha cambiado esta obligación mientras la editabas. Recárgala y revisa los cambios antes de volver a intentarlo.")
        cfg = config(tenant_id)
        actual = v["fase"]
        if destino == actual:
            raise ValueError(f"Ya está en «{actual}».")
        if destino not in _destinos(actual, cfg["flujo_estricto"]):
            raise ValueError(f"No se puede pasar de «{actual}» a «{destino}»" + (" con el flujo estricto de este despacho." if cfg["flujo_estricto"] else "."))
        autoriza = acceso.puede_autorizar(tenant_id, usuario_id)
        motivo = (motivo or "").strip()[:500] or None
        if destino in ("aprobada", "no_aplica", "anulada") and not autoriza:
            raise ValueError("Solo la dirección o el revisor fiscal puede aprobar o declarar una obligación «no aplica» o «anulada».")
        if destino in ("no_aplica", "anulada") and not motivo:
            raise ValueError("Indica la justificación.")
        if destino == "en_preparacion" and actual in ("en_revision", "aprobada"):
            if actual == "en_revision" and not autoriza:
                raise ValueError("Solo quien revisa puede devolver una obligación en revisión.")
            if not motivo:
                raise ValueError("Indica por qué se devuelve a preparación.")
        evidencia = None
        if destino == "presentada":
            p = presentacion or {}
            evidencia = {"presentado_en": _fecha_presentacion(p.get("presentado_en")), "organismo": (p.get("organismo") or "").strip()[:80] or None,
                         "referencia": (p.get("referencia") or "").strip()[:120] or None, "documento_id": p.get("documento_id")}
            if cfg["exigir_justificante"] and not evidencia["documento_id"] and not _tiene_justificante(conn, vencimiento_id):
                raise ValueError("Este despacho exige un justificante para presentar: sube el justificante oficial.")
            if evidencia["documento_id"] and conn.execute("SELECT 1 FROM vencimientos_fiscales_documentos WHERE id = ? AND vencimiento_id = ?", (evidencia["documento_id"], vencimiento_id)).fetchone() is None:
                raise ValueError("El documento indicado no pertenece a esta obligación.")
        if destino == "cerrada":
            if conn.execute("SELECT 1 FROM obligaciones_evidencias WHERE vencimiento_id = ? LIMIT 1", (vencimiento_id,)).fetchone() is None:
                raise ValueError("No se puede cerrar sin la evidencia de la presentación.")
            if cfg["exigir_justificante"] and not _tiene_justificante(conn, vencimiento_id):
                raise ValueError("Este despacho exige el justificante oficial para cerrar: súbelo antes.")
        estado = "presentado" if destino in PRESENTADAS else ("pendiente" if v["estado"] == "presentado" else v["estado"])
        extra, extra_p = "", []
        if destino in ("no_aplica", "anulada"):
            extra, extra_p = ", papelera_en = ?", [db._marca_papelera()]
        if destino == "presentada":
            tarde = int(evidencia["presentado_en"][:10] > v["fecha_limite"][:10])
            extra += ", presentada_tarde = ?"; extra_p.append(tarde)
        cur = conn.execute(
            f"UPDATE vencimientos_fiscales SET fase = ?, estado = ?, fase_motivo = ?, actualizado_en = ?, version = version + 1{extra} WHERE id = ? AND tenant_id = ? AND version = ?",
            [destino, estado, motivo if destino in ("no_aplica", "anulada", "en_preparacion") else v["fase_motivo"], db.now_iso(), *extra_p, vencimiento_id, tenant_id, v["version"]])
        if cur.rowcount == 0:
            raise ConflictoDeVersion("Otra persona ha cambiado esta obligación a la vez. Recárgala y vuelve a intentarlo.")
        if evidencia:
            conn.execute("INSERT INTO obligaciones_evidencias (tenant_id, vencimiento_id, presentado_en, organismo, referencia, documento_id, procedencia, declarada_por, creado_en) "
                         "VALUES (?, ?, ?, ?, ?, ?, 'declarada_por_gestor', ?, ?)", (tenant_id, vencimiento_id, evidencia["presentado_en"], evidencia["organismo"], evidencia["referencia"], evidencia["documento_id"], usuario_id, db.now_iso()))
        accion = "obligacion.rechazo" if destino == "en_preparacion" and actual in ("en_revision", "aprobada") else "obligacion.transicion"
        auditoria.registrar(tenant_id, usuario_id, accion, "obligacion", vencimiento_id,
                            {"de": actual, "a": destino, "motivo": motivo, "version": v["version"] + 1, "evidencia": bool(evidencia), "cliente_fiscal_id": v["cliente_fiscal_id"]}, conn=conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    db._reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)
    _avisar(tenant_id, usuario_id, v, actual, destino, motivo)
    return {"fase": destino, "estado": estado, "version": v["version"] + 1}


def _avisar(tenant_id: int, autor_id: int, v, de: str, a: str, motivo: str | None) -> None:
    """Avisa a quien debe actuar: a quien revisa cuando algo entra en revisión; a quien lo preparaba cuando se le devuelve."""
    try:
        from . import notificaciones
        titulo_cliente = db.obtener_cliente_fiscal(tenant_id, v["cliente_fiscal_id"])
        nombre = (titulo_cliente["nombre"] if titulo_cliente else "") or ""
        url = f"/fiscal/vencimientos/{v['id']}/editar"
        if a == "en_revision":
            for u in db.usuarios_de_tenant(tenant_id):
                if u != autor_id and acceso.puede_autorizar(tenant_id, u) and acceso.puede_ver_cliente(tenant_id, u, v["cliente_fiscal_id"]):
                    notificaciones.crear_y_enviar(u, "obligacion", "Obligación para revisar", f"{v['modelo']} {v['periodo']} · {nombre}", url=url, datos={"tipo": "obligacion"})
        elif a == "en_preparacion" and de in ("en_revision", "aprobada") and v["usuario_id"] and v["usuario_id"] != autor_id:
            notificaciones.crear_y_enviar(v["usuario_id"], "obligacion", "Obligación devuelta a preparación", f"{v['modelo']} {v['periodo']} · {nombre}: {motivo}", url=url, datos={"tipo": "obligacion"})
    except Exception:  # noqa: BLE001  (un aviso que falla nunca deshace la transición)
        pass


def bloquear(tenant_id: int, usuario_id: int, vencimiento_id: int, motivo: str | None, *, bloqueada: bool = True) -> None:
    """Marca (o quita) la obligación como bloqueada: espera algo (documentación del cliente, un tercero) pero **el reloj legal no se detiene**. Es un indicador, no una fase."""
    motivo = (motivo or "").strip()[:300]
    if bloqueada and not motivo:
        raise ValueError("Indica qué se está esperando.")
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT * FROM vencimientos_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (vencimiento_id, tenant_id)).fetchone()
        if v is None or not acceso.puede_modificar_cliente(tenant_id, usuario_id, v["cliente_fiscal_id"]):
            raise ValueError("No existe esa obligación.")
        if v["fase"] not in ACTIVAS:
            raise ValueError("Solo se bloquea una obligación en trabajo.")
        conn.execute("UPDATE vencimientos_fiscales SET bloqueada = ?, bloqueo_motivo = ?, version = version + 1, actualizado_en = ? WHERE id = ?",
                     (int(bloqueada), motivo if bloqueada else None, db.now_iso(), vencimiento_id))
        auditoria.registrar(tenant_id, usuario_id, "obligacion.bloqueo" if bloqueada else "obligacion.desbloqueo", "obligacion", vencimiento_id, {"motivo": motivo or None}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def resumen(tenant_id: int, usuario_id: int, v, hoy: date | None = None) -> dict:
    """Todo lo que la ficha necesita: fase, indicadores, a dónde puede ir esta persona y las evidencias."""
    return {"fase": v["fase"], "version": v["version"], "indicadores": indicadores(v, hoy), "destinos": destinos_permitidos(tenant_id, usuario_id, v),
            "evidencias": evidencias(tenant_id, v["id"]), "config": config(tenant_id), "motivo": v["fase_motivo"], "bloqueo_motivo": v["bloqueo_motivo"]}


def exigir_para_marcar_presentado(tenant_id: int, usuario_id: int, v, *, con_justificante: bool = False) -> None:
    """El botón «Presentado» de siempre respeta las reglas del despacho: con el flujo estricto hay que pasar por la ficha (revisión y aprobación), y con «exigir justificante»
    no se presenta sin él. Lanza ValueError con lo que falta."""
    cfg = config(tenant_id)
    if v["fase"] in PRESENTADAS:
        return
    if cfg["flujo_estricto"] and v["fase"] != "aprobada":
        raise ValueError("Este despacho trabaja con flujo estricto: la obligación tiene que estar aprobada antes de presentarla. Hazlo desde su ficha.")
    if cfg["exigir_justificante"] and not con_justificante:
        conn = db.get_connection()
        try:
            if not _tiene_justificante(conn, v["id"]):
                raise ValueError("Este despacho exige el justificante oficial para presentar: adjúntalo al marcar la obligación como presentada.")
        finally:
            conn.close()


def exigir_para_cambiar_estado(tenant_id: int, usuario_id: int, v, nuevo_estado: str | None) -> None:
    """Editar el estado a mano («presentado») no es una vía de escape del flujo del despacho: pasa por las mismas reglas que el botón de presentar."""
    if nuevo_estado == "presentado" and v["estado"] != "presentado":
        exigir_para_marcar_presentado(tenant_id, usuario_id, v)
