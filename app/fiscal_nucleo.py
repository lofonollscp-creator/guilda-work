"""Guilda Fiscal · núcleo (F4): apuntes aprobados, instantáneas inmutables, declaraciones del 303, casillas y ficheros generados (docs/fiscal-f4-esquema-propuesto.md).

El flujo, siempre con una persona que decide:
  factura (facturas_contables) ─▶ propuesta de apunte ─▶ **apunte aprobado** (revisor fiscal o dirección) ─▶ **instantánea** inmutable del periodo ─▶ declaración (borrador) calculada SOLO sobre la
  instantánea ─▶ revisada ─▶ exportada (fichero `.303` + libro + resumen) ─▶ presentada (la presentación la hace el cliente o su colaborador social; aquí solo se anota).

Reglas: la IA y la API de lectura nunca aprueban; lo exportado o presentado no se modifica (lo impone la base con triggers, no solo este código); una instantánea nueva SUSTITUYE a la anterior sin borrarla;
recalcular desde la misma instantánea da las mismas casillas. El cálculo es `fiscal_modelos.motor_303` (función pura, contrastada con la AEAT)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta

from flask_babel import lazy_gettext as _l  # noqa: F401  (los textos de pantalla se traducen en las rutas)

from . import acceso, auditoria, db, fiscal_perfiles
from .fiscal_modelos import exportador_303, fichero_303, fichero_390, fichero_retenciones, iban as iban_mod, libros_lsi, motor_130, motor_303, motor_390, motor_retenciones, validacion_apuntes
from .fiscal_modelos.apuntes import RECTIFICATIVAS as RECTIFICATIVAS_APUNTE, Apunte
motor_303_RECTIFICATIVAS = RECTIFICATIVAS_APUNTE
from .fiscal_perfiles import ErrorFiscal

VERSION_MOTOR = "1"
VERSION_DISENO = "DR303e26v101"
ESTADOS = ("borrador", "revisada", "exportada", "presentada", "anulada")
TRANSICIONES = {"borrador": ("revisada", "anulada"), "revisada": ("exportada", "anulada"), "exportada": ("presentada", "anulada"), "presentada": (), "anulada": ()}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fiscal_apuntes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    factura_id INTEGER REFERENCES facturas_contables(id) ON DELETE SET NULL,
    libro TEXT NOT NULL CHECK (libro IN ('E','R')),
    tipo_factura TEXT NOT NULL,
    clave TEXT NOT NULL DEFAULT '01',
    calificacion TEXT NOT NULL DEFAULT 'S1',
    exenta TEXT NOT NULL DEFAULT '',
    serie TEXT NOT NULL DEFAULT '',
    numero TEXT NOT NULL,
    fecha_expedicion TEXT NOT NULL,
    fecha_operacion TEXT,
    fecha_recepcion TEXT,
    base_centimos INTEGER NOT NULL,
    tipo_iva_centesimas INTEGER NOT NULL DEFAULT 0,
    cuota_centimos INTEGER NOT NULL DEFAULT 0,
    total_centimos INTEGER,
    cuota_deducible_centimos INTEGER,
    isp INTEGER NOT NULL DEFAULT 0,
    bien_inversion INTEGER NOT NULL DEFAULT 0,
    deducible_periodo_posterior INTEGER NOT NULL DEFAULT 0,
    periodo_deduccion TEXT,
    inmueble_situacion TEXT NOT NULL DEFAULT '',
    inmueble_referencia TEXT NOT NULL DEFAULT '',
    recargo_pct_centesimas INTEGER NOT NULL DEFAULT 0,
    recargo_cuota_centimos INTEGER NOT NULL DEFAULT 0,
    cobros_json TEXT,
    contraparte_nombre TEXT NOT NULL,
    contraparte_nif TEXT,
    contraparte_nif_tipo TEXT NOT NULL DEFAULT '',
    contraparte_pais TEXT NOT NULL DEFAULT '',
    retencion_modelo TEXT NOT NULL DEFAULT '',
    retencion_clave TEXT NOT NULL DEFAULT '',
    retencion_base_centimos INTEGER,
    retencion_pct_centesimas INTEGER,
    retencion_centimos INTEGER,
    causa TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    aprobado_por INTEGER NOT NULL REFERENCES usuarios(id),
    aprobado_en TEXT NOT NULL,
    anulado_en TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_fiscal_apuntes_periodo ON fiscal_apuntes(tenant_id, cliente_fiscal_id, libro, fecha_expedicion);
CREATE INDEX IF NOT EXISTS idx_fiscal_apuntes_factura ON fiscal_apuntes(tenant_id, factura_id);

CREATE TABLE IF NOT EXISTS fiscal_instantaneas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    modelo TEXT NOT NULL,
    ejercicio INTEGER NOT NULL,
    periodo TEXT NOT NULL,
    hash TEXT NOT NULL,
    contenido TEXT NOT NULL,
    aprobada_por INTEGER NOT NULL REFERENCES usuarios(id),
    aprobada_en TEXT NOT NULL,
    sustituye_a_id INTEGER REFERENCES fiscal_instantaneas(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fiscal_instantaneas ON fiscal_instantaneas(tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo);

CREATE TABLE IF NOT EXISTS fiscal_declaraciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    instantanea_id INTEGER NOT NULL REFERENCES fiscal_instantaneas(id),
    vencimiento_id INTEGER REFERENCES vencimientos_fiscales(id) ON DELETE SET NULL,
    modelo TEXT NOT NULL,
    ejercicio INTEGER NOT NULL,
    periodo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','revisada','exportada','presentada','anulada')),
    tipo_declaracion TEXT NOT NULL DEFAULT 'N',
    resultado_centimos INTEGER NOT NULL DEFAULT 0,
    version_motor TEXT NOT NULL,
    version_diseno TEXT NOT NULL,
    rectifica_a_id INTEGER REFERENCES fiscal_declaraciones(id),
    justificante_anterior TEXT,
    iban TEXT,
    bloqueos TEXT,
    revisada_por INTEGER REFERENCES usuarios(id),
    revisada_en TEXT,
    exportada_en TEXT,
    presentada_en TEXT,
    referencia_presentacion TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fiscal_declaraciones ON fiscal_declaraciones(tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo);

CREATE TABLE IF NOT EXISTS fiscal_casillas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    declaracion_id INTEGER NOT NULL REFERENCES fiscal_declaraciones(id) ON DELETE CASCADE,
    casilla TEXT NOT NULL,
    valor INTEGER NOT NULL,
    origen TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_casillas ON fiscal_casillas(tenant_id, declaracion_id, casilla);

CREATE TABLE IF NOT EXISTS fiscal_artefactos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    declaracion_id INTEGER NOT NULL REFERENCES fiscal_declaraciones(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('303','libro_xlsx','resumen')),
    hash TEXT NOT NULL,
    contenido BLOB NOT NULL,
    informe_validacion TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fiscal_artefactos ON fiscal_artefactos(tenant_id, declaracion_id, tipo);

CREATE TRIGGER IF NOT EXISTS fiscal_instantaneas_sin_modificar BEFORE UPDATE ON fiscal_instantaneas
BEGIN SELECT RAISE(ABORT, 'Una instantánea fiscal es inmutable: no se puede modificar.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_instantaneas_sin_borrar BEFORE DELETE ON fiscal_instantaneas
WHEN COALESCE((SELECT valor FROM auditoria_control WHERE clave = 'permitir_borrado'), '0') != '1'
BEGIN SELECT RAISE(ABORT, 'Una instantánea fiscal es inmutable: no se puede borrar.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_artefactos_sin_modificar BEFORE UPDATE ON fiscal_artefactos
BEGIN SELECT RAISE(ABORT, 'Un fichero fiscal generado es inmutable: no se puede modificar.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_artefactos_sin_borrar BEFORE DELETE ON fiscal_artefactos
WHEN COALESCE((SELECT valor FROM auditoria_control WHERE clave = 'permitir_borrado'), '0') != '1'
BEGIN SELECT RAISE(ABORT, 'Un fichero fiscal generado es inmutable: no se puede borrar.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_casillas_solo_borrador_u BEFORE UPDATE ON fiscal_casillas
WHEN (SELECT estado FROM fiscal_declaraciones WHERE id = OLD.declaracion_id) NOT IN ('borrador')
BEGIN SELECT RAISE(ABORT, 'Las casillas de una declaración ya revisada, exportada o presentada no se modifican.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_casillas_solo_borrador_d BEFORE DELETE ON fiscal_casillas
WHEN (SELECT estado FROM fiscal_declaraciones WHERE id = OLD.declaracion_id) NOT IN ('borrador', 'anulada')
 AND COALESCE((SELECT valor FROM auditoria_control WHERE clave = 'permitir_borrado'), '0') != '1'
BEGIN SELECT RAISE(ABORT, 'Las casillas de una declaración ya revisada, exportada o presentada no se borran.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_declaraciones_estados BEFORE UPDATE ON fiscal_declaraciones
WHEN NEW.estado != OLD.estado AND NOT (
    (OLD.estado = 'borrador' AND NEW.estado IN ('revisada', 'anulada')) OR (OLD.estado = 'revisada' AND NEW.estado IN ('exportada', 'anulada')) OR (OLD.estado = 'exportada' AND NEW.estado IN ('presentada', 'anulada')))
BEGIN SELECT RAISE(ABORT, 'Transición de estado no permitida en la declaración fiscal.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_declaraciones_congeladas BEFORE UPDATE ON fiscal_declaraciones
WHEN OLD.estado IN ('exportada', 'presentada') AND (NEW.instantanea_id != OLD.instantanea_id OR NEW.resultado_centimos != OLD.resultado_centimos OR NEW.tipo_declaracion != OLD.tipo_declaracion
     OR NEW.modelo != OLD.modelo OR NEW.ejercicio != OLD.ejercicio OR NEW.periodo != OLD.periodo OR NEW.version_motor != OLD.version_motor OR NEW.version_diseno != OLD.version_diseno)
BEGIN SELECT RAISE(ABORT, 'Una declaración exportada o presentada no se modifica: se abre una rectificación.'); END;
CREATE TRIGGER IF NOT EXISTS fiscal_declaraciones_sin_borrar BEFORE DELETE ON fiscal_declaraciones
WHEN OLD.estado IN ('revisada', 'exportada', 'presentada') AND COALESCE((SELECT valor FROM auditoria_control WHERE clave = 'permitir_borrado'), '0') != '1'
BEGIN SELECT RAISE(ABORT, 'Una declaración revisada, exportada o presentada no se borra.'); END;
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    for columna, tipo in (("retencion_modelo", "TEXT NOT NULL DEFAULT ''"), ("retencion_clave", "TEXT NOT NULL DEFAULT ''"), ("retencion_base_centimos", "INTEGER"),
                          ("retencion_pct_centesimas", "INTEGER"), ("retencion_centimos", "INTEGER")):
        db._asegurar_columna(conn, "fiscal_apuntes", columna, tipo)          # bases anteriores a la migración 005
    for columna in ("recargo_pct_centesimas", "recargo_cuota_centimos"):
        db._asegurar_columna(conn, "fiscal_apuntes", columna, "INTEGER NOT NULL DEFAULT 0")                  # bases anteriores a la migración 007
    db._asegurar_columna(conn, "fiscal_apuntes", "cobros_json", "TEXT")                                       # bases anteriores a la migración 009
    db._asegurar_columna(conn, "fiscal_declaraciones", "justificante_anterior", "TEXT")      # bases anteriores a la migración 006
    db._asegurar_columna(conn, "fiscal_declaraciones", "iban", "TEXT")                       # bases anteriores a la migración 010


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    """Al borrar un despacho por completo: lo inmutable solo se puede borrar con el permiso que existe durante esa transacción (el mismo de la auditoría)."""
    conn.execute("INSERT INTO auditoria_control (clave, valor) VALUES ('permitir_borrado', '1') ON CONFLICT(clave) DO UPDATE SET valor = '1'")
    try:
        for tabla in ("fiscal_artefactos", "fiscal_casillas", "fiscal_declaraciones", "fiscal_instantaneas", "fiscal_apuntes"):
            conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))
    finally:
        conn.execute("UPDATE auditoria_control SET valor = '0' WHERE clave = 'permitir_borrado'")


# --- Permisos -----------------------------------------------------------------------------------------------------------------------------------
def _exigir_aprobador(tenant_id: int, usuario_id: int) -> None:
    """Aprueban apuntes e instantáneas el revisor fiscal y la dirección del despacho (decisión F-D3). Nadie más: ni la IA ni las integraciones."""
    if not usuario_id or not acceso.puede_autorizar(tenant_id, usuario_id):
        raise ErrorFiscal("Solo el revisor fiscal o la dirección del despacho pueden aprobar.", "prohibido")


def _exigir_acceso(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> None:
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ErrorFiscal("No tienes acceso a este titular.", "prohibido")


def _titular(conn, tenant_id: int, cliente_fiscal_id: int):
    f = conn.execute("SELECT id, nombre, nif FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone()
    if not f:
        raise ErrorFiscal("El titular no existe en este despacho.", "no_encontrado")
    return f


# --- Apuntes ------------------------------------------------------------------------------------------------------------------------------------
CAMPOS_APUNTE = ("libro", "tipo_factura", "clave", "calificacion", "exenta", "serie", "numero", "fecha_expedicion", "fecha_operacion", "fecha_recepcion", "base_centimos", "tipo_iva_centesimas",
                 "cuota_centimos", "total_centimos", "cuota_deducible_centimos", "isp", "bien_inversion", "deducible_periodo_posterior", "periodo_deduccion", "inmueble_situacion",
                 "inmueble_referencia", "recargo_pct_centesimas", "recargo_cuota_centimos", "cobros_json", "contraparte_nombre", "contraparte_nif", "contraparte_nif_tipo", "contraparte_pais", "causa")
CAMPOS_RETENCION = ("retencion_modelo", "retencion_clave", "retencion_base_centimos", "retencion_pct_centesimas", "retencion_centimos")
CAMPOS_GUARDADOS = CAMPOS_APUNTE + CAMPOS_RETENCION
CLAVES_RETENCION_111 = ("G", "A")            # G: actividades profesionales · A: rendimientos del trabajo (claves de percepción del 190)
SIN_RETENCION = {"retencion_modelo": "", "retencion_clave": "", "retencion_base_centimos": None, "retencion_pct_centesimas": None, "retencion_centimos": None}


def normalizar_retencion(apunte: Apunte, retencion: dict | None) -> dict:
    """Las columnas de retención del apunte. `retencion`: `{"modelo": "111"|"115", "clave": "G"|"A", "base": céntimos, "pct": centésimas, "importe": céntimos | None (= base × %)}`.
    Solo las facturas recibidas la llevan (la practica el cliente); una emitida con retención la soporta él y no va en el 111. Base e importe llevan el signo del apunte (un abono resta)."""
    if not retencion or not retencion.get("modelo"):
        return dict(SIN_RETENCION)
    modelo = str(retencion["modelo"])
    if modelo not in ("111", "115"):
        raise ErrorFiscal("La retención solo puede ir en el modelo 111 o en el 115.")
    if apunte.libro != "R":
        raise ErrorFiscal("La retención la practica quien recibe la factura: solo va en facturas recibidas.")
    base, pct = retencion.get("base"), retencion.get("pct")
    if base is None or pct is None or not (0 < pct <= 10000):
        raise ErrorFiscal("Indica la base y el porcentaje de la retención (entre 0 y 100 %).")
    esperado = (1 if base >= 0 else -1) * ((abs(base) * pct + 5000) // 10000)
    importe = esperado if retencion.get("importe") is None else retencion["importe"]
    if (importe < 0) != (base < 0) and importe != 0:
        raise ErrorFiscal("La retención y su base deben tener el mismo signo.")
    if abs(importe - esperado) > 1:
        raise ErrorFiscal(f"La retención no cuadra: {pct / 100:g} % de la base son {esperado / 100:.2f} €.".replace(".", ","))
    clave = (retencion.get("clave") or "").upper()
    if modelo == "111":
        clave = clave or "G"
        if clave not in CLAVES_RETENCION_111:
            raise ErrorFiscal("Clave de percepción no válida para el modelo 111.")
    else:
        clave = ""
    return {"retencion_modelo": modelo, "retencion_clave": clave, "retencion_base_centimos": base, "retencion_pct_centesimas": pct, "retencion_centimos": importe}


def cobros_a_json(cobros) -> str | None:
    """Los cobros (o pagos) de un apunte con criterio de caja como texto para guardar: `[["2026-05-20", 60500], …]`, o None si no hay."""
    return json.dumps([[d.isoformat(), int(importe)] for d, importe in cobros]) if cobros else None


def cobros_de_json(texto) -> tuple:
    if not texto:
        return ()
    try:
        return tuple(sorted((date.fromisoformat(d), int(importe)) for d, importe in json.loads(texto)))
    except (ValueError, TypeError):
        return ()


def a_apunte(f) -> Apunte:
    """La fila (o el diccionario) como `Apunte` del motor."""
    d = dict(f)
    fecha = lambda x: date.fromisoformat(x) if x else None          # noqa: E731
    ded = None
    if d.get("periodo_deduccion"):
        ej, per = d["periodo_deduccion"].split("-")
        ded = (int(ej), per)
    return Apunte(libro=d["libro"], tipo_factura=d["tipo_factura"], fecha_expedicion=date.fromisoformat(d["fecha_expedicion"]), numero=d["numero"], serie=d.get("serie") or "", clave=d.get("clave") or "01",
                  base=d["base_centimos"], tipo_iva=d.get("tipo_iva_centesimas") or 0, cuota=d.get("cuota_centimos") or 0, total=d.get("total_centimos"), fecha_operacion=fecha(d.get("fecha_operacion")),
                  contraparte_nombre=d["contraparte_nombre"], contraparte_nif=d.get("contraparte_nif") or "", contraparte_nif_tipo=d.get("contraparte_nif_tipo") or "",
                  contraparte_pais=d.get("contraparte_pais") or "", calificacion=d.get("calificacion") or "", exenta=d.get("exenta") or "", fecha_recepcion=fecha(d.get("fecha_recepcion")),
                  isp=bool(d.get("isp")), bien_inversion=bool(d.get("bien_inversion")), cuota_deducible=d.get("cuota_deducible_centimos"),
                  deducible_periodo_posterior=bool(d.get("deducible_periodo_posterior")), periodo_deduccion=ded, inmueble_situacion=d.get("inmueble_situacion") or "",
                  inmueble_referencia=d.get("inmueble_referencia") or "", recargo_pct=d.get("recargo_pct_centesimas") or 0, recargo_cuota=d.get("recargo_cuota_centimos") or 0, cobros=cobros_de_json(d.get("cobros_json")))


def _datos_de_apunte(a: Apunte) -> dict:
    return {"libro": a.libro, "tipo_factura": a.tipo_factura, "clave": a.clave, "calificacion": a.calificacion, "exenta": a.exenta, "serie": a.serie, "numero": a.numero,
            "fecha_expedicion": a.fecha_expedicion.isoformat(), "fecha_operacion": a.fecha_operacion.isoformat() if a.fecha_operacion else None,
            "fecha_recepcion": a.fecha_recepcion.isoformat() if a.fecha_recepcion else None, "base_centimos": a.base, "tipo_iva_centesimas": a.tipo_iva, "cuota_centimos": a.cuota,
            "total_centimos": a.total, "cuota_deducible_centimos": a.cuota_deducible, "isp": int(a.isp), "bien_inversion": int(a.bien_inversion),
            "deducible_periodo_posterior": int(a.deducible_periodo_posterior), "periodo_deduccion": f"{a.periodo_deduccion[0]}-{a.periodo_deduccion[1]}" if a.periodo_deduccion else None,
            "inmueble_situacion": a.inmueble_situacion, "inmueble_referencia": a.inmueble_referencia, "recargo_pct_centesimas": a.recargo_pct, "recargo_cuota_centimos": a.recargo_cuota, "cobros_json": cobros_a_json(a.cobros),
            "contraparte_nombre": a.contraparte_nombre, "contraparte_nif": a.contraparte_nif or None,
            "contraparte_nif_tipo": a.contraparte_nif_tipo, "contraparte_pais": a.contraparte_pais}


def aprobar_apunte(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, apunte: Apunte, *, factura_id: int | None = None, causa: str | None = None, apunte_id: int | None = None,
                   version: int | None = None, retencion: dict | None = None) -> dict:
    """Aprueba (alta) o corrige (con `apunte_id` y la `version` leída) un apunte. Se valida con las reglas de la AEAT: un apunte con ERRORES no se aprueba.
    `retencion` (ver `normalizar_retencion`) es la retención de IRPF que el cliente practica en esa factura recibida; al corregir, si no se pasa, el apunte queda sin retención."""
    _exigir_aprobador(tenant_id, usuario_id)
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        titular = _titular(conn, tenant_id, cliente_fiscal_id)
        errores = validacion_apuntes.errores(validacion_apuntes.validar_apunte(apunte, hoy=date.today(), nif_titular=titular["nif"] or ""))
        if errores:
            raise ErrorFiscal("El apunte tiene errores: " + " · ".join(e.mensaje for e in errores), "datos_con_errores", errores=[e.mensaje for e in errores])
        if factura_id is not None and not conn.execute("SELECT 1 FROM facturas_contables WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (factura_id, tenant_id, cliente_fiscal_id)).fetchone():
            raise ErrorFiscal("La factura no es de este titular.", "no_encontrado")
        d = _datos_de_apunte(apunte)
        d.update(normalizar_retencion(apunte, retencion))
        d["causa"] = (causa or "").strip() or None
        ahora = db.now_iso()
        if apunte_id is None:
            cols = ("tenant_id", "cliente_fiscal_id", "factura_id", *CAMPOS_GUARDADOS, "aprobado_por", "aprobado_en", "creado_en")
            cur = conn.execute(f"INSERT INTO fiscal_apuntes ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               (tenant_id, cliente_fiscal_id, factura_id, *(d[c] for c in CAMPOS_GUARDADOS), usuario_id, ahora, ahora))
            apunte_id, accion = cur.lastrowid, "fiscal.apunte.aprobar"
        else:
            actual = conn.execute("SELECT * FROM fiscal_apuntes WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (apunte_id, tenant_id, cliente_fiscal_id)).fetchone()
            if not actual:
                raise ErrorFiscal("El apunte no existe.", "no_encontrado")
            if actual["anulado_en"]:
                raise ErrorFiscal("El apunte está anulado.", "invalido")
            if version is None or int(version) != actual["version"]:
                raise ErrorFiscal("Alguien ha cambiado este apunte mientras lo editabas.", "version_obsoleta", version_actual=actual["version"])
            sets = ", ".join(f"{c} = ?" for c in CAMPOS_GUARDADOS)
            conn.execute(f"UPDATE fiscal_apuntes SET {sets}, version = version + 1, aprobado_por = ?, aprobado_en = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ? AND version = ?",
                         (*(d[c] for c in CAMPOS_GUARDADOS), usuario_id, ahora, ahora, apunte_id, tenant_id, actual["version"]))
            accion = "fiscal.apunte.corregir"
            cambios = {c: [str(actual[c] if actual[c] is not None else "")[:40], str(d[c] if d[c] is not None else "")[:40]] for c in CAMPOS_GUARDADOS
                       if c != "causa" and (actual[c] if actual[c] is not None else "") != (d[c] if d[c] is not None else "")}
        detalle = {"apunte_id": apunte_id, "numero": apunte.numero, "libro": apunte.libro}
        if accion == "fiscal.apunte.corregir":
            detalle["cambios"] = dict(list(cambios.items())[:12])
            if d["causa"]:
                detalle["causa"] = d["causa"][:200]
        auditoria.registrar(tenant_id, usuario_id, accion, "cliente_fiscal", cliente_fiscal_id, detalle, conn=conn)
        fila = conn.execute("SELECT * FROM fiscal_apuntes WHERE id = ? AND tenant_id = ?", (apunte_id, tenant_id)).fetchone()
        conn.commit()
        return dict(fila)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def anular_apunte(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, apunte_id: int, motivo: str) -> None:
    _exigir_aprobador(tenant_id, usuario_id)
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    if not (motivo or "").strip():
        raise ErrorFiscal("Indica el motivo de la anulación.")
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE fiscal_apuntes SET anulado_en = ?, version = version + 1, actualizado_en = ?, causa = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND anulado_en IS NULL",
                         (db.now_iso(), db.now_iso(), motivo.strip()[:300], apunte_id, tenant_id, cliente_fiscal_id)).rowcount
        if not n:
            raise ErrorFiscal("El apunte no existe o ya está anulado.", "no_encontrado")
        auditoria.registrar(tenant_id, usuario_id, "fiscal.apunte.anular", "cliente_fiscal", cliente_fiscal_id, {"apunte_id": apunte_id, "motivo": motivo.strip()[:300]}, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _nif_limpio(nif) -> str:
    return "".join(ch for ch in str(nif or "").upper() if ch.isalnum())


def buscar_contraparte(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, nif: str, libro: str | None = None) -> dict | None:
    """Los datos de una contraparte que este titular ya usó (apuntes anteriores, terceros de contabilidad, facturas anotadas), para no teclearlos otra vez. Solo lee; None si no la conoce."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    limpio = _nif_limpio(nif)
    if len(limpio) < 5:
        return None
    norma = "UPPER(REPLACE(REPLACE(REPLACE({c}, ' ', ''), '-', ''), '.', ''))"
    conn = db.get_connection()
    try:
        f = conn.execute(f"SELECT contraparte_nombre AS nombre, contraparte_nif AS nif, contraparte_nif_tipo AS nif_tipo, contraparte_pais AS pais, tipo_iva_centesimas, clave, calificacion, exenta, "
                         f"tipo_factura, libro FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND anulado_en IS NULL AND {norma.format(c='contraparte_nif')} = ? "
                         f"ORDER BY CASE WHEN libro = ? THEN 0 ELSE 1 END, id DESC LIMIT 1", (tenant_id, cliente_fiscal_id, limpio, libro or "")).fetchone()
        if f:
            hallada = dict(f)
            if libro and hallada["libro"] == libro:                       # lo habitual con esta contraparte en este libro: se propone, la persona lo cambia si quiere
                hallada["habitual"] = {"tipo_iva": f"{hallada['tipo_iva_centesimas'] / 100:g}".replace(".", ","), "clave": hallada["clave"], "calificacion": hallada["calificacion"],
                                       "exenta": hallada["exenta"], "tipo_factura": hallada["tipo_factura"]}
            for k in ("tipo_iva_centesimas", "clave", "calificacion", "exenta", "tipo_factura", "libro"):
                hallada.pop(k)
            return {**hallada, "origen": "apuntes"}
        f = conn.execute(f"SELECT nombre, nif FROM contabilidad_terceros WHERE tenant_id = ? AND cliente_fiscal_id = ? AND {norma.format(c='nif')} = ? AND nombre IS NOT NULL AND nombre <> '' LIMIT 1",
                         (tenant_id, cliente_fiscal_id, limpio)).fetchone()
        if not f:
            f = conn.execute(f"SELECT tercero_nombre AS nombre, tercero_nif AS nif FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartada' "
                             f"AND {norma.format(c='tercero_nif')} = ? ORDER BY id DESC LIMIT 1", (tenant_id, cliente_fiscal_id, limpio)).fetchone()
        if f:
            return {"nombre": f["nombre"], "nif": f["nif"], "nif_tipo": "", "pais": "", "origen": "facturas"}
    finally:
        conn.close()
    return None


