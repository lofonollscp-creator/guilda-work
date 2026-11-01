"""Plantillas recurrentes de Guilda Fiscal: un apunte modelo (alquiler, gasto fijo) que se repite solo cada mes o cada trimestre.

Una persona que puede aprobar apuntes define la plantilla a partir de un apunte ya aprobado (importes, retención de IRPF, contraparte); desde entonces `generar` crea, para cada fecha que toca y ya ha llegado, una copia
APROBADA del apunte, igual que el «Repetir cada mes» manual: entra en el 303 y el 130 del periodo. Cada copia queda en la auditoría como hecha por el sistema a nombre de quien creó la plantilla, y a esa persona se le avisa.
La plantilla se puede pausar o borrar, y un apunte generado se anula como cualquier otro.

Reglas: no se crean apuntes con fecha futura (no se validarían); una fecha que ya tiene un apunte igual (misma contraparte, libro, importe y mes) se salta, así que ejecutar dos veces no duplica; si la persona que
creó la plantilla ya no puede aprobar, o el apunte deja de validarse, la plantilla se queda donde estaba con el motivo en `ultimo_error` y se avisa, sin saltarse ninguna fecha."""
from __future__ import annotations

import json
from datetime import date

from . import auditoria, db
from . import fiscal_nucleo as fn
from .bd import contexto
from .fiscal_perfiles import ErrorFiscal

FRECUENCIAS = {"mensual": 1, "trimestral": 3}                       # meses entre repeticiones
MAX_POR_EJECUCION = 12                                              # tope de repeticiones que se ponen al día de una vez
# del apunte guardado, lo que describe el apunte modelo (no los identificadores ni la auditoría)
EXCLUIDOS = {"id", "tenant_id", "cliente_fiscal_id", "factura_id", "version", "aprobado_por", "aprobado_en", "creado_en", "actualizado_en", "anulado_en", "anulado_por", "anulado_motivo", "causa"}


def _proxima(p: dict) -> str:
    """Fecha de la siguiente repetición de una plantilla."""
    return fn._mes_despues(p["datos"]["fecha_expedicion"], (p["generadas"] + 1) * FRECUENCIAS[p["frecuencia"]])


def _fila(r) -> dict:
    p = dict(r)
    p["datos"] = json.loads(p["datos"])
    p["proxima"] = _proxima(p)
    p["terminada"] = bool(p["hasta"]) and p["proxima"] > p["hasta"]
    return p


def listar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> list[dict]:
    fn._exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        return [_fila(r) for r in conn.execute("SELECT * FROM fiscal_apuntes_recurrentes WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY activa DESC, id", (tenant_id, cliente_fiscal_id)).fetchall()]
    finally:
        conn.close()


def prevision(plantillas: list[dict], *, meses: int = 12, hoy: date | None = None) -> dict:
    """Los apuntes que las plantillas ACTIVAS crearán en los próximos `meses` meses (más los que ya tocan y aún no se han generado), por fecha, y su resumen por trimestre natural: base y cuota del libro de
    emitidas (E) y de recibidas (R), y la retención. Solo mira: no crea nada. Devuelve `{"lineas", "trimestres"}`."""
    hoy = hoy or date.today()
    limite = fn._mes_despues(hoy.isoformat(), meses)
    lineas = []
    for p in plantillas:
        if not p["activa"]:
            continue
        paso, n = FRECUENCIAS[p["frecuencia"]], p["generadas"] + 1
        fecha = fn._mes_despues(p["datos"]["fecha_expedicion"], n * paso)
        while fecha <= limite and not (p["hasta"] and fecha > p["hasta"]) and len(lineas) < 500:
            d = p["datos"]
            lineas.append({"fecha": fecha, "plantilla_id": p["id"], "nombre": p["nombre"], "libro": d.get("libro"), "base": d.get("base_centimos") or 0, "cuota": d.get("cuota_centimos") or 0,
                           "retencion": d.get("retencion_centimos") or 0, "pendiente": fecha <= hoy.isoformat()})
            n += 1
            fecha = fn._mes_despues(p["datos"]["fecha_expedicion"], n * paso)
    lineas.sort(key=lambda x: (x["fecha"], x["nombre"]))
    trimestres = {}
    for x in lineas:
        t = trimestres.setdefault(f"{x['fecha'][:4]}-T{(int(x['fecha'][5:7]) - 1) // 3 + 1}", {"emitidas": 0, "recibidas": 0, "base_e": 0, "base_r": 0, "cuota_e": 0, "cuota_r": 0, "retencion": 0, "n": 0})
        clave = "e" if x["libro"] == "E" else "r"
        t["emitidas" if clave == "e" else "recibidas"] += 1
        t["base_" + clave] += x["base"]
        t["cuota_" + clave] += x["cuota"]
        t["retencion"] += x["retencion"]
        t["n"] += 1
    return {"lineas": lineas, "trimestres": trimestres}


