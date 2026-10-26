"""Consultas de Guilda Fiscal que comparten la API REST (app/rutas_api_guilda_fiscal.py) y las herramientas MCP y del asistente de IA (mcp_tools/herramientas_guilda_fiscal.py).

SOLO LEEN Y SIMULAN: nada de aquí aprueba un apunte, congela un periodo, revisa, exporta ni marca como presentada una declaración. Eso lo hace una persona con rol de dirección o revisor fiscal desde las pantallas
(decisión del módulo: ni la IA ni las integraciones aprueban). La simulación del 303 usa los apuntes YA aprobados y no se guarda: no es una declaración. Los importes salen en euros."""
from __future__ import annotations

from datetime import date

from . import acceso, db, fiscal_nucleo as fn, fiscal_perfiles as fp, verticales
from .fiscal_modelos import motor_303, validacion_apuntes
from .fiscal_perfiles import ErrorFiscal


def _exigir_modulo(tenant_id: int) -> None:
    if tenant_id is None or not verticales.esta_activo(tenant_id, "fiscal"):
        raise ErrorFiscal("El módulo Guilda Fiscal no está activo en este despacho.", "no_encontrado")


def _euros(centimos):
    return None if centimos is None else round(centimos / 100, 2)


def _apunte(f: dict) -> dict:
    return {"id": f["id"], "libro": "emitidas" if f["libro"] == "E" else "recibidas", "tipo_factura": f["tipo_factura"], "clave": f["clave"], "calificacion": f["calificacion"] or None, "exenta": f["exenta"] or None,
            "numero": f"{f['serie']}{f['numero']}", "fecha_expedicion": f["fecha_expedicion"], "fecha_operacion": f["fecha_operacion"], "fecha_recepcion": f["fecha_recepcion"],
            "contraparte": f["contraparte_nombre"], "nif": f["contraparte_nif"], "base": _euros(f["base_centimos"]), "tipo_iva": f["tipo_iva_centesimas"] / 100, "cuota": _euros(f["cuota_centimos"]),
            "cuota_deducible": _euros(f["cuota_deducible_centimos"]), "factura_id": f["factura_id"], "version": f["version"], "aprobado_en": f["aprobado_en"], "anulado": bool(f["anulado_en"])}


def titulares(tenant_id: int, usuario_id: int) -> list[dict]:
    """Los titulares que la persona ve, con su perfil fiscal, apuntes del año y última declaración."""
    _exigir_modulo(tenant_id)
    salida = []
    for f in fn.resumen_cartera(tenant_id, usuario_id):
        u = f["ultima"]
        salida.append({"cliente_fiscal_id": f["id"], "nombre": f["nombre"], "nif": f["nif"], "perfil": ({"regimen_iva": f["perfil"]["regimen_iva"], "periodicidad": f["perfil"]["periodicidad"]} if f["perfil"] else None),
                       "apuntes_del_anio": f["apuntes"], "ultima_declaracion": ({"id": u["id"], "ejercicio": u["ejercicio"], "periodo": u["periodo"], "estado": u["estado"], "resultado": _euros(u["resultado_centimos"])}
                                                                                if u else None)})
    return salida


def perfil(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, fecha: str | None = None) -> dict:
    """El perfil fiscal vigente de un titular (en `fecha`, por defecto hoy) y su historial de vigencias."""
    _exigir_modulo(tenant_id)
    fn._exigir_acceso(tenant_id, usuario_id, int(cliente_fiscal_id))
    p = fp.perfil_en(tenant_id, int(cliente_fiscal_id), fecha or date.today().isoformat())
    quitar = ("tenant_id", "creado_por", "creado_en", "actualizado_en")
    return {"vigente": {k: v for k, v in p.items() if k not in quitar} if p else None, "historial": [{"desde": x["vigente_desde"], "hasta": x["vigente_hasta"], "regimen_iva": x["regimen_iva"],
                                                                                                    "periodicidad": x["periodicidad"]} for x in fp.perfiles_de(tenant_id, int(cliente_fiscal_id))]}


def apuntes(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int | None = None) -> list[dict]:
    """Los apuntes APROBADOS (los que cuentan para el 303) de un titular y ejercicio."""
    _exigir_modulo(tenant_id)
    return [_apunte(f) for f in fn.listar_apuntes(tenant_id, usuario_id, int(cliente_fiscal_id), ejercicio=int(ejercicio) if ejercicio else None)]


def proponer(tenant_id: int, usuario_id: int, factura_id: int) -> list[dict]:
    """Cómo se podría registrar una factura ya anotada (Facturas para contabilizar) como apuntes fiscales. Es solo una propuesta: no guarda nada y la aprobación es de una persona."""
    _exigir_modulo(tenant_id)
    return [{**p, "base": _euros(p.pop("base_centimos")), "cuota": _euros(p.pop("cuota_centimos")), "tipo_iva": p.pop("tipo_iva_centesimas") / 100, "total_centimos": None} for p in fn.proponer_desde_factura(tenant_id, usuario_id, int(factura_id))]