def _siguiente(texto: str) -> str:
    """«A-0007» → «A-0008»; sin número al final, vacío."""
    m = re.search(r"(\d+)$", texto or "")
    if not m:
        return ""
    n = m.group(1)
    return texto[:m.start()] + str(int(n) + 1).zfill(len(n))


def siguiente_numero(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int | None = None) -> dict:
    """La serie y el número que tocan tras la última factura EMITIDA de este titular (por defecto en el formulario). Vacío si aún no hay ninguna."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT serie, numero FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND libro = 'E' AND anulado_en IS NULL AND SUBSTR(tipo_factura, 1, 1) <> 'R' "
                         "ORDER BY fecha_expedicion DESC, id DESC LIMIT 1", (tenant_id, cliente_fiscal_id)).fetchone()
    finally:
        conn.close()
    if not f:
        return {"serie": "", "numero": ""}
    siguiente = _siguiente(f["numero"])
    return {"serie": f["serie"] or "", "numero": siguiente} if siguiente else {"serie": f["serie"] or "", "numero": ""}


def _mes_despues(texto: str, meses: int) -> str:
    """La fecha `texto` (AAAA-MM-DD) desplazada `meses` meses, con el día recortado al último del mes (31 de enero + 1 mes = 28/29 de febrero), siempre contando desde la fecha original."""
    import calendar
    d = date.fromisoformat(texto[:10])
    indice = d.year * 12 + d.month - 1 + meses
    anio, mes = divmod(indice, 12)
    return date(anio, mes + 1, min(d.day, calendar.monthrange(anio, mes + 1)[1])).isoformat()


def repetir_apunte(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, apunte_id: int, *, hasta: str, hoy: date | None = None) -> dict:
    """Alquileres y gastos fijos: crea una copia APROBADA del apunte por cada mes desde el siguiente hasta `hasta` («AAAA-MM», como mucho 12 meses), con los mismos importes y la misma retención de IRPF.
    No crea apuntes con fecha futura (no se validarían: se salta lo que falta y se dice), ni repite un mes que ya tiene un apunte igual (misma contraparte, libro e importe), así que se puede volver a lanzar.
    Las copias de una factura recibida llevan el número del original con el mes añadido: se corrige cuando llega la factura real. Devuelve `{"creados": [ids], "ya_existian": n, "futuros": n}`."""
    _exigir_aprobador(tenant_id, usuario_id)
    hoy = hoy or date.today()
    filas = listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id)
    fila = next((f for f in filas if f["id"] == apunte_id), None)
    if not fila:
        raise ErrorFiscal("El apunte no existe o está anulado.", "no_encontrado")
    if fila["tipo_factura"] in RECTIFICATIVAS_APUNTE:
        raise ErrorFiscal("No se repite una factura rectificativa.")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", hasta or ""):
        raise ErrorFiscal("Indica el último mes como AAAA-MM.")
    origen = date.fromisoformat(fila["fecha_expedicion"][:10])
    meses = (int(hasta[:4]) * 12 + int(hasta[5:7])) - (origen.year * 12 + origen.month)
    if meses < 1:
        raise ErrorFiscal("El último mes debe ser posterior al del apunte.")
    if meses > 12:
        raise ErrorFiscal("Como mucho se repite durante 12 meses de una vez.")
    nif = _nif_limpio(fila["contraparte_nif"])
    existentes = {(f["libro"], _nif_limpio(f["contraparte_nif"]), f["base_centimos"], f["tipo_iva_centesimas"], f["fecha_expedicion"][:7]) for f in filas}
    retencion = None
    if fila.get("retencion_modelo"):
        retencion = {"modelo": fila["retencion_modelo"], "clave": fila["retencion_clave"], "base": fila["retencion_base_centimos"], "pct": fila["retencion_pct_centesimas"], "importe": fila["retencion_centimos"]}
    base_apunte = a_apunte(fila).con(deducible_periodo_posterior=False, periodo_deduccion=None)
    creados, ya_existian, futuros = [], 0, 0
    for n in range(1, meses + 1):
        fecha = _mes_despues(fila["fecha_expedicion"], n)
        if date.fromisoformat(fecha) > hoy:
            futuros += 1
            continue
        if (fila["libro"], nif, fila["base_centimos"], fila["tipo_iva_centesimas"], fecha[:7]) in existentes:
            ya_existian += 1
            continue
        etiqueta = fecha[:7].replace("-", "")
        numero, serie = f"{fila['numero']}-{etiqueta}", fila["serie"] or ""
        if fila["libro"] == "E":
            sig = siguiente_numero(tenant_id, usuario_id, cliente_fiscal_id)
            if sig["numero"]:
                numero, serie = sig["numero"], sig["serie"]
        copia = base_apunte.con(fecha_expedicion=date.fromisoformat(fecha), numero=numero, serie=serie,
                                fecha_operacion=date.fromisoformat(_mes_despues(fila["fecha_operacion"], n)) if fila["fecha_operacion"] else None,
                                fecha_recepcion=date.fromisoformat(_mes_despues(fila["fecha_recepcion"], n)) if fila["fecha_recepcion"] else None)
        creados.append(aprobar_apunte(tenant_id, usuario_id, cliente_fiscal_id, copia, retencion=retencion)["id"])
    auditoria.registrar(tenant_id, usuario_id, "fiscal.apunte.repetir", "cliente_fiscal", cliente_fiscal_id, {"apunte_id": apunte_id, "hasta": hasta, "creados": len(creados), "ya_existian": ya_existian, "futuros": futuros})
    return {"creados": creados, "ya_existian": ya_existian, "futuros": futuros}


def capturas_recientes(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, limite: int = 8) -> list[dict]:
    """Las últimas facturas subidas por el despacho (foto o PDF) de un titular, con su estado de lectura: `pendiente` (sin leer), `ia` (leída), `fallida` o `None` (ya escrita a mano)."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, tipo, estado, lectura, creado_en, numero FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND origen = 'despacho' "
                                              "AND documento_id IS NOT NULL ORDER BY id DESC LIMIT ?", (tenant_id, cliente_fiscal_id, limite)).fetchall()]
    finally:
        conn.close()


