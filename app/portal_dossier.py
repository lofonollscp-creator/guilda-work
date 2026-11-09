"""Dossier de actividad para el banco, un alquiler o una ayuda: un PDF de una hoja con lo que la actividad del cliente ha movido en un periodo (ventas, gastos, IVA por trimestre y modelos presentados), hecho solo con las
facturas que su gestoría ya ha revisado y que el cliente puede generar cuando quiera.

Nace **sin validar** (un resumen informativo). El cliente puede pedir que su gestoría lo **valide**: una persona del equipo lo revisa y, con un clic, queda validado con un código y una huella de lo que dice. Cualquiera puede
comprobar un código en una página pública que enseña los mismos totales: si no coinciden con los del papel, el papel no es auténtico. El PDF se rehace siempre desde la copia de datos guardada al generarlo, así que lo
validado no cambia aunque luego se revisen más facturas."""
from __future__ import annotations

import hashlib
import io
import json
import secrets
from datetime import date, datetime

from flask_babel import gettext as _
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import db, facturas_contables as fc
from .fiscal_resumen_pdf import _e, _eur

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_dossiers (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    desde TEXT NOT NULL,
    hasta TEXT NOT NULL,
    creado_por TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL,
    datos TEXT NOT NULL,
    huella TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'sin_validar' CHECK (estado IN ('sin_validar', 'pendiente', 'validado', 'rechazado')),
    pedido_en TEXT,
    validado_por INTEGER,
    validado_en TEXT,
    codigo TEXT,
    nota TEXT NOT NULL DEFAULT '',
    UNIQUE (tenant_id, codigo)
);
CREATE INDEX IF NOT EXISTS idx_portal_dossiers_cliente ON portal_dossiers(tenant_id, cliente_fiscal_id, creado_en);
CREATE INDEX IF NOT EXISTS idx_portal_dossiers_codigo ON portal_dossiers(codigo);
"""
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # sin caracteres que se confunden (0/O, 1/I)
MAX_DIAS = 366 * 2


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def periodo(clave: str, hoy: date | None = None) -> tuple[str, str]:
    """(desde, hasta) de un periodo con nombre: «ultimo_anio» (12 meses hasta hoy), «anio_en_curso», «ultimo_trimestre» (el último trimestre natural cerrado) o «anio_anterior»."""
    hoy = hoy or date.today()
    if clave == "anio_en_curso":
        return f"{hoy.year}-01-01", hoy.isoformat()
    if clave == "anio_anterior":
        return f"{hoy.year - 1}-01-01", f"{hoy.year - 1}-12-31"
    if clave == "ultimo_trimestre":
        t = (hoy.month - 1) // 3
        anio, t = (hoy.year, t) if t else (hoy.year - 1, 4)
        ini = (anio, 3 * (t - 1) + 1)
        fin = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[t]
        return f"{ini[0]}-{ini[1]:02d}-01", f"{anio}-{fin}"
    if clave == "ultimo_anio":
        try:
            return hoy.replace(year=hoy.year - 1).isoformat(), hoy.isoformat()
        except ValueError:                                 # 29 de febrero
            return hoy.replace(year=hoy.year - 1, day=28).isoformat(), hoy.isoformat()
    raise ValueError("Elige un periodo.")


def calcular(cliente, desde: str, hasta: str) -> dict:
    """Los números del periodo, por trimestre natural: ventas y gastos (base), IVA repercutido y soportado y el resultado del IVA, solo de facturas revisadas o contabilizadas (los abonos restan)."""
    d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
    if d1 < d0 or (d1 - d0).days > MAX_DIAS:
        raise ValueError("El periodo no es válido (máximo dos años).")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT f.id, f.tipo, f.fecha, f.abono, COALESCE(SUM(l.base_centimos), 0) AS base, COALESCE(SUM(l.cuota_iva), 0) AS iva FROM facturas_contables f "
                             "LEFT JOIN facturas_contables_lineas l ON l.factura_id = f.id WHERE f.tenant_id = ? AND f.cliente_fiscal_id = ? AND f.estado IN ('revisada', 'exportada') AND f.fecha >= ? AND f.fecha <= ? "
                             "GROUP BY f.id, f.tipo, f.fecha, f.abono", (cliente["tenant_id"], cliente["id"], desde, hasta)).fetchall()
        modelos = conn.execute("SELECT modelo, periodo FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'presentado' AND papelera_en IS NULL AND fecha_limite >= ? AND fecha_limite <= ? ORDER BY fecha_limite",
                               (cliente["tenant_id"], cliente["id"], desde, hasta)).fetchall()
    finally:
        conn.close()
    trimestres: dict[str, dict] = {}
    for f in filas:
        t = fc.trimestre_de(f["fecha"])
        d = trimestres.setdefault(t, {"trimestre": t, "ventas": 0, "gastos": 0, "iva_repercutido": 0, "iva_soportado": 0, "facturas": 0})
        signo = -1 if f["abono"] else 1
        d["facturas"] += 1
        if f["tipo"] == "emitida":
            d["ventas"] += signo * f["base"]
            d["iva_repercutido"] += signo * f["iva"]
        else:
            d["gastos"] += signo * f["base"]
            d["iva_soportado"] += signo * f["iva"]
    filas_t = [trimestres[k] for k in sorted(trimestres)]
    total = {c: sum(t[c] for t in filas_t) for c in ("ventas", "gastos", "iva_repercutido", "iva_soportado", "facturas")}
    total["resultado_iva"] = total["iva_repercutido"] - total["iva_soportado"]
    return {"desde": desde, "hasta": hasta, "trimestres": filas_t, "total": total, "modelos": [{"modelo": m["modelo"], "periodo": m["periodo"]} for m in modelos]}


def _huella(datos: dict) -> str:
    return hashlib.sha256(json.dumps(datos, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def crear(cliente, desde: str, hasta: str, quien: str) -> int:
    """Genera el dossier de ese periodo con los números de ahora y lo guarda (sin validar). `ValueError` si el periodo no vale o no hay nada que contar."""
    datos = calcular(cliente, desde, hasta)
    if not datos["total"]["facturas"] and not datos["modelos"]:
        raise ValueError("Todavía no hay facturas revisadas ni modelos presentados en ese periodo.")
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO portal_dossiers (tenant_id, cliente_fiscal_id, desde, hasta, creado_por, creado_en, datos, huella) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], desde, hasta, (quien or "")[:120], _ahora(), json.dumps(datos, ensure_ascii=False), _huella(datos)))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _fila(f) -> dict:
    d = dict(f)
    d["datos"] = json.loads(d["datos"])
    return d


def listar(cliente) -> list[dict]:
    conn = db.get_connection()
    try:
        return [_fila(f) for f in conn.execute("SELECT * FROM portal_dossiers WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY id DESC LIMIT 50", (cliente["tenant_id"], cliente["id"])).fetchall()]
    finally:
        conn.close()


def obtener(cliente, dossier_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM portal_dossiers WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (dossier_id, cliente["tenant_id"], cliente["id"])).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def pedir_validacion(cliente, dossier_id: int) -> bool:
    """El cliente pide a su gestoría que lo valide. False si no existe o ya no está sin validar."""
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_dossiers SET estado = 'pendiente', pedido_en = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('sin_validar', 'rechazado')", (_ahora(), dossier_id, cliente["tenant_id"], cliente["id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def pendientes(tenant_id: int) -> list[dict]:
    """Los dossiers que esperan validación en este despacho, con el nombre del cliente."""
    conn = db.get_connection()
    try:
        return [_fila(f) for f in conn.execute("SELECT d.*, c.nombre AS cliente_nombre FROM portal_dossiers d JOIN clientes_fiscales c ON c.id = d.cliente_fiscal_id WHERE d.tenant_id = ? AND d.estado = 'pendiente' ORDER BY d.pedido_en", (tenant_id,)).fetchall()]
    finally:
        conn.close()


def obtener_del_despacho(tenant_id: int, dossier_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT d.*, c.nombre AS cliente_nombre, c.nif AS cliente_nif FROM portal_dossiers d JOIN clientes_fiscales c ON c.id = d.cliente_fiscal_id WHERE d.id = ? AND d.tenant_id = ?", (dossier_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def resolver(tenant_id: int, dossier_id: int, usuario_id: int, validar: bool, nota: str = "") -> str | None:
    """La gestoría valida (devuelve el código) o rechaza (devuelve None) un dossier pendiente. `ValueError` si ya no está pendiente."""
    d = obtener_del_despacho(tenant_id, dossier_id)
    if d is None or d["estado"] != "pendiente":
        raise ValueError("Este dossier ya no está pendiente de validar.")
    codigo = "".join(secrets.choice(ALFABETO) for _i in range(10)) if validar else None
    conn = db.get_connection()
    try:
        conn.execute("UPDATE portal_dossiers SET estado = ?, validado_por = ?, validado_en = ?, codigo = ?, nota = ? WHERE id = ? AND tenant_id = ?",
                     ("validado" if validar else "rechazado", usuario_id, _ahora(), codigo, " ".join((nota or "").split())[:300], dossier_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    return codigo


def verificar(codigo: str) -> dict | None:
    """Lo que enseña la página pública de comprobación de un código, o None si no existe. Sin datos personales más allá de lo que lleva el propio papel."""
    codigo = (codigo or "").strip().upper()
    if not codigo or len(codigo) > 20:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT d.*, c.nombre AS cliente_nombre, c.nif AS cliente_nif FROM portal_dossiers d JOIN clientes_fiscales c ON c.id = d.cliente_fiscal_id WHERE d.codigo = ? AND d.estado = 'validado'", (codigo,)).fetchall()
    finally:
        conn.close()
    for fila in f:
        d = _fila(fila)
        if _huella(d["datos"]) == d["huella"]:               # los datos guardados siguen siendo los que se validaron
            despacho = db.obtener_tenant(d["tenant_id"])
            d["despacho"] = despacho["nombre"] if despacho else ""
            return d
    return None


def pdf(d: dict, cliente_nombre: str, cliente_nif: str, despacho: str, url_verificacion: str | None = None) -> bytes:
    """El PDF del dossier a partir de los datos guardados (nunca de los de hoy)."""
    datos = d["datos"]
    estilos = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm, title=_("Resumen de actividad"))

    def tabla(cabecera, filas, anchos):
        t = Table([[Paragraph(f"<b>{_e(c)}</b>", estilos["Normal"]) for c in cabecera]] + [[Paragraph(_e(c), estilos["Normal"]) for c in f] for f in filas], colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f1ec")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t
    c = [Paragraph(_e(despacho), estilos["Heading3"]), Paragraph(_("Resumen de actividad"), estilos["Title"]),
         Paragraph(f"<b>{_e(cliente_nombre)}</b> · {_e(cliente_nif)}", estilos["Normal"]),
         Paragraph(_e(_("Periodo: del %(a)s al %(b)s", a=datos["desde"], b=datos["hasta"])), estilos["Normal"]), Spacer(1, 0.5 * cm)]
    if datos["trimestres"]:
        filas = [[t["trimestre"], _eur(t["ventas"]), _eur(t["gastos"]), _eur(t["iva_repercutido"]), _eur(t["iva_soportado"]), str(t["facturas"])] for t in datos["trimestres"]]
        t = datos["total"]
        filas.append([_("Total"), _eur(t["ventas"]), _eur(t["gastos"]), _eur(t["iva_repercutido"]), _eur(t["iva_soportado"]), str(t["facturas"])])
        c += [tabla([_("Trimestre"), _("Ventas (base)"), _("Gastos (base)"), _("IVA repercutido"), _("IVA soportado"), _("Facturas")], filas, [2.6 * cm, 3.1 * cm, 3.1 * cm, 3 * cm, 3 * cm, 2 * cm]),
              Spacer(1, 0.3 * cm), Paragraph(_e(_("Resultado del IVA del periodo (repercutido menos soportado): %(r)s", r=_eur(t["resultado_iva"]))), estilos["Normal"])]
    if datos["modelos"]:
        c += [Spacer(1, 0.4 * cm), Paragraph(_e(_("Modelos presentados en el periodo")), estilos["Heading4"]), tabla([_("Modelo"), _("Periodo")], [[m["modelo"], m["periodo"]] for m in datos["modelos"]], [5 * cm, 6 * cm])]
    c += [Spacer(1, 0.6 * cm), Paragraph(_e(_("Hecho con las facturas revisadas por su gestoría. Es un resumen informativo: no sustituye a las declaraciones presentadas ni a los justificantes oficiales.")), estilos["Italic"])]
    if d["estado"] == "validado":
        c += [Spacer(1, 0.4 * cm), Paragraph(f"<b>{_e(_('Validado por %(d)s el %(f)s', d=despacho, f=(d['validado_en'] or '')[:10]))}</b>", estilos["Normal"]),
              Paragraph(_e(_("Código de verificación: %(c)s", c=d["codigo"])), estilos["Normal"])]
        if url_verificacion:
            c.append(Paragraph(_e(_("Compruébalo en: %(u)s", u=url_verificacion)), estilos["Normal"]))
    else:
        c += [Spacer(1, 0.4 * cm), Paragraph(f"<b>{_e(_('Documento sin validar por la gestoría.'))}</b>", estilos["Normal"])]
    doc.build(c)
    return buf.getvalue()