def crear(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, apunte_id: int, *, frecuencia: str = "mensual", hasta: str | None = None, nombre: str | None = None) -> dict:
    """Define la plantilla a partir de un apunte aprobado. Cada apunte tiene como mucho una plantilla activa. `hasta`: última fecha (AAAA-MM-DD) hasta la que se repite; en blanco, sin fin."""
    fn._exigir_aprobador(tenant_id, usuario_id)
    fn._exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    if frecuencia not in FRECUENCIAS:
        raise ErrorFiscal("La frecuencia es mensual o trimestral.")
    fila = next((f for f in fn.listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id) if f["id"] == apunte_id), None)
    if not fila:
        raise ErrorFiscal("El apunte no existe o está anulado.", "no_encontrado")
    if fila["tipo_factura"] in fn.RECTIFICATIVAS_APUNTE:
        raise ErrorFiscal("No se repite una factura rectificativa.")
    hasta = (hasta or "").strip() or None
    if hasta:
        try:
            if date.fromisoformat(hasta) <= date.fromisoformat(fila["fecha_expedicion"][:10]):
                raise ErrorFiscal("La fecha final debe ser posterior a la del apunte.")
        except ValueError:
            raise ErrorFiscal("La fecha final debe ser una fecha válida (AAAA-MM-DD).") from None
    nombre = (nombre or "").strip()[:120] or f"{fila['contraparte_nombre']} · {fila['numero']}"
    datos = {k: v for k, v in fila.items() if k not in EXCLUIDOS}
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM fiscal_apuntes_recurrentes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND apunte_id = ? AND activa = 1", (tenant_id, cliente_fiscal_id, apunte_id)).fetchone():
            raise ErrorFiscal("Este apunte ya tiene una plantilla recurrente activa.", "ya_existe")
        cur = conn.execute("INSERT INTO fiscal_apuntes_recurrentes (tenant_id, cliente_fiscal_id, nombre, apunte_id, datos, frecuencia, hasta, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                           (tenant_id, cliente_fiscal_id, nombre, apunte_id, json.dumps(datos, ensure_ascii=False, default=str), frecuencia, hasta, usuario_id, ahora))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.recurrente.crear", "cliente_fiscal", cliente_fiscal_id, {"plantilla_id": cur.lastrowid, "apunte_id": apunte_id, "frecuencia": frecuencia, "hasta": hasta}, conn=conn)
        fila_nueva = conn.execute("SELECT * FROM fiscal_apuntes_recurrentes WHERE id = ? AND tenant_id = ?", (cur.lastrowid, tenant_id)).fetchone()
        conn.commit()
        return _fila(fila_nueva)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _plantilla(conn, tenant_id: int, cliente_fiscal_id: int, plantilla_id: int):
    r = conn.execute("SELECT * FROM fiscal_apuntes_recurrentes WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (plantilla_id, tenant_id, cliente_fiscal_id)).fetchone()
    if not r:
        raise ErrorFiscal("La plantilla no existe.", "no_encontrado")
    return r


def pausar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, plantilla_id: int, activa: bool) -> dict:
    """Pausa o reanuda la plantilla. Al reanudar se limpia el último error; lo que toca se genera en la siguiente ejecución."""
    fn._exigir_aprobador(tenant_id, usuario_id)
    fn._exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        _plantilla(conn, tenant_id, cliente_fiscal_id, plantilla_id)
        conn.execute("UPDATE fiscal_apuntes_recurrentes SET activa = ?, ultimo_error = NULL, actualizado_en = ? WHERE id = ? AND tenant_id = ?", (1 if activa else 0, db.now_iso(), plantilla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.recurrente.reanudar" if activa else "fiscal.recurrente.pausar", "cliente_fiscal", cliente_fiscal_id, {"plantilla_id": plantilla_id}, conn=conn)
        fila = _plantilla(conn, tenant_id, cliente_fiscal_id, plantilla_id)
        conn.commit()
        return _fila(fila)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def borrar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, plantilla_id: int) -> None:
    """Borra la plantilla; los apuntes que ya generó se quedan."""
    fn._exigir_aprobador(tenant_id, usuario_id)
    fn._exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        _plantilla(conn, tenant_id, cliente_fiscal_id, plantilla_id)
        conn.execute("DELETE FROM fiscal_apuntes_recurrentes WHERE id = ? AND tenant_id = ?", (plantilla_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.recurrente.borrar", "cliente_fiscal", cliente_fiscal_id, {"plantilla_id": plantilla_id}, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _avisar(usuario_id: int, titulo: str, cuerpo: str, cliente_fiscal_id: int) -> None:
    try:
        db.crear_notificacion(usuario_id, "fiscal_recurrente", titulo, cuerpo, f"/guilda-fiscal/{cliente_fiscal_id}/recurrentes")
    except Exception:                                   # un aviso que falla no debe parar la generación
        pass


def _generar_una(p: dict, hoy: date) -> dict:
    """Pone al día UNA plantilla (en el despacho que ya esté fijado). Devuelve `{"creados": n, "ya_existian": n, "error": texto o None}`."""
    tenant_id, cliente, actor = p["tenant_id"], p["cliente_fiscal_id"], p["creado_por"]
    salida = {"creados": 0, "ya_existian": 0, "error": None}
    paso = FRECUENCIAS[p["frecuencia"]]
    generadas = p["generadas"]
    try:
        fn._exigir_aprobador(tenant_id, actor)
        fn._exigir_acceso(tenant_id, actor, cliente)
        existentes = None
        datos = p["datos"]
        nif = fn._nif_limpio(datos["contraparte_nif"])
        for _ in range(MAX_POR_EJECUCION):
            n = (generadas + 1) * paso
            fecha = fn._mes_despues(datos["fecha_expedicion"], n)
            if date.fromisoformat(fecha) > hoy or (p["hasta"] and fecha > p["hasta"]):
                break
            if existentes is None:
                existentes = {(f["libro"], fn._nif_limpio(f["contraparte_nif"]), f["base_centimos"], f["tipo_iva_centesimas"], f["fecha_expedicion"][:7]) for f in fn.listar_apuntes(tenant_id, actor, cliente)}
            if (datos["libro"], nif, datos["base_centimos"], datos["tipo_iva_centesimas"], fecha[:7]) in existentes:
                salida["ya_existian"] += 1
            else:
                nuevo = fn.aprobar_apunte(tenant_id, actor, cliente, fn.apunte_desplazado(tenant_id, actor, cliente, datos, n), retencion=fn.retencion_de_apunte(datos))
                existentes.add((datos["libro"], nif, datos["base_centimos"], datos["tipo_iva_centesimas"], fecha[:7]))
                salida["creados"] += 1
                auditoria.registrar(tenant_id, actor, "fiscal.recurrente.generar", "cliente_fiscal", cliente, {"plantilla_id": p["id"], "apunte_id": nuevo["id"], "fecha": fecha, "automatico": True})
            generadas += 1
    except ErrorFiscal as e:
        salida["error"] = str(e)[:300]
    if generadas != p["generadas"] or salida["error"] != p.get("ultimo_error"):
        conn = db.get_connection()
        try:
            conn.execute("UPDATE fiscal_apuntes_recurrentes SET generadas = ?, ultima_ejecucion = ?, ultimo_error = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                         (generadas, hoy.isoformat(), salida["error"], db.now_iso(), p["id"], tenant_id))
            conn.commit()
        finally:
            conn.close()
    if salida["creados"]:
        _avisar(actor, f"Apuntes recurrentes generados: {p['nombre']}", f"Se han creado {salida['creados']} apunte(s) aprobado(s) de «{p['nombre']}». Revísalos en la ficha del titular.", cliente)
    if salida["error"]:
        _avisar(actor, f"La plantilla recurrente «{p['nombre']}» no se ha podido generar", salida["error"], cliente)
    return salida


def generar(*, tenant_id: int | None = None, cliente_fiscal_id: int | None = None, hoy: date | None = None) -> dict:
    """Pone al día las plantillas activas con fechas ya llegadas: las de un titular (desde la pantalla), las de un despacho o todas (el script diario). Repetirlo el mismo día no duplica nada.
    Devuelve `{"creados": n, "ya_existian": n, "errores": n, "plantillas": n}`."""
    hoy = hoy or date.today()
    total = {"creados": 0, "ya_existian": 0, "errores": 0, "plantillas": 0}
    with contexto.como_plataforma():
        conn = db.get_connection(plataforma=True)
        try:
            sql, args = "SELECT * FROM fiscal_apuntes_recurrentes WHERE activa = 1", []
            for columna, valor in (("tenant_id", tenant_id), ("cliente_fiscal_id", cliente_fiscal_id)):
                if valor is not None:
                    sql += f" AND {columna} = ?"
                    args.append(valor)
            filas = [_fila(r) for r in conn.execute(sql + " ORDER BY tenant_id, id", args).fetchall()]
        finally:
            conn.close()
    for p in filas:
        if p["terminada"] or date.fromisoformat(p["proxima"]) > hoy:
            continue
        with contexto.en_despacho(p["tenant_id"]):
            r = _generar_una(p, hoy)
        total["plantillas"] += 1
        total["creados"] += r["creados"]
        total["ya_existian"] += r["ya_existian"]
        total["errores"] += 1 if r["error"] else 0
    return total


def generar_de_un_titular(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """«Generar lo que toca ahora» desde la pantalla del titular: lo mismo que el script diario, solo para sus plantillas."""
    fn._exigir_aprobador(tenant_id, usuario_id)
    fn._exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    return generar(tenant_id=tenant_id, cliente_fiscal_id=cliente_fiscal_id)


__all__ = ["crear", "listar", "pausar", "borrar", "generar", "generar_de_un_titular", "FRECUENCIAS", "ErrorFiscal"]