def existe_apunte(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, libro: str, serie: str, numero: str, nif: str, excluir_id: int | None = None) -> dict | None:
    """El apunte vivo con ese libro, serie, número y contraparte (aviso de duplicado en el formulario)."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    if not (numero or "").strip():
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, fecha_expedicion, contraparte_nombre FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND anulado_en IS NULL AND libro = ? AND COALESCE(serie, '') = ? "
                         "AND numero = ? AND UPPER(REPLACE(REPLACE(COALESCE(contraparte_nif, ''), ' ', ''), '-', '')) = ? AND id <> ? ORDER BY id DESC LIMIT 1",
                         (tenant_id, cliente_fiscal_id, libro, (serie or "").strip(), numero.strip(), _nif_limpio(nif), excluir_id or 0)).fetchone()
    finally:
        conn.close()
    return dict(f) if f else None


def duplicada_en_otros_titulares(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, libro: str, serie: str, numero: str, nif: str) -> list[str]:
    """Los OTROS titulares del despacho (que esta persona puede ver) que ya tienen una factura con el mismo número y contraparte, ya sea apunte o factura de «Facturas para contabilizar» (portal, subida
    del cliente…). Una recibida repetida en dos titulares suele ser una factura subida al cliente equivocado. Solo avisa; no impide nada."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    limpio = _nif_limpio(nif)
    if not (numero or "").strip() or len(limpio) < 5:
        return []
    norma = "UPPER(REPLACE(REPLACE(REPLACE({c}, ' ', ''), '-', ''), '.', ''))"
    conn = db.get_connection()
    try:
        ids = {f["cliente_fiscal_id"] for f in conn.execute(
            f"SELECT DISTINCT cliente_fiscal_id FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id <> ? AND anulado_en IS NULL AND libro = ? AND COALESCE(serie, '') = ? AND numero = ? "
            f"AND {norma.format(c='contraparte_nif')} = ?", (tenant_id, cliente_fiscal_id, libro, (serie or "").strip(), numero.strip(), limpio)).fetchall()}
        ids |= {f["cliente_fiscal_id"] for f in conn.execute(
            f"SELECT DISTINCT cliente_fiscal_id FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id <> ? AND estado != 'descartada' AND tipo = ? AND numero = ? "
            f"AND {norma.format(c='tercero_nif')} = ?", (tenant_id, cliente_fiscal_id, "emitida" if libro == "E" else "recibida", f"{(serie or '').strip()}{numero.strip()}", limpio)).fetchall()}
        nombres = []
        for cid in sorted(ids):
            if acceso.puede_ver_cliente(tenant_id, usuario_id, cid):
                f = conn.execute("SELECT nombre FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cid, tenant_id)).fetchone()
                if f:
                    nombres.append(f["nombre"])
    finally:
        conn.close()
    return nombres[:5]


def listar_apuntes(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, *, ejercicio: int | None = None, incluir_anulados: bool = False) -> list[dict]:
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    sql = "SELECT * FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ?"
    args: list = [tenant_id, cliente_fiscal_id]
    if ejercicio:
        sql += " AND substr(fecha_expedicion, 1, 4) IN (?, ?)"
        args += [str(ejercicio - 1), str(ejercicio)]
    if not incluir_anulados:
        sql += " AND anulado_en IS NULL"
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(sql + " ORDER BY fecha_expedicion, id", args).fetchall()]
    finally:
        conn.close()


def historial_apunte(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, apunte_id: int) -> list[dict]:
    """Quién aprobó, corrigió o anuló un apunte y qué cambió (valor anterior → nuevo), del más reciente al más antiguo. Sale de la auditoría, que no se puede alterar."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    eventos = auditoria.listar(tenant_id, entidad="cliente_fiscal", entidad_id=cliente_fiscal_id, limite=500)
    return [{"cuando": e["creado_en"], "quien": e.get("actor") or "—", "accion": e["accion"].rsplit(".", 1)[-1], "cambios": e["detalle"].get("cambios") or {},
             "motivo": e["detalle"].get("causa") or e["detalle"].get("motivo") or ""}
            for e in eventos if e["accion"].startswith("fiscal.apunte.") and isinstance(e.get("detalle"), dict) and e["detalle"].get("apunte_id") == apunte_id]


def proponer_desde_factura(tenant_id: int, usuario_id: int, factura_id: int) -> list[dict]:
    """Propuesta (NO aprobada, NO guardada) de apuntes para revisar a partir de una factura ya anotada: un apunte por tipo de IVA. La revisión humana decide clave, calificación, deducibilidad…"""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM facturas_contables WHERE id = ? AND tenant_id = ?", (factura_id, tenant_id)).fetchone()
        if not f:
            raise ErrorFiscal("La factura no existe.", "no_encontrado")
        _exigir_acceso(tenant_id, usuario_id, f["cliente_fiscal_id"])
        lineas = conn.execute("SELECT base_centimos, pct_iva, cuota_iva, pct_recargo, cuota_recargo, sujeta_iva, pct_retencion, cuota_retencion FROM facturas_contables_lineas WHERE factura_id = ? ORDER BY id", (factura_id,)).fetchall()
    finally:
        conn.close()
    agrupadas: dict[tuple[int, int], list[int]] = {}
    for ln in lineas:
        g = agrupadas.setdefault((ln["pct_iva"] if ln["sujeta_iva"] else -1, (ln["pct_recargo"] or 0) if ln["sujeta_iva"] else 0), [0, 0, 0])
        g[0] += ln["base_centimos"]
        g[1] += ln["cuota_iva"]
        g[2] += ln["cuota_recargo"] or 0
    ret_base = sum(ln["base_centimos"] for ln in lineas if (ln["pct_retencion"] or 0) > 0)             # retención de IRPF de la factura: solo la practica quien la recibe (111 por defecto; el 115 lo decide la revisión)
    ret_importe = sum(ln["cuota_retencion"] or 0 for ln in lineas)
    ret_pct = max([ln["pct_retencion"] or 0 for ln in lineas] + [0])
    propuestas = []
    for n, ((pct, pct_recargo), (base, cuota, cuota_recargo)) in enumerate(sorted(agrupadas.items()), 1):
        emitida = f["tipo"] == "emitida"
        if f["abono"] and base > 0:                                    # un abono/rectificativa va en negativo en los libros
            base, cuota, cuota_recargo = -base, -cuota, -cuota_recargo
        retencion = None
        if n == 1 and not emitida and ret_importe and ret_pct:                  # una sola vez por factura, aunque se reparta en varios apuntes por tipo de IVA
            s = -1 if f["abono"] else 1
            retencion = {"modelo": "111", "clave": "G", "base": s * ret_base, "pct": int(round(ret_pct)), "importe": s * ret_importe}
        propuestas.append({
            "factura_id": factura_id, "libro": "E" if emitida else "R", "tipo_factura": ("R1" if f["abono"] else "F1"), "clave": "01", "calificacion": "S1" if pct >= 0 else "N1", "exenta": "",
            "serie": "", "numero": f["numero"] if len(agrupadas) == 1 else f"{f['numero']}/{n}", "fecha_expedicion": f["fecha"], "fecha_operacion": f["fecha_operacion"],
            "fecha_recepcion": None if emitida else f["fecha"], "base_centimos": base, "tipo_iva_centesimas": max(pct, 0), "cuota_centimos": cuota, "total_centimos": None,
            "contraparte_nombre": f["tercero_nombre"], "contraparte_nif": f["tercero_nif"] or "", "aprobado": False, "retencion": retencion,
            "recargo_pct_centesimas": pct_recargo if emitida else 0, "recargo_cuota_centimos": cuota_recargo if emitida else 0,
        })
    return propuestas


# --- Instantáneas -------------------------------------------------------------------------------------------------------------------------------
def facturas_por_registrar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int) -> list[dict]:
    """Facturas ya REVISADAS en «Facturas para contabilizar» del ejercicio que aún no tienen apunte fiscal. `automatica`: todas sus líneas son de IVA al 4, 10 o 21 % sin recargo ni conceptos
    especiales, así que se pueden aprobar de golpe; las demás hay que mirarlas una a una."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        facturas = [dict(f) for f in conn.execute(
            "SELECT id, tipo, fecha, numero, tercero_nombre, total_centimos, abono FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('revisada', 'exportada') AND incluir_en_fiscal = 1 "
            "AND substr(fecha, 1, 4) = ? AND id NOT IN (SELECT factura_id FROM fiscal_apuntes WHERE tenant_id = ? AND factura_id IS NOT NULL AND anulado_en IS NULL) ORDER BY fecha, id",
            (tenant_id, cliente_fiscal_id, str(ejercicio), tenant_id)).fetchall()]
        for f in facturas:
            lineas = conn.execute("SELECT pct_iva, pct_recargo, sujeta_iva, pct_retencion FROM facturas_contables_lineas WHERE factura_id = ?", (f["id"],)).fetchall()
            f["automatica"] = bool(lineas) and all(l["sujeta_iva"] and l["pct_iva"] in (400, 1000, 2100) and not l["pct_recargo"] for l in lineas)
    finally:
        conn.close()
    return facturas


def _limites_periodo(ejercicio: int, periodo: str) -> tuple[str, str]:
    mes_fin = int(periodo[0]) * 3 if periodo.endswith("T") else int(periodo)
    mes_ini = mes_fin - 2 if periodo.endswith("T") else mes_fin
    return date(ejercicio, mes_ini, 1).isoformat(), _fecha_fin_periodo(ejercicio, periodo).isoformat()