def comprobar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int) -> dict:
    """Pasa a los apuntes aprobados las mismas reglas que aplica la AEAT al importar libros: errores (la AEAT los rechazaría) y avisos."""
    _exigir_modulo(tenant_id)
    if not ejercicio:
        raise ErrorFiscal("Indica el ejercicio.")
    filas = fn.listar_apuntes(tenant_id, usuario_id, int(cliente_fiscal_id), ejercicio=int(ejercicio))
    conn = db.get_connection()
    try:
        titular = conn.execute("SELECT nif FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (int(cliente_fiscal_id), tenant_id)).fetchone()
    finally:
        conn.close()
    problemas = validacion_apuntes.validar([fn.a_apunte(f) for f in filas], hoy=date.today(), nif_titular=(titular["nif"] if titular else "") or "")
    return {"apuntes": len(filas), "ok": not validacion_apuntes.errores(problemas), "problemas": [{"nivel": p.nivel, "codigo": p.codigo, "mensaje": p.mensaje, "apunte_id": filas[p.indice]["id"] if p.indice is not None else None}
                                                                                                     for p in problemas]}


def simular_303(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, ejercicio: int, periodo: str) -> dict:
    """SIMULA el modelo 303 con los apuntes aprobados y el perfil vigente. NO guarda nada ni es una declaración: la declaración se crea desde la pantalla, congelando el periodo. Si el caso no está soportado,
    lo dice en `bloqueos` en vez de dar un número."""
    _exigir_modulo(tenant_id)
    fn._exigir_acceso(tenant_id, usuario_id, int(cliente_fiscal_id))
    p = fp.perfil_en(tenant_id, int(cliente_fiscal_id), fn._fecha_fin_periodo(int(ejercicio), periodo).isoformat())
    if not p:
        raise ErrorFiscal("El titular no tiene perfil fiscal vigente en ese periodo.", "sin_perfil")
    filas = fn.listar_apuntes(tenant_id, usuario_id, int(cliente_fiscal_id), ejercicio=int(ejercicio))
    ajustes, extra = fn._perfil_a_flags(p, periodo)
    try:
        r = motor_303.calcular([fn.a_apunte(f) for f in filas], ejercicio=int(ejercicio), periodo=periodo, cuotas_a_compensar_anteriores=int(p["saldo_a_compensar_centimos"] or 0), **ajustes)
    except motor_303.ErrorDeCalculo as e:
        raise ErrorFiscal(str(e)) from None
    r.bloqueos.extend(extra)
    return {"simulacion": True, "ejercicio": int(ejercicio), "periodo": periodo, "bloqueos": r.bloqueos, "tipo_declaracion": r.tipo_declaracion, "resultado": _euros(r.casillas.get("71", 0)),
            "casillas": {k: (v / 100 if k != "65" else v / 100) for k, v in sorted(r.casillas.items(), key=lambda x: int(x[0])) if k not in ("02", "05", "08")} if r.calculable else {},
            "aviso": "Simulación con los datos de hoy: no es una declaración. Para declarar, la dirección o el revisor fiscal congela el periodo desde la pantalla."}


def declaraciones(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> list[dict]:
    _exigir_modulo(tenant_id)
    return [{"id": d["id"], "modelo": d["modelo"], "ejercicio": d["ejercicio"], "periodo": d["periodo"], "estado": d["estado"], "tipo_declaracion": d["tipo_declaracion"], "resultado": _euros(d["resultado_centimos"]),
             "presentada_en": d["presentada_en"]} for d in fn.listar_declaraciones(tenant_id, usuario_id, int(cliente_fiscal_id))]


def declaracion(tenant_id: int, usuario_id: int, declaracion_id: int) -> dict:
    """Una declaración con sus casillas, de qué apuntes sale cada una, bloqueos y ficheros generados (los ficheros se descargan desde la pantalla)."""
    _exigir_modulo(tenant_id)
    d = fn.obtener_declaracion(tenant_id, usuario_id, int(declaracion_id))
    return {"id": d["id"], "cliente_fiscal_id": d["cliente_fiscal_id"], "modelo": d["modelo"], "ejercicio": d["ejercicio"], "periodo": d["periodo"], "estado": d["estado"], "tipo_declaracion": d["tipo_declaracion"],
            "resultado": _euros(d["resultado_centimos"]), "instantanea_id": d["instantanea_id"], "bloqueos": d["bloqueos"], "version_motor": d["version_motor"], "version_diseno": d["version_diseno"],
            "casillas": {k: v / 100 for k, v in sorted(d["casillas"].items(), key=lambda x: int(x[0])) if k not in ("02", "05", "08")}, "origen": d["origen"], "ficheros": [a["tipo"] for a in d["artefactos"]],
            "presentada_en": d["presentada_en"], "referencia_presentacion": d["referencia_presentacion"]}
