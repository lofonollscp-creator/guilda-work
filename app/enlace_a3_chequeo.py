"""Pre-chequeo de un SUENLACE.DAT antes de llevarlo a a3: se vuelve a leer el fichero **por sus posiciones** (sin pasar por el generador) y se comprueba lo que a3 comprobaría en su botón «Chequeo» y algo más:
estructura de registros de 512 bytes, orden cabecera → detalles → ampliación, fechas, importes, cuentas, cuadre de IVA y totales, números repetidos y NIF.

No sustituye al chequeo de a3 (que conoce el plan de cuentas de la empresa): lo que hace es encontrar aquí, y con el número de registro, los fallos que de otro modo salen allí. Cada problema es un *error*
(a3 lo rechazaría o el asiento saldría mal) o un *aviso* (probablemente bien, pero conviene mirarlo). No toca la base de datos."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal

from . import enlace_a3

LONG_REGISTRO = enlace_a3.LONGITUD + 2
TOLERANCIA_CENTIMOS = 2
_IMPORTE = re.compile(r"^[+-]\d{10}\.\d{2}$")
_PORCENTAJE = re.compile(r"^\d{2}\.\d{2}$")
_CAMPOS_ACEPTADOS = "".join(chr(c) for c in range(32, 127)) + "ÁÉÍÓÚÜÑáéíóúüñÇçº¿¡·ª"


def _c(r: str, ini: int, fin: int) -> str:
    """Posiciones `ini` a `fin` (1 a 512, como en el documento de a3)."""
    return r[ini - 1:fin]


def _fecha(texto: str) -> datetime | None:
    try:
        return datetime.strptime(texto, "%Y%m%d") if re.fullmatch(r"\d{8}", texto) else None
    except ValueError:
        return None


def _importe(texto: str) -> int | None:
    return int(Decimal(texto) * 100) if _IMPORTE.match(texto) else None


def _porcentaje(texto: str) -> int | None:
    return int(Decimal(texto) * 100) if _PORCENTAJE.match(texto) else None


class _Informe:
    def __init__(self) -> None:
        self.errores: list[dict] = []
        self.avisos: list[dict] = []

    def error(self, registro: int | None, mensaje: str) -> None:
        self.errores.append({"registro": registro, "mensaje": mensaje})

    def aviso(self, registro: int | None, mensaje: str) -> None:
        self.avisos.append({"registro": registro, "mensaje": mensaje})


def chequear(contenido: bytes, digitos: int = 8) -> dict:
    """Revisa el contenido de un SUENLACE.DAT. Devuelve `{ok, registros, facturas, errores, avisos, totales}`; `errores` y `avisos` son listas de `{registro, mensaje}` (registro 1 = el primero)."""
    inf = _Informe()
    if not contenido:
        inf.error(None, "El fichero está vacío.")
        return _resultado(inf, 0, [], {})
    if len(contenido) % LONG_REGISTRO:
        inf.error(None, f"El tamaño ({len(contenido)} bytes) no es múltiplo de {LONG_REGISTRO}: los registros de a3 son de 512 bytes (510 caracteres más CR LF).")
    try:
        texto = contenido.decode("latin-1")
    except UnicodeDecodeError:       # no puede pasar con latin-1, por si acaso
        inf.error(None, "El fichero no está en ASCII/Latin-1.")
        return _resultado(inf, 0, [], {})
    registros = [texto[i:i + LONG_REGISTRO] for i in range(0, len(texto), LONG_REGISTRO)]
    facturas: list[dict] = []
    actual: dict | None = None
    empresas, vistos = set(), {}
    for n, r in enumerate(registros, start=1):
        if len(r) != LONG_REGISTRO or not r.endswith("\r\n"):
            inf.error(n, "El registro no mide 512 bytes o no acaba en CR LF.")
            continue
        r = r[:enlace_a3.LONGITUD]
        if _c(r, 1, 1) != "5":
            inf.error(n, f"La posición 1 debe ser «5» y es «{_c(r, 1, 1)}».")
            continue
        raros = sorted({ch for ch in r if ch not in _CAMPOS_ACEPTADOS})
        if raros:
            inf.aviso(n, "Caracteres poco habituales que a3 podría no aceptar: " + "".join(raros)[:20])
        if not re.fullmatch(r"\d{5}", _c(r, 2, 6)):
            inf.error(n, "El código de empresa (posiciones 2-6) debe ser de 5 dígitos.")
        else:
            empresas.add(_c(r, 2, 6))
        fecha = _fecha(_c(r, 7, 14))
        if fecha is None:
            inf.error(n, f"La fecha del registro (7-14) no es válida: «{_c(r, 7, 14)}».")
        if _c(r, 15, 15) != "4" and _c(r, 509, 509) != "E":         # la ampliación de rectificativa (tipo 4) no lleva moneda
            inf.error(n, "La posición 509 (moneda) debe ser «E» (euros).")
        if _c(r, 510, 510) not in ("N", "S"):
            inf.error(n, "La posición 510 (generado/ya contabilizado) debe ser «N» o «S».")
        tipo = _c(r, 15, 15)
        if tipo in ("1", "2"):
            actual = _cabecera(inf, n, r, tipo, fecha, digitos)
            facturas.append(actual)
            clave = (actual["tipo_factura"], actual["numero_completo"], actual["nif"])
            if clave in vistos:
                inf.error(n, f"La factura {actual['numero_completo']} ya está en el registro {vistos[clave]}: está repetida.")
            vistos.setdefault(clave, n)
        elif tipo == "9":
            if actual is None or actual["cerrada"]:
                inf.error(n, "Un detalle de IVA (tipo 9) tiene que ir después de la cabecera de su factura.")
            else:
                _detalle(inf, n, r, actual, digitos)
        elif tipo == "4":
            if actual is None or not actual["detalles"]:
                inf.error(n, "La ampliación (tipo 4) tiene que ir después de los detalles de una factura.")
            else:
                _ampliacion(inf, n, r, actual)
        else:
            inf.error(n, f"Tipo de registro desconocido en la posición 15: «{tipo}».")
    for f in facturas:
        _cerrar(inf, f)
    if len(empresas) > 1:
        inf.aviso(None, "El fichero mezcla varios códigos de empresa: " + ", ".join(sorted(empresas)) + ". a3 importa a la empresa abierta.")
    años = {f["fecha"].year for f in facturas if f["fecha"]}
    if len(años) > 1:
        inf.aviso(None, "Hay facturas de varios ejercicios: " + ", ".join(str(a) for a in sorted(años)) + ". a3 las asienta en el ejercicio de cada fecha.")
    hoy = datetime.now()
    for f in facturas:
        if f["fecha"] and (f["fecha"] > hoy + timedelta(days=365) or f["fecha"].year < hoy.year - 6):
            inf.aviso(f["registro"], f"La fecha {f['fecha']:%d/%m/%Y} de la factura {f['numero_completo']} es muy lejana: ¿es correcta?")
    return _resultado(inf, len(registros), facturas, {})


def _cabecera(inf: _Informe, n: int, r: str, tipo: str, fecha: datetime | None, digitos: int) -> dict:
    cuenta = _c(r, 16, 27)
    if not re.fullmatch(r"\d{12}", cuenta):
        inf.error(n, f"La subcuenta del tercero (16-27) debe tener 12 dígitos y es «{cuenta}».")
    elif cuenta[digitos:].strip("0"):
        inf.error(n, f"La subcuenta {cuenta[:digitos]}… tiene más de {digitos} dígitos significativos.")
    elif not cuenta[:digitos].strip("0"):
        inf.error(n, "La subcuenta del tercero está a cero.")
    tipo_factura = _c(r, 58, 58)
    if tipo_factura not in ("1", "2"):
        inf.error(n, f"El tipo de factura (58) debe ser 1 (emitida) o 2 (recibida) y es «{tipo_factura}».")
    numero = _c(r, 59, 68).strip()
    ampliado = _c(r, 253, 312).strip()
    if not numero:
        inf.error(n, "Falta el número de factura (59-68).")
    elif ampliado and not ampliado.endswith(numero):
        inf.error(n, f"El número corto «{numero}» no es el final del número ampliado «{ampliado}».")
    total = _importe(_c(r, 100, 113))
    if total is None:
        inf.error(n, f"El importe total (100-113) no tiene el formato +0000000000.00: «{_c(r, 100, 113)}».")
    nif = re.sub(r"[\s.\-]", "", _c(r, 176, 189)).upper()
    if not nif:
        inf.aviso(n, "La factura no lleva NIF: a3 la admitirá, pero no entrará en los modelos 347/349 ni en el SII.")
    else:
        from . import fiscal_identidad
        if not fiscal_identidad.clave_unica(nif, "ES") and re.fullmatch(r"[A-Z0-9]+", nif) and _c(r, 374, 375) == "ES":
            inf.aviso(n, f"El NIF «{nif}» no pasa la validación de dígito de control.")
    if not _c(r, 28, 57).strip():
        inf.aviso(n, "La factura no lleva nombre del tercero.")
    f_op, f_fra = _fecha(_c(r, 237, 244)), _fecha(_c(r, 245, 252))
    if f_op is None or f_fra is None:
        inf.error(n, "La fecha de operación (237-244) o la de factura (245-252) no son válidas.")
    elif fecha and f_fra != fecha:
        inf.aviso(n, "La fecha de la factura (245-252) no coincide con la del registro (7-14).")
    return {"registro": n, "abono": tipo == "2", "tipo_factura": tipo_factura, "numero": numero, "numero_completo": ampliado or numero, "total": total, "nif": nif, "fecha": fecha,
            "detalles": [], "ampliacion": False, "cerrada": False, "suma": 0}


def _detalle(inf: _Informe, n: int, r: str, f: dict, digitos: int) -> None:
    cuenta = _c(r, 16, 27)
    if not re.fullmatch(r"\d{12}", cuenta) or not cuenta[:digitos].strip("0"):
        inf.error(n, f"La cuenta de gasto o ingreso (16-27) no es válida: «{cuenta}».")
    sentido = _c(r, 58, 58)
    if sentido != ("A" if f["abono"] else "C"):
        inf.error(n, f"El sentido (58) debe ser «{'A' if f['abono'] else 'C'}» en {'un abono' if f['abono'] else 'una factura'} y es «{sentido}».")
    if _c(r, 59, 68).strip() != f["numero"]:
        inf.error(n, "El número de factura del detalle (59-68) no coincide con el de su cabecera.")
    marca = _c(r, 69, 69)
    if marca not in ("U", "M"):
        inf.error(n, f"La marca de último detalle (69) debe ser «U» o «M» y es «{marca}».")
    if f["detalles"] and f["detalles"][-1]["marca"] == "U":
        inf.error(n, "Hay un detalle después del que estaba marcado como último («U»).")
    base, cuota = _importe(_c(r, 102, 115)), _importe(_c(r, 121, 134))
    rec, ret = _importe(_c(r, 140, 153)), _importe(_c(r, 159, 172))
    pct, pct_rec, pct_ret = _porcentaje(_c(r, 116, 120)), _porcentaje(_c(r, 135, 139)), _porcentaje(_c(r, 154, 158))
    if None in (base, cuota, rec, ret, pct, pct_rec, pct_ret):
        inf.error(n, "Algún importe o porcentaje del detalle no tiene el formato de a3 (+0000000000.00 y 00.00).")
        f["detalles"].append({"marca": marca})
        return
    sujeta = _c(r, 175, 175)
    if sujeta not in ("S", "N"):
        inf.error(n, f"La marca «sujeta a IVA» (175) debe ser «S» o «N» y es «{sujeta}».")
    if base == 0:
        inf.aviso(n, "Un detalle con base cero.")
    if sujeta == "S":
        esperada = int((Decimal(base) * Decimal(pct) / Decimal(10000)).quantize(Decimal("1")))
        if abs(esperada - cuota) > TOLERANCIA_CENTIMOS:
            inf.error(n, f"La cuota de IVA ({cuota / 100:.2f}) no es la base ({base / 100:.2f}) por el {pct / 100:g} %: saldría {esperada / 100:.2f}.")
        cuenta_iva = _c(r, 228, 239) if f["tipo_factura"] == "1" else _c(r, 192, 203)
        if cuota and not re.fullmatch(r"\d{12}", cuenta_iva):
            inf.error(n, f"Falta la cuenta de IVA {'repercutido (228-239)' if f['tipo_factura'] == '1' else 'soportado (192-203)'}.")
        if f["tipo_factura"] == "1" and _c(r, 192, 203).strip():
            inf.aviso(n, "Una factura emitida lleva cuenta de IVA soportado (192-203).")
        if f["tipo_factura"] == "2" and _c(r, 228, 239).strip():
            inf.aviso(n, "Una factura recibida lleva cuenta de IVA repercutido (228-239).")
    elif cuota:
        inf.error(n, "Un detalle no sujeto a IVA lleva cuota de IVA.")
    if ret:
        if not re.fullmatch(r"\d{12}", _c(r, 216, 227)):
            inf.error(n, "Hay retención (159-172) y falta su cuenta (216-227).")
        esperada_ret = int((Decimal(base) * Decimal(pct_ret) / Decimal(10000)).quantize(Decimal("1")))
        if abs(esperada_ret - ret) > TOLERANCIA_CENTIMOS:
            inf.error(n, f"La retención ({ret / 100:.2f}) no es la base por el {pct_ret / 100:g} %: saldría {esperada_ret / 100:.2f}.")
    if rec:
        esperada_rec = int((Decimal(base) * Decimal(pct_rec) / Decimal(10000)).quantize(Decimal("1")))
        if abs(esperada_rec - rec) > TOLERANCIA_CENTIMOS:
            inf.error(n, f"El recargo ({rec / 100:.2f}) no es la base por el {pct_rec / 100:g} %.")
    f["detalles"].append({"marca": marca, "registro": n})
    f["suma"] += base + cuota + rec - ret


def _ampliacion(inf: _Informe, n: int, r: str, f: dict) -> None:
    f["cerrada"] = True
    f["ampliacion"] = True
    if not f["abono"]:
        inf.error(n, "Una ampliación de rectificativa (tipo 4) sigue a una factura normal: solo los abonos y rectificativas (tipo 2) la llevan.")
        return
    if _fecha(_c(r, 59, 66)) is None:
        inf.error(n, "Falta la fecha de la factura rectificada (59-66) o no es válida.")
    if not _c(r, 67, 126).strip():
        inf.error(n, "Falta el número de la factura rectificada (67-126).")
    if _c(r, 157, 157) != "R":
        inf.error(n, f"El tipo de rectificativa (157) debe ser «R» y es «{_c(r, 157, 157)}».")
    esperado = "E" if f["tipo_factura"] == "1" else "R"
    if _c(r, 304, 304) != esperado:
        inf.error(n, f"El tipo de factura de la ampliación (304) debe ser «{esperado}» y es «{_c(r, 304, 304)}».")


def _cerrar(inf: _Informe, f: dict) -> None:
    n = f["registro"]
    if not f["detalles"]:
        inf.error(n, f"La factura {f['numero_completo']} no tiene ningún detalle de IVA.")
        return
    if f["detalles"][-1].get("marca") != "U":
        inf.error(f["detalles"][-1].get("registro", n), f"El último detalle de la factura {f['numero_completo']} debe llevar «U» en la posición 69.")
    if f["abono"] and not f["ampliacion"]:
        inf.error(n, f"El abono {f['numero_completo']} necesita su registro de ampliación (tipo 4) con la factura que rectifica.")
    if f["total"] is not None and abs(f["suma"] - f["total"]) > TOLERANCIA_CENTIMOS * len(f["detalles"]):
        inf.aviso(n, f"El total de la cabecera ({f['total'] / 100:.2f}) no es la suma de sus detalles ({f['suma'] / 100:.2f}): normal si la factura lleva suplidos, si no hay que revisarla.")


def _resultado(inf: _Informe, n_registros: int, facturas: list[dict], extra: dict) -> dict:
    return {"ok": not inf.errores, "registros": n_registros, "facturas": len(facturas), "errores": inf.errores, "avisos": inf.avisos,
            "totales": {"total": sum(f["total"] or 0 for f in facturas) / 100, "abonos": sum(1 for f in facturas if f["abono"])}, **extra}