def facturas_del_periodo(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str) -> dict:
    """Qué facturas del periodo computan y en qué modelo. Una misma factura puede ir en varios: el **303** (IVA, cuando ya es un apunte aprobado) y las **retenciones de IRPF** que lleve en sus líneas:
    si es recibida las practica el cliente (modelo 111, o 115 si es un alquiler), si es emitida las soporta él (no van en el 111). Para cada modelo: `computa` (ya cuenta), `por_registrar` / `por_revisar`
    (aún no cuenta) o `excluida` (se sacó de Guilda Fiscal). El cálculo automático del 111 todavía no existe: aquí se ve qué entrará en él. Importes en céntimos; los abonos restan."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    if periodo not in tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T"):
        raise ErrorFiscal("Periodo no válido.")
    desde, hasta = _limites_periodo(ejercicio, periodo)
    conn = db.get_connection()
    try:
        facturas = [dict(f) for f in conn.execute(
            "SELECT f.id, f.tipo, f.estado, f.fecha, f.numero, f.tercero_nombre, f.abono, f.total_centimos, f.incluir_en_fiscal, "
            "COALESCE(SUM(l.base_centimos), 0) AS base, COALESCE(SUM(l.cuota_iva), 0) AS cuota_iva, COALESCE(SUM(l.cuota_retencion), 0) AS retencion, "
            "COALESCE(SUM(CASE WHEN l.pct_retencion > 0 THEN l.base_centimos ELSE 0 END), 0) AS base_retencion, COALESCE(MAX(l.pct_retencion), 0) AS pct_retencion "
            "FROM facturas_contables f LEFT JOIN facturas_contables_lineas l ON l.factura_id = f.id "
            "WHERE f.tenant_id = ? AND f.cliente_fiscal_id = ? AND f.estado != 'descartada' AND f.fecha >= ? AND f.fecha <= ? "
            "GROUP BY f.id, f.tipo, f.estado, f.fecha, f.numero, f.tercero_nombre, f.abono, f.total_centimos, f.incluir_en_fiscal ORDER BY f.fecha, f.id",
            (tenant_id, cliente_fiscal_id, desde, hasta)).fetchall()]
        apuntes = {}
        for a in conn.execute("SELECT id, factura_id, clave, base_centimos, cuota_centimos, retencion_modelo, retencion_centimos FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND factura_id IS NOT NULL "
                              "AND anulado_en IS NULL ORDER BY id", (tenant_id, cliente_fiscal_id)).fetchall():
            previo = apuntes.get(a["factura_id"])
            if previo:
                previo["base_centimos"] += a["base_centimos"]
                previo["cuota_centimos"] += a["cuota_centimos"]
                previo["retencion_centimos"] = (previo["retencion_centimos"] or 0) + (a["retencion_centimos"] or 0)
                previo["retencion_modelo"] = previo["retencion_modelo"] or a["retencion_modelo"]
            else:
                apuntes[a["factura_id"]] = dict(a)
    finally:
        conn.close()
    totales = {"iva_repercutido": 0, "iva_soportado": 0, "retenciones_111": 0, "retenciones_115": 0, "retenciones_soportadas": 0, "no_computan": 0, "descuadres": 0}
    for f in facturas:
        signo = -1 if f["abono"] else 1
        for k in ("base", "cuota_iva", "retencion", "base_retencion"):
            f[k] *= signo
        ap = apuntes.get(f["id"])
        f["apunte_id"] = ap["id"] if ap else None
        f["descuadre"] = bool(ap) and (ap["base_centimos"] != f["base"] or ap["cuota_centimos"] != f["cuota_iva"])         # el apunte aprobado ya no coincide con la factura de la que salió
        revisada = f["estado"] in ("revisada", "exportada")
        if not f["incluir_en_fiscal"]:
            f["m303"] = "excluida"
        elif ap:
            f["m303"] = "computa"
        elif revisada:
            f["m303"] = "por_registrar"
        else:
            f["m303"] = "por_revisar"
        f["m_retencion"], f["retencion_estado"] = None, None
        if f["retencion"]:
            if f["tipo"] == "emitida":
                f["m_retencion"], f["retencion_estado"] = "soportada", "computa" if f["incluir_en_fiscal"] else "excluida"
            elif ap and ap["retencion_modelo"]:                                   # la retención ya está en el apunte aprobado: eso es lo que cuenta
                f["m_retencion"], f["retencion_estado"], f["retencion"] = ap["retencion_modelo"], "computa" if f["incluir_en_fiscal"] else "excluida", ap["retencion_centimos"] or 0
            else:
                f["m_retencion"] = "115" if (ap and ap["clave"] in ("11", "12", "13")) else "111"
                if not f["incluir_en_fiscal"]:
                    f["retencion_estado"] = "excluida"
                else:                                                             # apunte aprobado sin la retención: hay que corregirlo para que cuente
                    f["retencion_estado"] = "por_revisar" if ap or not revisada else "por_registrar"
        if f["m303"] == "computa":
            totales["iva_repercutido" if f["tipo"] == "emitida" else "iva_soportado"] += f["cuota_iva"]
        if f["retencion_estado"] == "computa":
            totales[{"111": "retenciones_111", "115": "retenciones_115", "soportada": "retenciones_soportadas"}[f["m_retencion"]]] += f["retencion"]
        if f["m303"] != "computa" and f["retencion_estado"] != "computa":
            totales["no_computan"] += 1
        totales["descuadres"] += 1 if f["descuadre"] else 0
    return {"ejercicio": ejercicio, "periodo": periodo, "desde": desde, "hasta": hasta, "facturas": facturas, "totales": totales}


def informe_trimestral(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str) -> dict:
    """Datos del informe trimestral para el cliente: lo que computa en el periodo, la última declaración viva del 303 y lo que falta. Solo lee."""
    datos = facturas_del_periodo(tenant_id, usuario_id, cliente_fiscal_id, ejercicio, periodo)
    pend = pendiente_de_recordar(tenant_id, usuario_id, cliente_fiscal_id, ejercicio, periodo)
    declaracion = next((d for d in listar_declaraciones(tenant_id, usuario_id, cliente_fiscal_id) if d["ejercicio"] == ejercicio and d["periodo"] == periodo and d["estado"] != "anulada"), None)
    datos.update({"declaracion": declaracion, "fecha_limite": pend["fecha_limite"], "emitidas": pend["emitidas"], "recibidas": pend["recibidas"], "sin_registrar": len(pend["sin_registrar"]),
                  "no_computan": datos["totales"]["no_computan"]})
    return datos


def _declaraciones_vigentes(tenant_id: int, cliente_fiscal_id: int, ejercicio: int) -> dict[str, dict]:
    """Por trimestre, la última declaración del 303 REVISADA o posterior (la que ya vale para el 390): `{"1T": {"id", "estado", "casillas", "tipo_declaracion"}}`."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, periodo, estado, tipo_declaracion FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND ejercicio = ? "
                             "AND estado IN ('revisada','exportada','presentada') ORDER BY id", (tenant_id, cliente_fiscal_id, ejercicio)).fetchall()
        salida = {}
        for f in filas:
            if f["periodo"] in motor_390.TRIMESTRES:
                salida[f["periodo"]] = {"id": f["id"], "estado": f["estado"], "tipo_declaracion": f["tipo_declaracion"],
                                        "casillas": {c["casilla"]: c["valor"] for c in conn.execute("SELECT casilla, valor FROM fiscal_casillas WHERE declaracion_id = ? AND tenant_id = ?", (f["id"], tenant_id)).fetchall()}}
        return salida
    finally:
        conn.close()


def resumen_390(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int) -> dict:
    """Resumen anual (modelo 390) calculado AHORA con los apuntes aprobados del año y cuadrado con los 303 ya revisados. No se guarda nada: es una vista que se recalcula. Devuelve el titular, el perfil,
    si está obligado a presentarlo, el `Resultado390` y las declaraciones del 303 en que se apoya."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    perfil = fiscal_perfiles.perfil_en(tenant_id, cliente_fiscal_id, date(ejercicio, 12, 31).isoformat())
    if not perfil:
        raise ErrorFiscal("El titular no tiene perfil fiscal vigente a final de ese ejercicio: créalo antes.", "sin_perfil")
    conn = db.get_connection()
    try:
        titular = dict(_titular(conn, tenant_id, cliente_fiscal_id))
    finally:
        conn.close()
    apuntes = [a_apunte(f) for f in listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id, ejercicio=ejercicio)]
    declaraciones = _declaraciones_vigentes(tenant_id, cliente_fiscal_id, ejercicio)
    ajustes, extra = _perfil_a_flags(perfil, "4T")
    resultado = motor_390.calcular(apuntes, ejercicio=ejercicio, saldo_compensar_inicial=max(0, int(perfil["saldo_a_compensar_centimos"] or 0)), declaraciones_303=declaraciones, **ajustes)
    resultado.bloqueos.extend(extra)
    exonerado = bool(perfil["exonerado_390"])
    return {"titular": titular, "perfil": perfil, "ejercicio": ejercicio, "exonerado": exonerado, "resultado": resultado, "declaraciones": declaraciones, "apuntes": len(apuntes),
            "trimestres": [{"periodo": t, "declaracion": declaraciones.get(t)} for t in motor_390.TRIMESTRES]}


def descargar_fichero_390(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int) -> tuple[bytes, str]:
    """El `.390` de PRUEBA del año (se importa en el simulador o el formulario de la AEAT; no se presenta tal cual). Solo quien aprueba apuntes. Queda en la auditoría."""
    _exigir_aprobador(tenant_id, usuario_id)
    r = resumen_390(tenant_id, usuario_id, cliente_fiscal_id, ejercicio)
    if r["exonerado"]:
        raise ErrorFiscal("Este titular está exonerado del 390: la información anual va en el 303 del último periodo.", "no_soportado")
    if not r["resultado"].calculable:
        raise ErrorFiscal("El cálculo del 390 está bloqueado: " + " · ".join(r["resultado"].bloqueos[:3]), "no_soportado")
    try:
        contenido = fichero_390.generar(r["resultado"], nif=(r["titular"]["nif"] or "").upper(), nombre=r["titular"]["nombre"])
    except (fichero_390.FicheroNoGenerable, exportador_303.ErrorDeFormato) as e:
        raise ErrorFiscal(str(e), "no_soportado")
    auditoria.registrar(tenant_id, usuario_id, "fiscal.390.descargar", "cliente_fiscal", cliente_fiscal_id, {"ejercicio": ejercicio, "hash": hashlib.sha256(contenido).hexdigest()})
    return contenido, f"{ejercicio}_390_prueba.390"


def _acumulados_130(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int) -> dict[str, dict[str, int]]:
    """Por trimestre, lo acumulado desde el 1 de enero hasta su último día, con los apuntes aprobados: `ingresos` (base de las emitidas, con abonos restando), `gastos` (base de las recibidas más el IVA que
    no se dedujo, sin los bienes de inversión, que se amortizan) y `retenciones` (de IRPF soportadas en las facturas emitidas que ya son apunte). `inversion` cuenta los bienes de inversión que se han dejado fuera."""
    apuntes = [a_apunte(f) for f in listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id, ejercicio=ejercicio)]
    salida = {}
    for t in ("1T", "2T", "3T", "4T"):
        fin = _fecha_fin_periodo(ejercicio, t)
        ingresos = gastos = inversion = 0
        for a in apuntes:
            fecha = a.fecha_expedicion if a.tipo_factura in motor_303_RECTIFICATIVAS else (a.fecha_operacion or a.fecha_expedicion)
            if fecha.year != ejercicio or fecha > fin:
                continue
            if a.libro == "E":
                ingresos += a.base
            elif a.bien_inversion:
                inversion += 1
            else:
                gastos += a.base + (a.cuota - a.deducible if a.clave != "09" and not a.isp else 0)
        retenciones = 0
        for p in ("1T", "2T", "3T", "4T"):
            if p > t:
                break
            retenciones += sum(f["retencion"] for f in facturas_del_periodo(tenant_id, usuario_id, cliente_fiscal_id, ejercicio, p)["facturas"]
                               if f["m_retencion"] == "soportada" and f["m303"] == "computa" and f["incluir_en_fiscal"])
        salida[t] = {"ingresos": ingresos, "gastos": gastos, "retenciones": retenciones, "inversion": inversion}
    return salida


def calculo_130(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str, *, otros_ingresos: int = 0, otros_gastos: int = 0, otras_retenciones: int = 0,
                rendimiento_anterior: int | None = None, simplificada: bool = False, pagos_previos: int | None = None, negativos_previos: int | None = None) -> dict:
    """Modelo 130 del trimestre calculado AHORA con los apuntes aprobados (no se guarda: no hay borrador ni estados). Los ajustes son importes ACUMULADOS del año que los apuntes no recogen (cuotas de
    autónomos, amortizaciones, ingresos sin factura…). `pagos_previos` (casilla 05) y `negativos_previos` (casilla 15) salen, si no se dan, de calcular los trimestres anteriores solo con los apuntes, como
    si se hubieran presentado así: es una suposición y se avisa. Devuelve `{"resultado", "sumas", "pagos_previos", "negativos_previos", "calculados_de_los_anteriores", "titular"}`."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    if periodo not in ("1T", "2T", "3T", "4T"):
        raise ErrorFiscal("El 130 es trimestral: 1T, 2T, 3T o 4T.")
    perfil = fiscal_perfiles.perfil_en(tenant_id, cliente_fiscal_id, _fecha_fin_periodo(ejercicio, periodo).isoformat())
    if not perfil:
        raise ErrorFiscal("El titular no tiene perfil fiscal vigente en ese periodo: créalo antes.", "sin_perfil")
    conn = db.get_connection()
    try:
        titular = dict(_titular(conn, tenant_id, cliente_fiscal_id))
    finally:
        conn.close()
    sumas = _acumulados_130(tenant_id, usuario_id, cliente_fiscal_id, ejercicio)
    # trimestres anteriores, solo con los apuntes
    pagos = negativos = 0
    for t in ("1T", "2T", "3T"):
        if t >= periodo:
            break
        s = sumas[t]
        previo = motor_130.calcular(ejercicio=ejercicio, periodo=t, ingresos=s["ingresos"], gastos=s["gastos"], retenciones=s["retenciones"], pagos_previos=pagos, negativos_previos=negativos,
                                    rendimiento_anterior=rendimiento_anterior, simplificada=simplificada)
        if not previo.calculable:
            continue
        pagos += max(0, previo.casillas["07"]) - previo.casillas.get("16", 0)
        negativos = max(0, negativos - previo.casillas.get("15", 0)) + (-previo.casillas["19"] if previo.casillas["19"] < 0 else 0)
    de_los_anteriores = pagos_previos is None and negativos_previos is None
    s = sumas[periodo]
    resultado = motor_130.calcular(ejercicio=ejercicio, periodo=periodo, ingresos=s["ingresos"] + otros_ingresos, gastos=s["gastos"] + otros_gastos, retenciones=s["retenciones"] + otras_retenciones,
                                   pagos_previos=pagos if pagos_previos is None else pagos_previos, negativos_previos=negativos if negativos_previos is None else negativos_previos,
                                   rendimiento_anterior=rendimiento_anterior, simplificada=simplificada)
    if perfil["forma_juridica"] != "persona_fisica":
        resultado.bloqueos.append("El modelo 130 lo presentan personas físicas con actividad económica en estimación directa: el perfil de este titular no es de persona física.")
    if de_los_anteriores and periodo != "1T":
        resultado.avisos.append("Los pagos de trimestres anteriores (casilla 05) y los resultados negativos pendientes (casilla 15) se han calculado con los apuntes, como si cada trimestre se hubiera presentado "
                                "así. Si lo presentado fue distinto, indícalo.")
    if s["inversion"]:
        resultado.avisos.append(f"Hay {s['inversion']} apunte(s) de bienes de inversión que no se cuentan como gasto: se amortizan. Suma la amortización del año en «otros gastos».")
    return {"resultado": resultado, "sumas": s, "pagos_previos": pagos if pagos_previos is None else pagos_previos, "negativos_previos": negativos if negativos_previos is None else negativos_previos,
            "calculados_de_los_anteriores": de_los_anteriores, "titular": titular}


def descargar_fichero_130(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str, **ajustes) -> tuple[bytes, str]:
    """El fichero de PRUEBA del 130 (se importa en el simulador o el formulario de la AEAT; no se presenta tal cual). Solo quien aprueba apuntes. Queda en la auditoría."""
    _exigir_aprobador(tenant_id, usuario_id)
    c = calculo_130(tenant_id, usuario_id, cliente_fiscal_id, ejercicio, periodo, **ajustes)
    if not c["resultado"].calculable:
        raise ErrorFiscal("El cálculo del 130 está bloqueado: " + " · ".join(c["resultado"].bloqueos[:3]), "no_soportado")
    try:
        contenido = fichero_retenciones.generar(c["resultado"], nif=(c["titular"]["nif"] or "").upper(), nombre=c["titular"]["nombre"])
    except (fichero_retenciones.FicheroNoGenerable, exportador_303.ErrorDeFormato) as e:
        raise ErrorFiscal(str(e), "no_soportado")
    auditoria.registrar(tenant_id, usuario_id, "fiscal.130.descargar", "cliente_fiscal", cliente_fiscal_id, {"ejercicio": ejercicio, "periodo": periodo, "resultado": c["resultado"].casillas.get("19", 0),
                                                                                                         "hash": hashlib.sha256(contenido).hexdigest()})
    return contenido, f"{ejercicio}_{periodo}_130_prueba.txt"


def descargar_fichero_retenciones(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, modelo: str, ejercicio: int, periodo: str) -> tuple[bytes, str]:
    """El fichero de PRUEBA del modelo 111 o 115 del periodo (se importa en el simulador o el formulario de la AEAT; no se presenta tal cual), calculado ahora con las retenciones de los apuntes aprobados.
    No tiene borrador, revisión ni estados propios como el 303. Solo quien aprueba apuntes. Queda en la auditoría."""
    if modelo not in ("111", "115"):
        raise ErrorFiscal("Solo los modelos 111 y 115.", "no_encontrado")
    _exigir_aprobador(tenant_id, usuario_id)
    simulado = simular_retenciones(tenant_id, usuario_id, cliente_fiscal_id, ejercicio, periodo)[modelo]
    if not simulado.casillas.get("03", 0) and not simulado.casillas.get("09", 0):
        raise ErrorFiscal(f"No hay retenciones del modelo {modelo} en este periodo: no hay nada que declarar.", "sin_datos")
    conn = db.get_connection()
    try:
        titular = _titular(conn, tenant_id, cliente_fiscal_id)
    finally:
        conn.close()
    try:
        contenido = fichero_retenciones.generar(simulado, nif=(titular["nif"] or "").upper(), nombre=titular["nombre"])
    except (fichero_retenciones.FicheroNoGenerable, exportador_303.ErrorDeFormato) as e:
        raise ErrorFiscal(str(e), "no_soportado")
    auditoria.registrar(tenant_id, usuario_id, "fiscal.retenciones.descargar", "cliente_fiscal", cliente_fiscal_id, {"modelo": modelo, "ejercicio": ejercicio, "periodo": periodo,
                                                                                                                 "hash": hashlib.sha256(contenido).hexdigest()})
    return contenido, f"{ejercicio}_{periodo}_{modelo}_prueba.txt"


def checklist_cierre(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str, *, hoy: date | None = None) -> dict:
    """Lista de comprobaciones para cerrar un trimestre del 303, calculada AHORA con lo que hay (no se guarda: no puede quedar desfasada). Cada punto es `ok`, `pendiente` (hay que hacer algo) o `aviso` (conviene
    mirarlo). `listo` es verdadero cuando no queda ningún `pendiente`. Orden: datos → apuntes → declaración → presentación."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    if periodo not in ("1T", "2T", "3T", "4T"):
        raise ErrorFiscal("Periodo no válido.")
    hoy = hoy or date.today()
    perfil = fiscal_perfiles.perfil_en(tenant_id, cliente_fiscal_id, _fecha_fin_periodo(ejercicio, periodo).isoformat())
    puntos: list[dict] = []

    def punto(clave: str, estado: str, detalle: str = "", cuantos: int = 0) -> None:
        puntos.append({"clave": clave, "estado": estado, "detalle": detalle, "cuantos": cuantos})

    punto("perfil", "ok" if perfil else "pendiente")
    computan = facturas_del_periodo(tenant_id, usuario_id, cliente_fiscal_id, ejercicio, periodo)
    por_revisar = sum(1 for f in computan["facturas"] if f["incluir_en_fiscal"] and f["m303"] == "por_revisar")
    por_registrar = sum(1 for f in computan["facturas"] if f["incluir_en_fiscal"] and f["m303"] == "por_registrar")
    retenciones = sum(1 for f in computan["facturas"] if f["retencion_estado"] in ("por_revisar", "por_registrar"))
    punto("revisar", "ok" if not por_revisar else "pendiente", cuantos=por_revisar)
    punto("registrar", "ok" if not por_registrar else "pendiente", cuantos=por_registrar)
    punto("descuadres", "ok" if not computan["totales"]["descuadres"] else "pendiente", cuantos=computan["totales"]["descuadres"])
    punto("retenciones", "ok" if not retenciones else "aviso", cuantos=retenciones)
    apuntes = [a for a in listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id, ejercicio=ejercicio) if motor_303_en_periodo(a["fecha_expedicion"], ejercicio, periodo)]
    punto("libros", "ok" if apuntes else "aviso", cuantos=len(apuntes))
    if apuntes:
        titular = None
        conn = db.get_connection()
        try:
            titular = _titular(conn, tenant_id, cliente_fiscal_id)
        finally:
            conn.close()
        errores = validacion_apuntes.errores(validacion_apuntes.validar([a_apunte(a) for a in apuntes], hoy=hoy, nif_titular=titular["nif"] or ""))
        punto("errores", "ok" if not errores else "pendiente", cuantos=len(errores))
    declaraciones = [d for d in listar_declaraciones(tenant_id, usuario_id, cliente_fiscal_id) if d["ejercicio"] == ejercicio and d["periodo"] == periodo and d["estado"] != "anulada"]
    d = declaraciones[0] if declaraciones else None
    nivel = {"borrador": 1, "revisada": 2, "exportada": 3, "presentada": 4}.get(d["estado"], 0) if d else 0
    punto("calculada", "ok" if d else "pendiente")
    punto("bloqueos", "ok" if not (d and d["bloqueos"]) else "pendiente", cuantos=len(json.loads(d["bloqueos"])) if d and d["bloqueos"] else 0)
    punto("revisada", "ok" if nivel >= 2 else "pendiente")
    punto("exportada", "ok" if nivel >= 3 else "pendiente")
    punto("presentada", "ok" if nivel >= 4 else "pendiente")
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT estado, fecha_limite FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND periodo = ? AND papelera_en IS NULL ORDER BY id DESC LIMIT 1",
                         (tenant_id, cliente_fiscal_id, f"{periodo} {ejercicio}")).fetchone()
    finally:
        conn.close()
    if not v:
        punto("vencimiento", "aviso")
    else:
        vencido = (v["fecha_limite"] or "")[:10] < hoy.isoformat() and v["estado"] != "presentado"
        punto("vencimiento", "ok" if v["estado"] == "presentado" else ("pendiente" if vencido else "aviso"), detalle=(v["fecha_limite"] or "")[:10])
    return {"ejercicio": ejercicio, "periodo": periodo, "puntos": puntos, "listo": not any(p["estado"] == "pendiente" for p in puntos), "hechos": sum(1 for p in puntos if p["estado"] == "ok"),
            "declaracion_id": d["id"] if d else None}


def simular_retenciones(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str) -> dict:
    """Simulación (NO se guarda ni se presenta) de los modelos 111 y 115 del periodo con las retenciones de los apuntes aprobados. Devuelve `{"111": Resultado, "115": Resultado}`."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    desde, hasta = _limites_periodo(ejercicio, periodo)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT retencion_modelo, retencion_clave, retencion_base_centimos, retencion_centimos, contraparte_nif FROM fiscal_apuntes WHERE tenant_id = ? AND cliente_fiscal_id = ? "
                             "AND libro = 'R' AND anulado_en IS NULL AND retencion_modelo != '' AND fecha_expedicion >= ? AND fecha_expedicion <= ? ORDER BY fecha_expedicion, id",
                             (tenant_id, cliente_fiscal_id, desde, hasta)).fetchall()
    finally:
        conn.close()
    retenciones = [motor_retenciones.Retencion(f["retencion_modelo"], f["retencion_clave"], f["retencion_base_centimos"] or 0, f["retencion_centimos"] or 0, f["contraparte_nif"] or "") for f in filas]
    return {m: motor_retenciones.calcular(retenciones, modelo=m, ejercicio=ejercicio, periodo=periodo) for m in ("111", "115")}


def _periodo_de_vencimiento(texto: str) -> tuple[int, str] | None:
    """«2T 2026» o «2026-T2» -> (2026, «2T»); los demás formatos (anual, mensual) no corresponden a una declaración trimestral del 303."""
    m = re.fullmatch(r"([1-4])T (\d{4})", texto or "") or None
    if m:
        return int(m.group(2)), f"{m.group(1)}T"
    m = re.fullmatch(r"(\d{4})-T([1-4])", texto or "")
    return (int(m.group(1)), f"{m.group(2)}T") if m else None


PESO_DECLARACION = {None: 3, "borrador": 2, "revisada": 1, "exportada": 1, "presentada": 0}          # lo que falta de un 303 según el estado de su declaración


def panel_vencimientos(tenant_id: int, usuario_id: int, *, dias: int = 60, hoy: date | None = None) -> dict:
    """Vencimientos pendientes de los titulares que la persona ve, con la carga de trabajo que cada uno lleva detrás. La carga se mide en «puntos de trabajo», no en horas: 1 por vencimiento, más 1 por
    cada factura aún sin revisar o sin registrar (en los modelos de IVA) y lo que falta de la declaración del 303 (3 sin crear, 2 en borrador, 1 revisada o exportada). Los vencidos van primero; se agrupan por
    semana (lunes) y por responsable. Devuelve `{"filas", "semanas", "responsables", "vencidos"}`."""
    hoy = hoy or date.today()
    limite = (hoy + timedelta(days=dias)).isoformat()
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    facturas = contadores_facturas(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT v.id, v.cliente_fiscal_id, v.modelo, v.periodo, v.fecha_limite, v.usuario_id AS responsable_id, c.nombre AS cliente, u.email AS responsable_email "
            "FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id AND c.tenant_id = v.tenant_id LEFT JOIN usuarios u ON u.id = v.usuario_id "
            "WHERE v.tenant_id = ? AND v.estado <> 'presentado' AND v.papelera_en IS NULL AND c.papelera_en IS NULL AND substr(v.fecha_limite, 1, 10) <= ? ORDER BY v.fecha_limite, c.nombre",
            (tenant_id, limite)).fetchall()]
        estado_decl = {(f["cliente_fiscal_id"], f["ejercicio"], f["periodo"]): f["estado"] for f in conn.execute(
            "SELECT cliente_fiscal_id, ejercicio, periodo, estado FROM fiscal_declaraciones WHERE tenant_id = ? AND modelo = '303' AND estado <> 'anulada' ORDER BY id", (tenant_id,)).fetchall()}
    finally:
        conn.close()
    salida, semanas, responsables = [], {}, {}
    for f in filas:
        if visibles is not None and f["cliente_fiscal_id"] not in visibles:
            continue
        dia = date.fromisoformat(f["fecha_limite"][:10])
        f["dias"] = (dia - hoy).days
        f["nivel"] = "vencido" if f["dias"] < 0 else ("semana" if f["dias"] <= 7 else "proximo")
        pend = facturas.get(f["cliente_fiscal_id"], {"sin_revisar": 0, "por_registrar": 0}) if f["modelo"] in ("303", "390") else {"sin_revisar": 0, "por_registrar": 0}
        per = _periodo_de_vencimiento(f["periodo"]) if f["modelo"] == "303" else None
        f["declaracion"] = estado_decl.get((f["cliente_fiscal_id"], *per)) if per else None
        f["sin_revisar"], f["por_registrar"] = pend["sin_revisar"], pend["por_registrar"]
        f["carga"] = 1 + pend["sin_revisar"] + pend["por_registrar"] + (PESO_DECLARACION.get(f["declaracion"], 1) if per else 0)
        f["responsable"] = (f.pop("responsable_email") or "").split("@")[0]
        lunes = dia - timedelta(days=dia.weekday()) if f["dias"] >= 0 else None
        f["semana"] = lunes.isoformat() if lunes else None
        clave_semana = f["semana"] or "vencidos"
        s = semanas.setdefault(clave_semana, {"inicio": f["semana"], "vencimientos": 0, "carga": 0})
        s["vencimientos"] += 1
        s["carga"] += f["carga"]
        r = responsables.setdefault(f["responsable"] or "", {"responsable": f["responsable"], "vencimientos": 0, "carga": 0})
        r["vencimientos"] += 1
        r["carga"] += f["carga"]
        salida.append(f)
    orden_semanas = sorted(semanas.values(), key=lambda s: s["inicio"] or "")
    return {"filas": salida, "semanas": orden_semanas, "responsables": sorted(responsables.values(), key=lambda r: -r["carga"]), "vencidos": sum(1 for f in salida if f["nivel"] == "vencido"),
            "carga_maxima": max([s["carga"] for s in orden_semanas] + [1])}


def recordatorios_sugeridos(tenant_id: int, usuario_id: int, *, dias: int = 21, hoy: date | None = None) -> list[dict]:
    """Los clientes a quienes conviene recordar ya lo que falta para su 303: el vencimiento está pendiente y cae en los próximos `dias` días (o ya pasó), y aún faltan facturas (por registrar, o ningún libro).
    Solo propone: no escribe a nadie. `puede` = tiene email y no se le ha escrito por este periodo en los últimos `DIAS_ENTRE_RECORDATORIOS` días (los mismos que los recordatorios de facturas)."""
    from . import facturas_contables as fc
    hoy = hoy or date.today()
    limite = (hoy + timedelta(days=dias)).isoformat()
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        venc = [dict(f) for f in conn.execute(
            "SELECT v.cliente_fiscal_id, v.periodo, v.fecha_limite, c.nombre, c.email FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id AND c.tenant_id = v.tenant_id "
            "WHERE v.tenant_id = ? AND v.modelo = '303' AND v.estado <> 'presentado' AND v.papelera_en IS NULL AND c.papelera_en IS NULL AND substr(v.fecha_limite, 1, 10) <= ? "
            "ORDER BY v.fecha_limite, c.nombre", (tenant_id, limite)).fetchall()]
        ultimos = {(f["cliente_fiscal_id"], f["trimestre"]): f["ultimo"] for f in conn.execute(
            "SELECT cliente_fiscal_id, trimestre, MAX(enviado_en) AS ultimo FROM contabilidad_recordatorios WHERE tenant_id = ? GROUP BY cliente_fiscal_id, trimestre", (tenant_id,)).fetchall()}
    finally:
        conn.close()
    desde = (datetime.now() - timedelta(days=fc.DIAS_ENTRE_RECORDATORIOS)).isoformat(timespec="seconds")
    salida = []
    for v in venc:
        per = _periodo_de_vencimiento(v["periodo"])
        if not per or (visibles is not None and v["cliente_fiscal_id"] not in visibles):
            continue
        try:
            p = pendiente_de_recordar(tenant_id, usuario_id, v["cliente_fiscal_id"], per[0], per[1])
        except ErrorFiscal:
            continue
        if not (p["sin_registrar"] or not p["emitidas"] or not p["recibidas"]):
            continue
        clave = f"{per[0]}-T{per[1][0]}"
        ultimo = ultimos.get((v["cliente_fiscal_id"], clave))
        email = (v["email"] or "").strip()
        salida.append({"cliente_id": v["cliente_fiscal_id"], "nombre": v["nombre"], "email": email, "ejercicio": per[0], "trimestre": per[1], "clave": clave, "fecha_limite": v["fecha_limite"][:10],
                       "dias": (date.fromisoformat(v["fecha_limite"][:10]) - hoy).days, "pendiente": p, "ultimo": ultimo, "reciente": bool(ultimo and ultimo > desde),
                       "puede": bool(email) and not (ultimo and ultimo > desde)})
    return salida


def enviar_recordatorios(tenant_id: int, usuario_id: int, envios: list[dict], url_portal: str, *, dias: int = 21) -> dict:
    """Envía los recordatorios CONFIRMADOS: cada envío es `{cliente_id, ejercicio, trimestre, asunto, texto}` con el texto que la persona ha revisado. Solo se escribe a quien sigue siendo una sugerencia válida
    (visible, con email, sin recordatorio reciente): el destinatario sale siempre de la ficha, nunca de lo enviado. Devuelve `{enviados, omitidos: [(nombre, motivo)]}`."""
    from . import facturas_contables as fc, notificaciones_email as ne
    if not ne.configurado():
        raise ErrorFiscal("El correo saliente de la plataforma no está configurado: no se puede avisar a los clientes.")
    validas = {(s["cliente_id"], s["ejercicio"], s["trimestre"]): s for s in recordatorios_sugeridos(tenant_id, usuario_id, dias=dias)}
    enviados, omitidos = 0, []
    for e in envios:
        s = validas.get((int(e["cliente_id"]), int(e["ejercicio"]), e["trimestre"]))
        asunto, texto = (e.get("asunto") or "").strip()[:200], (e.get("texto") or "").strip()[:4000]
        if s is None:
            omitidos.append((f"#{e['cliente_id']}", "ya no es una sugerencia válida"))
        elif not s["email"]:
            omitidos.append((s["nombre"], "no tiene email"))
        elif s["reciente"]:
            omitidos.append((s["nombre"], f"ya se le recordó hace menos de {fc.DIAS_ENTRE_RECORDATORIOS} días"))
        elif not asunto or not texto:
            omitidos.append((s["nombre"], "falta el asunto o el texto"))
        else:
            try:
                ne.enviar_recordatorio_fiscal(s["email"], asunto, texto, url_portal, tenant_id=tenant_id)
            except ne.ErrorNotificacionesEmail as err:
                omitidos.append((s["nombre"], str(err)[:120]))
                continue
            conn = db.get_connection()
            try:
                conn.execute("INSERT INTO contabilidad_recordatorios (tenant_id, cliente_fiscal_id, trimestre, enviado_por, enviado_en) VALUES (?, ?, ?, ?, ?)",
                             (tenant_id, s["cliente_id"], s["clave"], usuario_id, db.now_iso()))
                auditoria.registrar(tenant_id, usuario_id, "fiscal.recordatorio.enviar", "cliente_fiscal", s["cliente_id"], {"periodo": s["clave"], "asunto": asunto}, conn=conn)
                conn.commit()
            finally:
                conn.close()
            enviados += 1
    return {"enviados": enviados, "omitidos": omitidos}


def aprobar_facturas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, factura_ids: list[int]) -> dict:
    """Aprueba de golpe los apuntes de las facturas elegidas (régimen general, clave 01, F1 o R1). Cada factura es independiente: las que fallan no impiden las demás y se devuelven con su motivo."""
    _exigir_aprobador(tenant_id, usuario_id)
    resultado = {"aprobadas": 0, "errores": []}
    for fid in factura_ids:
        try:
            propuestas = proponer_desde_factura(tenant_id, usuario_id, int(fid))
            if not propuestas or any(p["calificacion"] != "S1" for p in propuestas):
                raise ErrorFiscal("Tiene operaciones no sujetas: revísala a mano.")
            for p in propuestas:
                aprobar_apunte(tenant_id, usuario_id, cliente_fiscal_id, a_apunte(p), factura_id=int(fid), retencion=p.get("retencion"))
            resultado["aprobadas"] += len(propuestas)
        except ErrorFiscal as e:
            resultado["errores"].append({"factura_id": int(fid), "motivo": str(e)})
    return resultado


def importar_libro(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, contenido: bytes) -> dict:
    """Importa un libro registro en formato LSI (el de cualquier programa que exporte el formato oficial de la AEAT) como apuntes APROBADOS por quien lo sube. Cada fila es independiente: las que tienen errores
    según las reglas de la AEAT, o no se pueden leer, no entran y se devuelven con su motivo para corregirlas. Una fila idéntica a un apunte ya aprobado (mismo libro, número, fecha y contraparte) no se duplica."""
    _exigir_aprobador(tenant_id, usuario_id)
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    if len(contenido) > 8_000_000:
        raise ErrorFiscal("El fichero es demasiado grande.")
    try:
        apuntes, ilegibles = libros_lsi.leer_xlsx(contenido)
    except Exception as e:                                                      # noqa: BLE001 — un xlsx que no es xlsx
        raise ErrorFiscal("No se puede leer el fichero: no es un libro .xlsx válido.") from e
    existentes = {(a["libro"], a["serie"], a["numero"], a["fecha_expedicion"], a["contraparte_nif"] or "") for a in listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id)}
    r = {"leidos": len(apuntes) + len(ilegibles), "importados": 0, "repetidos": 0, "rechazados": [{"hoja": i["hoja"], "fila": i["fila"], "motivo": i["motivo"]} for i in ilegibles]}
    for n, a in enumerate(apuntes, 1):
        if (a.libro, a.serie, a.numero, a.fecha_expedicion.isoformat(), a.contraparte_nif or "") in existentes:
            r["repetidos"] += 1
            continue
        try:
            aprobar_apunte(tenant_id, usuario_id, cliente_fiscal_id, a)
            r["importados"] += 1
        except ErrorFiscal as e:
            r["rechazados"].append({"hoja": "EXPEDIDAS_INGRESOS" if a.libro == "E" else "RECIBIDAS_GASTOS", "fila": n, "motivo": str(e)[:200]})
    return r


def _perfil_a_flags(perfil: dict, periodo: str) -> tuple[dict, list[str]]:
    ajustes = {"tributacion_foral": bool(perfil["tributacion_foral"]), "criterio_caja": bool(perfil["criterio_caja"]), "prorrata": bool(perfil["prorrata_especial"] or perfil["sectores_diferenciados"]),
               "prorrata_general": perfil["prorrata_centesimas"] if not (perfil["prorrata_especial"] or perfil["sectores_diferenciados"]) else None,
               "regimen_simplificado": perfil["regimen_iva"] in ("simplificado", "general_y_simplificado"), "recargo_equivalencia": perfil["regimen_iva"] == "recargo"}
    extra = []
    if perfil["regimen_iva"] in ("exento", "otro"):
        extra.append(f"El régimen de IVA del titular ({perfil['regimen_iva']}) no tiene cálculo automático.")
    if perfil["sii"]:
        extra.append("El titular está en el SII: el 303 se calcula con otra información.")
    if perfil["autoliquidacion_conjunta"]:
        extra.append("Autoliquidación conjunta: no soportada.")
    if perfil["territorio_iva"] != "peninsula_baleares":
        extra.append("Territorio de IVA distinto de península y Baleares: no soportado.")
    if (perfil["periodicidad"] == "mensual") != (periodo[-1] != "T"):
        extra.append(f"El periodo {periodo} no corresponde a la periodicidad del titular ({perfil['periodicidad']}).")
    return ajustes, extra


def _fecha_fin_periodo(ejercicio: int, periodo: str) -> date:
    import calendar
    mes = int(periodo[0]) * 3 if periodo.endswith("T") else int(periodo)
    return date(ejercicio, mes, calendar.monthrange(ejercicio, mes)[1])


def _pendientes_anteriores(conn, tenant_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str, perfil: dict) -> int:
    """Cuotas a compensar (casilla 110): lo pendiente de las declaraciones ya REVISADAS (o más) de periodos anteriores del mismo ejercicio; si no hay ninguna, el saldo inicial del perfil."""
    ordenar = lambda p: int(p[0]) * 3 if p.endswith("T") else int(p)        # noqa: E731
    previas = [f for f in conn.execute("SELECT periodo, tipo_declaracion, resultado_centimos, id FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND ejercicio = ? "
                                       "AND estado IN ('revisada','exportada','presentada')", (tenant_id, cliente_fiscal_id, ejercicio)).fetchall() if ordenar(f["periodo"]) < ordenar(periodo)]
    if not previas:
        return max(0, int(perfil["saldo_a_compensar_centimos"] or 0))
    pendiente = int(perfil["saldo_a_compensar_centimos"] or 0)
    ultimas: dict[str, dict] = {}
    for f in sorted(previas, key=lambda x: x["id"]):                         # si un periodo tiene original y rectificativa, vale la última
        ultimas[f["periodo"]] = f
    for f in sorted(ultimas.values(), key=lambda x: ordenar(x["periodo"])):
        casillas = {c["casilla"]: c["valor"] for c in conn.execute("SELECT casilla, valor FROM fiscal_casillas WHERE declaracion_id = ? AND tenant_id = ?", (f["id"], tenant_id)).fetchall()}
        pendiente -= casillas.get("78", 0)
        if f["tipo_declaracion"] == "C" and f["resultado_centimos"] < 0:
            pendiente += -f["resultado_centimos"]
    return max(0, pendiente)


def crear_instantanea(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, *, ejercicio: int, periodo: str, modelo: str = "303", para_rectificar: bool = False) -> dict:
    """Congela el periodo: perfil vigente, apuntes aprobados y reglas. Si ya había una instantánea de ese periodo, la nueva la SUSTITUYE (la anterior queda). Con errores en los datos, no se crea.
    Un periodo cuyo 303 ya se presentó no se vuelve a calcular como si fuera el primero: se rectifica (`para_rectificar`, que solo usa `rectificar_declaracion`)."""
    if modelo != "303":
        raise ErrorFiscal("Solo está soportado el modelo 303.")
    if periodo not in tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T"):
        raise ErrorFiscal("Periodo no válido.")
    _exigir_aprobador(tenant_id, usuario_id)
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    perfil = fiscal_perfiles.perfil_en(tenant_id, cliente_fiscal_id, _fecha_fin_periodo(ejercicio, periodo).isoformat())
    if not perfil:
        raise ErrorFiscal("El titular no tiene perfil fiscal vigente en ese periodo: créalo antes.", "sin_perfil")
    filas = listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id, ejercicio=ejercicio)
    conn = db.get_connection()
    try:
        if not para_rectificar and conn.execute("SELECT 1 FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND ejercicio = ? AND periodo = ? AND estado = 'presentada'",
                                                (tenant_id, cliente_fiscal_id, ejercicio, periodo)).fetchone():
            raise ErrorFiscal("Este periodo ya tiene un 303 presentado: si hay que corregirlo se abre una rectificativa desde esa declaración, no se calcula de nuevo.", "periodo_presentado")
        titular = _titular(conn, tenant_id, cliente_fiscal_id)
        apuntes = [a_apunte(f) for f in filas]
        errores = validacion_apuntes.errores(validacion_apuntes.validar(apuntes, hoy=date.today(), nif_titular=titular["nif"] or ""))
        if errores:
            raise ErrorFiscal("Hay errores en los apuntes: " + " · ".join(e.mensaje for e in errores[:5]), "datos_con_errores", errores=[e.mensaje for e in errores])
        contenido = {
            "formato": 1, "modelo": modelo, "ejercicio": ejercicio, "periodo": periodo, "titular": {"id": titular["id"], "nombre": titular["nombre"], "nif": titular["nif"]},
            "perfil": {k: perfil[k] for k in sorted(perfil) if k not in ("creado_por", "creado_en", "actualizado_en")},
            "apuntes": [{**_datos_de_apunte(a), "apunte_id": f["id"], "version": f["version"], "factura_id": f["factura_id"]} for a, f in zip(apuntes, filas)],
            "cuotas_a_compensar_anteriores": _pendientes_anteriores(conn, tenant_id, cliente_fiscal_id, ejercicio, periodo, perfil),
            "motor": VERSION_MOTOR, "diseno": VERSION_DISENO,
        }
        texto = json.dumps(contenido, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        previa = conn.execute("SELECT id FROM fiscal_instantaneas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = ? AND ejercicio = ? AND periodo = ? ORDER BY id DESC LIMIT 1",
                              (tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo)).fetchone()
        ahora = db.now_iso()
        cur = conn.execute("INSERT INTO fiscal_instantaneas (tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo, hash, contenido, aprobada_por, aprobada_en, sustituye_a_id, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo, hashlib.sha256(texto.encode()).hexdigest(), texto, usuario_id, ahora, previa["id"] if previa else None, ahora))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.instantanea.crear", "cliente_fiscal", cliente_fiscal_id, {"instantanea_id": cur.lastrowid, "modelo": modelo, "ejercicio": ejercicio, "periodo": periodo,
                                                                                                                   "apuntes": len(apuntes)}, conn=conn)
        fila = conn.execute("SELECT * FROM fiscal_instantaneas WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.commit()
        return dict(fila)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def obtener_instantanea(tenant_id: int, usuario_id: int, instantanea_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM fiscal_instantaneas WHERE id = ? AND tenant_id = ?", (instantanea_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if not f:
        raise ErrorFiscal("La instantánea no existe.", "no_encontrado")
    _exigir_acceso(tenant_id, usuario_id, f["cliente_fiscal_id"])
    d = dict(f)
    d["datos"] = json.loads(d["contenido"])
    d["integra"] = hashlib.sha256(d["contenido"].encode()).hexdigest() == d["hash"]
    return d


# --- Declaraciones ------------------------------------------------------------------------------------------------------------------------------
def _vencimiento_del_periodo(conn, tenant_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str) -> int | None:
    """El vencimiento del calendario fiscal que corresponde a este 303 («303» · «2T 2026»), si existe."""
    f = conn.execute("SELECT id FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND periodo = ? AND papelera_en IS NULL ORDER BY id DESC LIMIT 1",
                     (tenant_id, cliente_fiscal_id, f"{periodo} {ejercicio}")).fetchone()
    return f["id"] if f else None


def calcular_declaracion(tenant_id: int, usuario_id: int, instantanea_id: int, *, destino_negativo: str = "C", vencimiento_id: int | None = None, rectifica: dict | None = None) -> dict:
    """Calcula el borrador del 303 SOLO con lo congelado en la instantánea. Un borrador anterior de la misma instantánea se anula (queda en el historial).
    `rectifica` (solo lo pasa `rectificar_declaracion`): `{"original": declaración presentada, "justificante": 13 cifras, "devolucion_acordada": bool}`; el resultado es una autoliquidación rectificativa."""
    _exigir_aprobador(tenant_id, usuario_id)
    inst = obtener_instantanea(tenant_id, usuario_id, instantanea_id)
    if not inst["integra"]:
        raise ErrorFiscal("La instantánea no es íntegra (su huella no coincide): no se calcula sobre ella.", "invalido")
    d = inst["datos"]
    perfil = d["perfil"]
    apuntes = [a_apunte(a) for a in d["apuntes"]]
    ajustes, extra = _perfil_a_flags(perfil, d["periodo"])
    r = motor_303.calcular(apuntes, ejercicio=d["ejercicio"], periodo=d["periodo"], cuotas_a_compensar_anteriores=d["cuotas_a_compensar_anteriores"], destino_negativo=destino_negativo, **ajustes)
    r.bloqueos.extend(extra)
    if rectifica:
        motor_303.aplicar_rectificativa(r, rectifica["original"]["casillas"], devolucion_acordada=rectifica["devolucion_acordada"], destino_negativo=destino_negativo)
    conn = db.get_connection()
    try:
        if vencimiento_id is None and not rectifica:                          # la rectificativa no toca el calendario: el vencimiento ya quedó presentado con la original
            vencimiento_id = _vencimiento_del_periodo(conn, tenant_id, inst["cliente_fiscal_id"], d["ejercicio"], d["periodo"])
        conn.execute("UPDATE fiscal_declaraciones SET estado = 'anulada' WHERE tenant_id = ? AND instantanea_id = ? AND estado = 'borrador'", (tenant_id, instantanea_id))
        cur = conn.execute("INSERT INTO fiscal_declaraciones (tenant_id, cliente_fiscal_id, instantanea_id, vencimiento_id, modelo, ejercicio, periodo, estado, tipo_declaracion, resultado_centimos, version_motor, "
                           "version_diseno, bloqueos, rectifica_a_id, justificante_anterior, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (tenant_id, inst["cliente_fiscal_id"], instantanea_id, vencimiento_id, "303", d["ejercicio"], d["periodo"], "borrador", r.tipo_declaracion, r.casillas.get("71", 0), VERSION_MOTOR,
                            VERSION_DISENO, json.dumps(r.bloqueos, ensure_ascii=False) if r.bloqueos else None, rectifica["original"]["id"] if rectifica else None,
                            rectifica["justificante"] if rectifica else None, usuario_id, db.now_iso()))
        did = cur.lastrowid
        for casilla, valor in sorted(r.casillas.items()):
            conn.execute("INSERT INTO fiscal_casillas (tenant_id, declaracion_id, casilla, valor, origen) VALUES (?,?,?,?,?)",
                         (tenant_id, did, casilla, valor, json.dumps([d["apuntes"][i]["apunte_id"] for i in r.origen.get(casilla, [])]) if casilla in r.origen else None))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.declaracion.calcular", "cliente_fiscal", inst["cliente_fiscal_id"], {"declaracion_id": did, "instantanea_id": instantanea_id, "resultado": r.casillas.get("71", 0),
                                                                                                                     "bloqueos": len(r.bloqueos), "rectifica_a": rectifica["original"]["id"] if rectifica else None}, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obtener_declaracion(tenant_id, usuario_id, did)


def obtener_declaracion(tenant_id: int, usuario_id: int, declaracion_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM fiscal_declaraciones WHERE id = ? AND tenant_id = ?", (declaracion_id, tenant_id)).fetchone()
        if not f:
            raise ErrorFiscal("La declaración no existe.", "no_encontrado")
        _exigir_acceso(tenant_id, usuario_id, f["cliente_fiscal_id"])
        d = dict(f)
        d["casillas"] = {c["casilla"]: c["valor"] for c in conn.execute("SELECT casilla, valor FROM fiscal_casillas WHERE declaracion_id = ? AND tenant_id = ? ORDER BY id", (declaracion_id, tenant_id)).fetchall()}
        d["origen"] = {c["casilla"]: json.loads(c["origen"]) for c in conn.execute("SELECT casilla, origen FROM fiscal_casillas WHERE declaracion_id = ? AND tenant_id = ? AND origen IS NOT NULL",
                                                                                   (declaracion_id, tenant_id)).fetchall()}
        d["bloqueos"] = json.loads(d["bloqueos"]) if d["bloqueos"] else []
        d["artefactos"] = [{"id": a["id"], "tipo": a["tipo"], "hash": a["hash"], "creado_en": a["creado_en"]} for a in
                           conn.execute("SELECT id, tipo, hash, creado_en FROM fiscal_artefactos WHERE declaracion_id = ? AND tenant_id = ? ORDER BY id", (declaracion_id, tenant_id)).fetchall()]
        return d
    finally:
        conn.close()


def rectificar_declaracion(tenant_id: int, usuario_id: int, declaracion_id: int, *, justificante: str, devolucion_acordada: bool = False, destino_negativo: str = "C") -> dict:
    """Abre la autoliquidación RECTIFICATIVA de un 303 ya presentado: congela el periodo otra vez (con los apuntes tal como están ahora) y calcula un 303 completo con las casillas 70, 109 y 111 que piden las
    instrucciones oficiales. Queda en borrador y sigue el mismo camino que cualquier otro (revisar, generar el fichero, anotar que se presentó). Solo la primera rectificativa de cada declaración."""
    _exigir_aprobador(tenant_id, usuario_id)
    original = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    if original["estado"] != "presentada":
        raise ErrorFiscal("Solo se rectifica un 303 que ya se presentó. Si todavía no lo has presentado, anúlalo y calcula el periodo de nuevo.", "estado_invalido")
    if original["rectifica_a_id"]:
        raise ErrorFiscal("Esta declaración ya es una rectificativa: las segundas rectificativas no están soportadas (las instrucciones de la AEAT las tratan con ejemplos aparte).", "no_soportado")
    justificante = (justificante or "").strip() or justificante_de(original) or ""            # si ya se anotó al presentarla, no hace falta teclearlo otra vez
    if not re.fullmatch(r"\d{13}", justificante):
        raise ErrorFiscal("El número de justificante de la declaración presentada tiene 13 cifras: es el que da la AEAT al presentarla.", "invalido")
    conn = db.get_connection()
    try:
        viva = conn.execute("SELECT id FROM fiscal_declaraciones WHERE tenant_id = ? AND rectifica_a_id = ? AND estado != 'anulada'", (tenant_id, declaracion_id)).fetchone()
    finally:
        conn.close()
    if viva:
        raise ErrorFiscal(f"Esta declaración ya tiene una rectificativa (la {viva['id']}): sigue con esa o anúlala antes de abrir otra.", "ya_rectificada")
    inst = crear_instantanea(tenant_id, usuario_id, original["cliente_fiscal_id"], ejercicio=original["ejercicio"], periodo=original["periodo"], para_rectificar=True)
    return calcular_declaracion(tenant_id, usuario_id, inst["id"], destino_negativo=destino_negativo,
                                rectifica={"original": original, "justificante": justificante, "devolucion_acordada": bool(devolucion_acordada)})


def listar_declaraciones(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> list[dict]:
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY ejercicio DESC, periodo DESC, id DESC", (tenant_id, cliente_fiscal_id)).fetchall()]
    finally:
        conn.close()


def _cambiar_estado(tenant_id: int, usuario_id: int, declaracion_id: int, nuevo: str, extra: dict | None = None) -> dict:
    d = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    if nuevo not in TRANSICIONES[d["estado"]]:
        raise ErrorFiscal(f"Una declaración «{d['estado']}» no pasa a «{nuevo}».", "estado_invalido")
    sets, args = ["estado = ?"], [nuevo]
    for k, v in (extra or {}).items():
        sets.append(f"{k} = ?")
        args.append(v)
    conn = db.get_connection()
    try:
        n = conn.execute(f"UPDATE fiscal_declaraciones SET {', '.join(sets)} WHERE id = ? AND tenant_id = ? AND estado = ?", (*args, declaracion_id, tenant_id, d["estado"])).rowcount
        if not n:
            raise ErrorFiscal("La declaración cambió mientras tanto: vuelve a abrirla.", "version_obsoleta")
        auditoria.registrar(tenant_id, usuario_id, f"fiscal.declaracion.{nuevo}", "cliente_fiscal", d["cliente_fiscal_id"], {"declaracion_id": declaracion_id}, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obtener_declaracion(tenant_id, usuario_id, declaracion_id)


def revisar_declaracion(tenant_id: int, usuario_id: int, declaracion_id: int) -> dict:
    """La persona que revisa da el visto bueno al borrador. Con bloqueos en el cálculo no se puede revisar."""
    _exigir_aprobador(tenant_id, usuario_id)
    d = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    if d["bloqueos"]:
        raise ErrorFiscal("El cálculo está bloqueado: " + " · ".join(d["bloqueos"][:3]), "bloqueada")
    return _cambiar_estado(tenant_id, usuario_id, declaracion_id, "revisada", {"revisada_por": usuario_id, "revisada_en": db.now_iso()})


def exportar_declaracion(tenant_id: int, usuario_id: int, declaracion_id: int) -> dict:
    """Genera y guarda el `.303`, el libro `.xlsx` y el resumen legible de una declaración REVISADA. No presenta nada."""
    _exigir_aprobador(tenant_id, usuario_id)
    d = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    if d["estado"] != "revisada":
        raise ErrorFiscal("Solo se exporta una declaración revisada.", "estado_invalido")
    inst = obtener_instantanea(tenant_id, usuario_id, d["instantanea_id"])
    datos = inst["datos"]
    apuntes = [a_apunte(a) for a in datos["apuntes"]]
    exonerado = bool(datos["perfil"].get("exonerado_390")) and d["periodo"] in exportador_303.ULTIMOS
    volumen = motor_390.volumen_anual(apuntes, d["ejercicio"]) if exonerado else None
    if exonerado and datos["perfil"].get("prorrata_centesimas") is not None:
        raise ErrorFiscal("El titular está exonerado del 390 y aplica prorrata: el último periodo lleva la página de prorrata (CNAE, importe y porcentaje por actividad) y todavía no se genera.", "no_soportado")
    problemas = validacion_apuntes.validar(apuntes, hoy=date.today(), nif_titular=datos["titular"]["nif"] or "")
    if necesita_iban(d) and not d.get("iban"):
        raise ErrorFiscal("Esta declaración necesita el IBAN del titular (" + ("devolución" if d["tipo_declaracion"] == "D" else "rectificativa con casilla 111: el diseño oficial exige los datos de la cuenta")
                          + "): anótalo en la declaración antes de generar el fichero.", "iban_necesario")
    resultado = motor_303.Resultado303(d["ejercicio"], d["periodo"], casillas=dict(d["casillas"]), tipo_declaracion=d["tipo_declaracion"])
    try:
        fichero = fichero_303.generar(resultado, nif=(datos["titular"]["nif"] or "").upper(), nombre=datos["titular"]["nombre"], exonerado_390=exonerado, volumen=volumen,
                                      justificante_anterior=d["justificante_anterior"] if d["rectifica_a_id"] else None, criterio_caja=bool(datos["perfil"].get("criterio_caja")),
                                      iban=d.get("iban") or None, actividades=fiscal_perfiles.actividades_de(datos["perfil"]) if exonerado else None)
    except fichero_303.FicheroNoGenerable as e:
        raise ErrorFiscal(str(e), "no_soportado")
    libro = libros_lsi.escribir_xlsx(apuntes, ejercicio=d["ejercicio"], periodo=d["periodo"])
    resumen = _resumen(d, datos).encode("utf-8")
    avisos_pagina_4 = [{"nivel": "aviso", "codigo": "actividad_sin_informar", "mensaje": "El titular está exonerado del 390: la página 4 del 303 lleva la clave de actividad y el epígrafe del IAE, y el perfil no los tiene. "
                        "Complétalos en el formulario o en el perfil fiscal."}] if exonerado and not any(a.get("codigo") for a in fiscal_perfiles.actividades_de(datos["perfil"])) else []
    informe = json.dumps([{"nivel": p.nivel, "codigo": p.codigo, "mensaje": p.mensaje} for p in problemas] + avisos_pagina_4, ensure_ascii=False)
    conn = db.get_connection()
    try:
        for tipo, contenido in (("303", fichero), ("libro_xlsx", libro), ("resumen", resumen)):
            conn.execute("INSERT INTO fiscal_artefactos (tenant_id, declaracion_id, tipo, hash, contenido, informe_validacion, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                         (tenant_id, declaracion_id, tipo, hashlib.sha256(contenido).hexdigest(), contenido, informe, usuario_id, db.now_iso()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _cambiar_estado(tenant_id, usuario_id, declaracion_id, "exportada", {"exportada_en": db.now_iso()})


def _resumen(d: dict, datos: dict) -> str:
    lineas = [f"Modelo 303 · {datos['titular']['nombre']} ({datos['titular']['nif']}) · {d['ejercicio']} {d['periodo']}" + (f" · RECTIFICATIVA de la declaración {d['justificante_anterior']}" if d["rectifica_a_id"] else ""),
              f"Tipo de declaración: {d['tipo_declaracion']} · Resultado (casilla 71): {d['resultado_centimos'] / 100:.2f} €",
              f"Motor {d['version_motor']} · diseño {d['version_diseno']} · instantánea {d['instantanea_id']}", ""]
    for casilla, valor in sorted(d["casillas"].items(), key=lambda x: int(x[0])):
        lineas.append(f"[{casilla}] {valor / 100:.2f}" + (f"  ← apuntes {d['origen'][casilla]}" if casilla in d["origen"] else ""))
    return "\n".join(lineas) + "\n"


def descargar_artefacto(tenant_id: int, usuario_id: int, declaracion_id: int, tipo: str) -> tuple[bytes, str]:
    d = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT contenido, hash FROM fiscal_artefactos WHERE declaracion_id = ? AND tenant_id = ? AND tipo = ? ORDER BY id DESC LIMIT 1", (declaracion_id, tenant_id, tipo)).fetchone()
    finally:
        conn.close()
    if not f:
        raise ErrorFiscal("Ese fichero no existe todavía: exporta la declaración.", "no_encontrado")
    nombre = {"303": f"{d['ejercicio']}_{d['periodo']}.303", "libro_xlsx": f"libro_{d['ejercicio']}_{d['periodo']}.xlsx", "resumen": f"resumen_{d['ejercicio']}_{d['periodo']}.txt"}[tipo]
    contenido = f["contenido"]
    return (bytes(contenido) if not isinstance(contenido, bytes) else contenido), nombre


def necesita_iban(d: dict) -> bool:
    """Una declaración a devolver lleva la cuenta de la devolución; una rectificativa con casilla 111 también (Nota 3 de la página DID del diseño oficial), aunque no sea a devolver."""
    return d["tipo_declaracion"] == "D" or bool(d["casillas"].get("111"))


def guardar_iban(tenant_id: int, usuario_id: int, declaracion_id: int, iban: str) -> dict:
    """Anota (o quita, con texto vacío) el IBAN de la declaración mientras es borrador o está revisada: el fichero ya generado no cambia."""
    _exigir_aprobador(tenant_id, usuario_id)
    d = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    if d["estado"] not in ("borrador", "revisada"):
        raise ErrorFiscal("El IBAN se anota antes de generar el fichero: esta declaración ya está " + d["estado"] + ".", "estado_invalido")
    try:
        limpio = iban_mod.validar(iban) if (iban or "").strip() else None
    except iban_mod.IbanNoValido as e:
        raise ErrorFiscal(str(e), "invalido") from None
    conn = db.get_connection()
    try:
        conn.execute("UPDATE fiscal_declaraciones SET iban = ? WHERE id = ? AND tenant_id = ?", (limpio, declaracion_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.declaracion.iban", "cliente_fiscal", d["cliente_fiscal_id"], {"declaracion_id": declaracion_id, "iban": ("…" + limpio[-4:]) if limpio else None}, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obtener_declaracion(tenant_id, usuario_id, declaracion_id)


def iban_reciente(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> str | None:
    """El último IBAN anotado en una declaración de este titular, para proponerlo en la siguiente."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT iban FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND iban IS NOT NULL AND iban <> '' ORDER BY id DESC LIMIT 1", (tenant_id, cliente_fiscal_id)).fetchone()
    finally:
        conn.close()
    return f["iban"] if f else None


def justificante_de(declaracion: dict) -> str | None:
    """El número de justificante (13 cifras) anotado en una declaración presentada, si lo hay."""
    m = re.search(r"(?<!\d)\d{13}(?!\d)", declaracion.get("referencia_presentacion") or "")
    return m.group(0) if m else None


def _referencia_de_presentacion(tenant_id: int, declaracion_id: int, referencia: str, justificante: str, csv: str) -> str | None:
    """El texto que se guarda: «justificante 3030000000123 · CSV ABC…»; con solo `referencia` libre (formato antiguo) se guarda tal cual. El justificante tiene 13 cifras y no puede estar ya en otra declaración."""
    justificante, csv = (justificante or "").strip(), re.sub(r"\s+", "", csv or "").upper()
    if not justificante and not csv:
        return (referencia or "").strip()[:200] or None
    if justificante:
        if not re.fullmatch(r"\d{13}", justificante):
            raise ErrorFiscal("El número de justificante tiene 13 cifras: es el que da la AEAT al presentar.")
        conn = db.get_connection()
        try:
            otra = conn.execute("SELECT id FROM fiscal_declaraciones WHERE tenant_id = ? AND id <> ? AND LOWER(referencia_presentacion) LIKE LOWER(?)", (tenant_id, declaracion_id, f"%{justificante}%")).fetchone()
        finally:
            conn.close()
        if otra:
            raise ErrorFiscal(f"Ese justificante ya está anotado en la declaración {otra['id']}.")
    if csv and not re.fullmatch(r"[A-Z0-9]{8,40}", csv):
        raise ErrorFiscal("El CSV (código seguro de verificación) son letras y números, sin espacios.")
    return " · ".join(p for p in (f"justificante {justificante}" if justificante else "", f"CSV {csv}" if csv else "") if p)


def anotar_justificante(tenant_id: int, usuario_id: int, declaracion_id: int, *, justificante: str = "", csv: str = "") -> dict:
    """Completa el justificante o el CSV de una declaración YA presentada (por ejemplo, una que se anotó solo con el CSV): hace falta el justificante para poder rectificarla."""
    _exigir_aprobador(tenant_id, usuario_id)
    d = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    if d["estado"] != "presentada":
        raise ErrorFiscal("Solo se anota el justificante de una declaración presentada.", "estado_invalido")
    if not (justificante or "").strip() and not (csv or "").strip():
        raise ErrorFiscal("Indica el justificante o el CSV.")
    previa = (d["referencia_presentacion"] or "").strip()
    nueva = _referencia_de_presentacion(tenant_id, declaracion_id, "", justificante or justificante_de(d) or "", csv)
    if not nueva:
        raise ErrorFiscal("Indica el justificante o el CSV.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE fiscal_declaraciones SET referencia_presentacion = ? WHERE id = ? AND tenant_id = ?", (nueva, declaracion_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "fiscal.declaracion.justificante", "cliente_fiscal", d["cliente_fiscal_id"], {"declaracion_id": declaracion_id, "antes": previa[:80], "despues": nueva[:80]}, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obtener_declaracion(tenant_id, usuario_id, declaracion_id)


def marcar_presentada(tenant_id: int, usuario_id: int, declaracion_id: int, referencia: str = "", *, justificante: str = "", csv: str = "") -> dict:
    """Anota que el cliente o su colaborador social presentó el fichero, con el número de justificante (13 cifras) y/o el CSV si se tienen (o una `referencia` libre, formato antiguo). Guilda Work no presenta."""
    _exigir_aprobador(tenant_id, usuario_id)
    texto = _referencia_de_presentacion(tenant_id, declaracion_id, referencia, justificante, csv)
    d = _cambiar_estado(tenant_id, usuario_id, declaracion_id, "presentada", {"presentada_en": db.now_iso(), "referencia_presentacion": texto})
    if d["vencimiento_id"]:                                                       # el calendario fiscal se entera: el vencimiento queda presentado
        db.marcar_presentado_vencimiento_fiscal(tenant_id, d["vencimiento_id"], usuario_id)
    return d


def anular_declaracion(tenant_id: int, usuario_id: int, declaracion_id: int) -> dict:
    _exigir_aprobador(tenant_id, usuario_id)
    return _cambiar_estado(tenant_id, usuario_id, declaracion_id, "anulada")


def uso_para_backoffice(tenant_id: int) -> list[tuple[str, str]]:
    """Lo que ha hecho este despacho este mes en Guilda Fiscal (el backoffice lo enseña y es la base del cobro por uso)."""
    mes = date.today().isoformat()[:7]
    conn = db.get_connection()
    try:
        apuntes = conn.execute("SELECT count(*) FROM fiscal_apuntes WHERE tenant_id = ? AND substr(aprobado_en, 1, 7) = ?", (tenant_id, mes)).fetchone()[0]
        instantaneas = conn.execute("SELECT count(*) FROM fiscal_instantaneas WHERE tenant_id = ? AND substr(aprobada_en, 1, 7) = ?", (tenant_id, mes)).fetchone()[0]
        exportadas = conn.execute("SELECT count(*) FROM fiscal_declaraciones WHERE tenant_id = ? AND substr(exportada_en, 1, 7) = ?", (tenant_id, mes)).fetchone()[0]
        presentadas = conn.execute("SELECT count(*) FROM fiscal_declaraciones WHERE tenant_id = ? AND substr(presentada_en, 1, 7) = ?", (tenant_id, mes)).fetchone()[0]
        titulares = conn.execute("SELECT count(DISTINCT cliente_fiscal_id) FROM fiscal_perfiles WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
    finally:
        conn.close()
    return [("Mes", mes), ("Titulares con perfil fiscal", str(titulares)), ("Apuntes aprobados", str(apuntes)), ("Periodos congelados", str(instantaneas)), ("Declaraciones exportadas", str(exportadas)),
            ("Declaraciones presentadas", str(presentadas))]


def _registrar() -> None:
    """El vertical «fiscal» (alta en fiscal_perfiles) pasa a crear y borrar también las tablas del núcleo."""
    from dataclasses import replace
    from . import verticales
    base = verticales.VERTICALES["fiscal"]
    previo_esquema, previo_borrar = base.esquema, base.borrar_datos

    def esquema(conn):
        previo_esquema(conn)
        crear_esquema(conn)

    def borrar(conn, tenant_id):
        borrar_datos_de_tenant(conn, tenant_id)               # primero lo inmutable y lo que cuelga de los perfiles, luego los perfiles
        previo_borrar(conn, tenant_id)

    verticales.registrar(replace(base, esquema=esquema, borrar_datos=borrar, uso=uso_para_backoffice, disponible=True))


_registrar()


# --- Para las pantallas -------------------------------------------------------------------------------------------------------------------------
_ETIQUETAS: dict[str, str] = {}


def etiqueta_casilla(casilla: str) -> str:
    """Nombre legible de una casilla, sacado del diseño oficial («IVA Devengado · Régimen general · Base imponible»)."""
    if not _ETIQUETAS:
        import re
        diseno = json.loads(exportador_303.DISENO_303_2026.read_text(encoding="utf-8"))
        from .fiscal_modelos.disenos_oficiales import indice_casillas
        for k, apariciones in indice_casillas(diseno).items():
            texto = re.sub(r"\s*\[\d+\]\s*\.?\s*$", "", apariciones[0]["descripcion"])
            texto = re.sub(r"\(\s*\[.*$", "", texto).strip()
            partes = [p.strip() for p in texto.split(" - ") if p.strip() and not p.strip().startswith("Liquidación")]
            _ETIQUETAS[k] = " · ".join(partes[-3:]) if partes else texto
    return _ETIQUETAS.get(casilla, "")


def periodo_por_defecto(hoy: date) -> tuple[int, str]:
    """El último trimestre ya terminado (el que se declara ahora): en el 4T de 2026 es el 3T de 2026; en el 1T de 2027, el 4T de 2026."""
    trimestre = (hoy.month - 1) // 3 + 1
    return (hoy.year, f"{trimestre - 1}T") if trimestre > 1 else (hoy.year - 1, "4T")


def comparar_con_anterior(tenant_id: int, usuario_id: int, declaracion_id: int) -> dict | None:
    """Qué casillas cambian respecto al cálculo anterior del MISMO periodo y titular (al volver a calcular tras corregir un apunte). None si no hay cálculo anterior."""
    d = obtener_declaracion(tenant_id, usuario_id, declaracion_id)
    conn = db.get_connection()
    try:
        if d["rectifica_a_id"]:                                               # una rectificativa se compara con la declaración que rectifica, no con borradores intermedios
            ant = conn.execute("SELECT id, estado, resultado_centimos FROM fiscal_declaraciones WHERE id = ? AND tenant_id = ?", (d["rectifica_a_id"], tenant_id)).fetchone()
        else:
            ant = conn.execute("SELECT id, estado, resultado_centimos FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND ejercicio = ? AND periodo = ? AND id < ? ORDER BY id DESC LIMIT 1",
                               (tenant_id, d["cliente_fiscal_id"], d["ejercicio"], d["periodo"], declaracion_id)).fetchone()
        if not ant:
            return None
        antes = {c["casilla"]: c["valor"] for c in conn.execute("SELECT casilla, valor FROM fiscal_casillas WHERE declaracion_id = ? AND tenant_id = ?", (ant["id"], tenant_id)).fetchall()}
    finally:
        conn.close()
    ahora = d["casillas"]
    cambios = [{"casilla": k, "antes": antes.get(k, 0), "ahora": ahora.get(k, 0)} for k in sorted(set(antes) | set(ahora)) if antes.get(k, 0) != ahora.get(k, 0) and k not in ("02", "05", "08")]
    return {"id": ant["id"], "estado": ant["estado"], "cambios": cambios, "resultado_antes": ant["resultado_centimos"], "resultado_ahora": d["resultado_centimos"]}


def pendiente_de_recordar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str) -> dict:
    """Lo que falta para cerrar un periodo de un titular (base del mensaje de recordatorio al cliente): facturas revisadas sin registrar, apuntes por libro y fecha límite del 303."""
    _exigir_acceso(tenant_id, usuario_id, cliente_fiscal_id)
    apuntes = [a for a in listar_apuntes(tenant_id, usuario_id, cliente_fiscal_id, ejercicio=ejercicio) if motor_303_en_periodo(a["fecha_expedicion"], ejercicio, periodo)]
    sin_registrar = [f for f in facturas_por_registrar(tenant_id, usuario_id, cliente_fiscal_id, ejercicio) if motor_303_en_periodo(f["fecha"], ejercicio, periodo)]
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT fecha_limite FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND periodo = ? AND papelera_en IS NULL ORDER BY id DESC LIMIT 1",
                         (tenant_id, cliente_fiscal_id, f"{periodo} {ejercicio}")).fetchone()
    finally:
        conn.close()
    return {"emitidas": sum(1 for a in apuntes if a["libro"] == "E"), "recibidas": sum(1 for a in apuntes if a["libro"] == "R"), "sin_registrar": sin_registrar, "fecha_limite": (v["fecha_limite"][:10] if v else None)}


def motor_303_en_periodo(fecha: str, ejercicio: int, periodo: str) -> bool:
    from .fiscal_modelos.apuntes import en_periodo
    return en_periodo(date.fromisoformat(fecha[:10]), ejercicio, periodo)


def _semaforo(c: dict, periodo: tuple[int, str]) -> dict:
    """Una frase y un nivel por titular, mirando el periodo que toca declarar ahora: rojo = hay que actuar, ámbar = en curso, verde = hecho, gris = nada que hacer."""
    if not c["perfil"]:
        return {"nivel": "rojo", "clave": "sin_perfil"}
    d = next((x for x in reversed(c["declaraciones_periodo"]) if x["estado"] != "anulada"), None)
    if d is None:
        return {"nivel": "rojo" if c["apuntes"] else "gris", "clave": "por_calcular" if c["apuntes"] else "sin_apuntes"}
    return {"nivel": {"borrador": "ambar", "revisada": "ambar", "exportada": "ambar", "presentada": "verde"}[d["estado"]],
            "clave": {"borrador": "borrador", "revisada": "revisada", "exportada": "pendiente_presentar", "presentada": "presentada"}[d["estado"]]}


def contadores_facturas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None) -> dict[int, dict]:
    """Por titular: facturas que cuentan para Guilda Fiscal y aún no tienen apunte, separadas en «sin_revisar» (pendientes en Facturas para contabilizar) y «por_registrar» (ya revisadas).
    Solo las del ejercicio que se declara y posteriores; las marcadas como «solo contabilidad» no cuentan."""
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    desde = f"{periodo_por_defecto(date.today())[0]}-01-01"
    args: list = [tenant_id, desde]
    if cliente_fiscal_id is None:
        sql = ("SELECT f.cliente_fiscal_id, f.estado, count(*) AS n FROM facturas_contables f LEFT JOIN fiscal_apuntes a ON a.tenant_id = f.tenant_id AND a.factura_id = f.id AND a.anulado_en IS NULL "
               "WHERE f.tenant_id = ? AND f.incluir_en_fiscal = 1 AND f.estado IN ('pendiente', 'revisada', 'exportada') AND f.fecha >= ? AND a.id IS NULL GROUP BY f.cliente_fiscal_id, f.estado")
    else:
        sql = ("SELECT f.cliente_fiscal_id, f.estado, count(*) AS n FROM facturas_contables f LEFT JOIN fiscal_apuntes a ON a.tenant_id = f.tenant_id AND a.factura_id = f.id AND a.anulado_en IS NULL "
               "WHERE f.tenant_id = ? AND f.incluir_en_fiscal = 1 AND f.estado IN ('pendiente', 'revisada', 'exportada') AND f.fecha >= ? AND a.id IS NULL AND f.cliente_fiscal_id = ? "
               "GROUP BY f.cliente_fiscal_id, f.estado")
        args.append(cliente_fiscal_id)
    conn = db.get_connection()
    try:
        filas = conn.execute(sql, tuple(args)).fetchall()
    except Exception:                                                              # noqa: BLE001 — sin la columna o sin la tabla de apuntes (despacho sin los dos módulos): no hay nada que contar
        conn.rollback()
        return {}
    finally:
        conn.close()
    salida: dict[int, dict] = {}
    for fila in filas:
        if visibles is not None and fila["cliente_fiscal_id"] not in visibles:
            continue
        c = salida.setdefault(fila["cliente_fiscal_id"], {"sin_revisar": 0, "por_registrar": 0})
        c["sin_revisar" if fila["estado"] == "pendiente" else "por_registrar"] += fila["n"]
    return salida


def resumen_cartera(tenant_id: int, usuario_id: int) -> list[dict]:
    """Una fila por titular que la persona ve: si tiene perfil fiscal, cuántos apuntes del ejercicio y su última declaración."""
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    hoy = date.today().isoformat()
    conn = db.get_connection()
    try:
        clientes = [dict(f) for f in conn.execute("SELECT id, nombre, nif FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY nombre", (tenant_id,)).fetchall()]
        perfiles = {f["cliente_fiscal_id"]: f for f in conn.execute("SELECT cliente_fiscal_id, regimen_iva, periodicidad FROM fiscal_perfiles WHERE tenant_id = ? AND vigente_desde <= ? AND "
                                                                    "COALESCE(vigente_hasta, '9999-12-31') >= ?", (tenant_id, hoy, hoy)).fetchall()}
        apuntes = {f["cliente_fiscal_id"]: f["n"] for f in conn.execute("SELECT cliente_fiscal_id, count(*) AS n FROM fiscal_apuntes WHERE tenant_id = ? AND anulado_en IS NULL AND substr(fecha_expedicion, 1, 4) = ? "
                                                                       "GROUP BY cliente_fiscal_id", (tenant_id, hoy[:4])).fetchall()}
        proximos: dict[int, dict] = {}
        for f in conn.execute("SELECT cliente_fiscal_id, periodo, fecha_limite, estado FROM vencimientos_fiscales WHERE tenant_id = ? AND modelo = '303' AND estado <> 'presentado' AND papelera_en IS NULL "
                              "ORDER BY fecha_limite", (tenant_id,)).fetchall():
            proximos.setdefault(f["cliente_fiscal_id"], dict(f))
        ultimas: dict[int, dict] = {}
        por_periodo: dict[int, list] = {}
        periodo = periodo_por_defecto(date.today())
        for f in conn.execute("SELECT id, cliente_fiscal_id, ejercicio, periodo, estado, resultado_centimos FROM fiscal_declaraciones WHERE tenant_id = ? ORDER BY ejercicio, periodo, id",
                              (tenant_id,)).fetchall():
            if f["estado"] != "anulada":
                ultimas[f["cliente_fiscal_id"]] = dict(f)
            if (f["ejercicio"], f["periodo"]) == periodo:
                por_periodo.setdefault(f["cliente_fiscal_id"], []).append(dict(f))
    finally:
        conn.close()
    salida = []
    facturas = contadores_facturas(tenant_id, usuario_id)
    for c in clientes:
        if visibles is not None and c["id"] not in visibles:
            continue
        p = perfiles.get(c["id"])
        fila = {**c, "perfil": dict(p) if p else None, "apuntes": apuntes.get(c["id"], 0), "ultima": ultimas.get(c["id"]), "proximo_303": proximos.get(c["id"]),
                "declaraciones_periodo": por_periodo.get(c["id"], []), "facturas": facturas.get(c["id"], {"sin_revisar": 0, "por_registrar": 0})}
        fila["semaforo"] = _semaforo(fila, periodo)
        salida.append(fila)
    return salida
