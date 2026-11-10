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
_SUBTIPOS_EMITIDA = {"01", "02", "03", "04", "05", "06", "07", "08", "09"}
_SUBTIPOS_RECIBIDA = {"01", "02", "03", "04", "06", "07", "08"}
_EMITIDA_SIN_IVA = {"02", "03", "04", "05", "06", "07", "09"}
IMPRESO_349 = {("1", "03"): "02", ("1", "04"): "02", ("2", "03"): "02", ("2", "08"): "11"}      # tipo de factura 1 emitida · 2 recibida
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
    def __init__(self, formato: str = enlace_a3.FORMATO_SII) -> None:
        self.errores: list[dict] = []
        self.avisos: list[dict] = []
        self.formato = formato                                    # «512» (SII) o «256» (clásico): cambian la longitud del registro y las posiciones de moneda y generado

    def error(self, registro: int | None, mensaje: str) -> None:
        self.errores.append({"registro": registro, "mensaje": mensaje})

    def aviso(self, registro: int | None, mensaje: str) -> None:
        self.avisos.append({"registro": registro, "mensaje": mensaje})


def formato_de(contenido: bytes) -> str:
    """El formato del fichero por dónde cae el primer CR LF: en la posición 255-256 es el clásico de 256 y en la 511-512 el de 512 (SII). Si no hay ninguno claro, el tipo de formato de la posición 1
    (4 = clásico) y, a falta de él, el de 512."""
    if contenido[254:256] == b"\r\n":
        return enlace_a3.FORMATO_CLASICO
    if contenido[510:512] == b"\r\n":
        return enlace_a3.FORMATO_SII
    return enlace_a3.FORMATO_CLASICO if contenido[:1] == b"4" and len(contenido) % 256 == 0 else enlace_a3.FORMATO_SII


def chequear(contenido: bytes, digitos: int = 8) -> dict:
    """Revisa el contenido de un SUENLACE.DAT (formato de 512 o clásico de 256, según lo que empiece). Devuelve `{ok, registros, facturas, errores, avisos, totales}`; `errores` y `avisos` son listas de
    `{registro, mensaje}` (registro 1 = el primero)."""
    formato = formato_de(contenido) if contenido else enlace_a3.FORMATO_SII
    inf = _Informe(formato)
    largo = 256 if formato == enlace_a3.FORMATO_CLASICO else 512
    if not contenido:
        inf.error(None, "El fichero está vacío.")
        return _resultado(inf, 0, [], {})
    if len(contenido) % largo:
        inf.error(None, f"El tamaño ({len(contenido)} bytes) no es múltiplo de {largo}: los registros de este formato son de {largo} bytes ({largo - 2} caracteres más CR LF).")
    try:
        texto = contenido.decode("latin-1")
    except UnicodeDecodeError:       # no puede pasar con latin-1, por si acaso
        inf.error(None, "El fichero no está en ASCII/Latin-1.")
        return _resultado(inf, 0, [], {})
    registros = [texto[i:i + largo] for i in range(0, len(texto), largo)]
    facturas: list[dict] = []
    actual: dict | None = None
    empresas, vistos = set(), {}
    for n, r in enumerate(registros, start=1):
        if len(r) != largo or not r.endswith("\r\n"):
            inf.error(n, f"El registro no mide {largo} bytes o no acaba en CR LF.")
            continue
        r = r[:enlace_a3.LONGITUD_DE[formato]]
        esperado = enlace_a3.TIPO_DE_FORMATO[formato]
        if _c(r, 1, 1) != esperado:
            inf.error(n, f"La posición 1 debe ser «{esperado}» y es «{_c(r, 1, 1)}».")
            continue
        pos_moneda, pos_generado = (509, 510) if formato == enlace_a3.FORMATO_SII else (253, 254)
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
        if _c(r, 15, 15) not in ("3", "4") and _c(r, pos_moneda, pos_moneda) != "E":         # la observación (tipo 3) y la ampliación (tipo 4) no llevan moneda
            inf.error(n, f"La posición {pos_moneda} (moneda) debe ser «E» (euros).")
        if _c(r, pos_generado, pos_generado) not in ("N", "S"):
            inf.error(n, f"La posición {pos_generado} (generado/ya contabilizado) debe ser «N» o «S».")
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
        elif tipo == "V" and inf.formato == enlace_a3.FORMATO_CLASICO:
            _vencimiento(inf, n, r, actual)
        elif tipo == "C" and inf.formato == enlace_a3.FORMATO_CLASICO:
            _alta_de_cuenta(inf, n, r, digitos)
        elif tipo == "3" and inf.formato == enlace_a3.FORMATO_CLASICO:
            if actual is None:
                inf.error(n, "Una observación (tipo 3) tiene que ir después del apunte al que se refiere.")
        else:
            inf.error(n, f"Tipo de registro desconocido en la posición 15: «{tipo}».")
    for f in facturas:
        _cerrar(inf, f)
    _coherencia_de_cuentas(inf, facturas, digitos)
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
    if tipo_factura not in ("1", "2", "3"):
        inf.error(n, f"El tipo de factura (58) debe ser 1 (emitida), 2 (recibida) o 3 (bien de inversión) y es «{tipo_factura}».")

    numero = _c(r, 59, 68).strip()
    ampliado = _c(r, 253, 312).strip() if inf.formato == enlace_a3.FORMATO_SII else ""
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
        if not fiscal_identidad.clave_unica(nif, "ES") and re.fullmatch(r"[A-Z0-9]+", nif) and (inf.formato == enlace_a3.FORMATO_CLASICO or _c(r, 374, 375) == "ES"):
            inf.aviso(n, f"El NIF «{nif}» no pasa la validación de dígito de control.")
    if not _c(r, 28, 57).strip():
        inf.aviso(n, "La factura no lleva nombre del tercero.")
    f_op, f_fra = _fecha(_c(r, 237, 244)), _fecha(_c(r, 245, 252))
    if f_op is None or f_fra is None:
        inf.error(n, "La fecha de operación (237-244) o la de factura (245-252) no son válidas.")
    elif fecha and f_fra != fecha:
        inf.aviso(n, "La fecha de la factura (245-252) no coincide con la del registro (7-14).")
    return {"registro": n, "abono": tipo == "2", "tipo_factura": tipo_factura, "numero": numero, "numero_completo": ampliado or numero, "total": total, "nif": nif, "fecha": fecha,
            "detalles": [], "ampliacion": False, "cerrada": False, "suma": 0, "cuenta": cuenta, "cuentas_detalle": []}


def _detalle(inf: _Informe, n: int, r: str, f: dict, digitos: int) -> None:
    cuenta = _c(r, 16, 27)
    if not re.fullmatch(r"\d{12}", cuenta) or not cuenta[:digitos].strip("0"):
        inf.error(n, f"La cuenta de gasto o ingreso (16-27) no es válida: «{cuenta}».")
    f["cuentas_detalle"].append((n, cuenta))
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
    subtipo = _c(r, 100, 101)
    validos = _SUBTIPOS_EMITIDA if f["tipo_factura"] == "1" else _SUBTIPOS_RECIBIDA
    if subtipo not in validos:
        inf.error(n, f"El subtipo de operación (100-101) «{subtipo}» no vale en una factura {'emitida' if f['tipo_factura'] == '1' else 'recibida'}: los válidos son {', '.join(sorted(validos))}.")
    impreso = _c(r, 173, 174)
    if impreso.strip() and not re.fullmatch(r"\d{2}", impreso):
        inf.error(n, f"El impreso (173-174) debe ser dos dígitos o ir en blanco y es «{impreso}».")
    esperado_349 = IMPRESO_349.get((f["tipo_factura"], subtipo))
    if esperado_349 and impreso != esperado_349:
        inf.aviso(n, f"Una operación intracomunitaria (subtipo {subtipo}) debería ir al impreso {esperado_349} (modelo 349) y lleva «{impreso.strip() or 'ninguno'}».")
    caja = _c(r, 177, 177)
    if caja not in (" ", "S"):
        inf.error(n, f"La marca de criterio de caja (177) debe ser «S» o ir en blanco y es «{caja}».")
    elif caja == "S" and f["tipo_factura"] == "1":
        inf.aviso(n, "El criterio de caja (177) solo se tiene en cuenta en facturas recibidas.")
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
    if sujeta == "S" and base and pct == 0 and subtipo == "01":
        inf.aviso(n, "Operación interior con IVA al 0 %: ¿es exenta o no sujeta? Cámbiale el tipo de operación si lo es.")
    if f["tipo_factura"] == "1" and subtipo in _EMITIDA_SIN_IVA and pct:
        inf.aviso(n, f"Una operación del subtipo {subtipo} (exenta, intracomunitaria, exportación…) lleva IVA del {pct / 100:g} %.")
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
    clasico = inf.formato == enlace_a3.FORMATO_CLASICO
    if not f["abono"] and not clasico:
        inf.error(n, "Una ampliación de rectificativa (tipo 4) sigue a una factura normal: solo los abonos y rectificativas (tipo 2) la llevan.")
        return
    if clasico:
        _ampliacion_clasica(inf, n, r, f)
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


def _alta_de_cuenta(inf: _Informe, n: int, r: str, digitos: int) -> None:
    """Registro tipo C del formato de 256: alta o modificación de una cuenta de cliente o proveedor."""
    cuenta = _c(r, 16, 27)
    if not re.fullmatch(r"\d{12}", cuenta):
        inf.error(n, f"La cuenta (16-27) debe tener 12 dígitos y es «{cuenta}».")
    elif cuenta[digitos:].strip("0"):
        inf.error(n, f"La cuenta {cuenta[:digitos]}… tiene más de {digitos} dígitos significativos.")
    if not _c(r, 28, 57).strip():
        inf.aviso(n, "La cuenta no lleva nombre.")
    if _c(r, 58, 58) not in ("S", "N"):
        inf.error(n, f"La marca «actualizar saldo inicial» (58) debe ser S o N y es «{_c(r, 58, 58)}».")
    if _c(r, 73, 73) not in (" ", "B"):
        inf.error(n, f"La marca de ampliación (73) debe ir en blanco (cuenta) o ser «B» (banco) y es «{_c(r, 73, 73)}».")
    if _c(r, 238, 238) not in (" ", "S", "N"):
        inf.error(n, f"La marca de criterio de caja (238) debe ser S, N o ir en blanco y es «{_c(r, 238, 238)}».")
    nif = _c(r, 78, 91).strip()
    if nif and _c(r, 73, 73) == " " and not re.fullmatch(r"[A-Z0-9]{5,14}", nif):
        inf.error(n, f"El NIF de la cuenta (78-91) «{nif}» tiene caracteres que no vale.")


def _vencimiento(inf: _Informe, n: int, r: str, factura: dict | None) -> None:
    """Registros tipo V del formato de 256: el alta del vencimiento (posición 69 en blanco) y su ampliación (69 = «A»). Tienen que ir después de la factura a la que pertenecen."""
    if factura is None:
        inf.error(n, "Un registro de vencimiento (tipo V) tiene que ir después de la factura a la que pertenece.")
        return
    if _fecha(_c(r, 7, 14)) is None:
        inf.error(n, f"La fecha del vencimiento (7-14) no es válida: «{_c(r, 7, 14)}».")
    marca = _c(r, 69, 69)
    if marca == "A":
        forma = _c(r, 59, 60).strip()
        if forma and forma not in enlace_a3.FORMAS_DE_PAGO:
            inf.error(n, f"El tipo de cobro o pago (59-60) «{forma}» no vale: los válidos son {', '.join(enlace_a3.FORMAS_DE_PAGO)}.")
        if _c(r, 70, 70) not in ("P", "D", "C", "G"):
            inf.error(n, f"El estado del vencimiento (70) debe ser P, D, C o G y es «{_c(r, 70, 70)}».")
        return
    if marca != " ":
        inf.error(n, f"La marca de ampliación del vencimiento (69) debe ir en blanco o ser «A» y es «{marca}».")
    if _c(r, 58, 58) not in ("C", "P"):
        inf.error(n, f"El tipo de vencimiento (58) debe ser C (cobro) o P (pago) y es «{_c(r, 58, 58)}».")
    elif _c(r, 58, 58) != ("C" if factura["tipo_factura"] == "1" else "P"):
        inf.aviso(n, f"El vencimiento es de {'cobro' if _c(r, 58, 58) == 'C' else 'pago'} y la factura {factura['numero_completo']} es {'emitida' if factura['tipo_factura'] == '1' else 'recibida'}.")
    if _importe(_c(r, 100, 113)) is None:
        inf.error(n, f"El importe del vencimiento (100-113) no tiene el formato +0000000000.00: «{_c(r, 100, 113)}».")
    if _fecha(_c(r, 114, 121)) is None:
        inf.error(n, "La fecha de factura del vencimiento (114-121) no es válida.")
    cuenta = _c(r, 16, 27)
    if not re.fullmatch(r"\d{12}", cuenta):
        inf.error(n, f"La cuenta del vencimiento (16-27) debe tener 12 dígitos y es «{cuenta}».")
    forma = _c(r, 134, 135)
    if forma.strip() and not re.fullmatch(r"\d{2}", forma):
        inf.error(n, f"La forma de pago (134-135) debe ser dos dígitos o ir en blanco y es «{forma}».")


def _ampliacion_clasica(inf: _Informe, n: int, r: str, f: dict) -> None:
    """El tipo 4 del formato de 256: factura rectificada (59-76), DUA (77-94), clave del 340 (107), NIF del representante (108-121), autofactura (122-131) y los importes del 347 (132-161)."""
    if f["abono"]:
        if _fecha(_c(r, 59, 66)) is None:
            inf.error(n, "Falta la fecha de la factura rectificada (59-66) o no es válida.")
        if not _c(r, 67, 76).strip():
            inf.error(n, "Falta el número de la factura rectificada (67-76).")
    elif _c(r, 59, 76).strip():
        inf.aviso(n, "Una factura que no es rectificativa lleva datos de factura rectificada (59-76).")
    clave = _c(r, 107, 107)
    if clave.strip():
        permitido = ("1",) if f["tipo_factura"] == "1" else ("1", "3")
        if clave not in permitido:
            inf.error(n, f"La clave de factura para el modelo 340 (107) «{clave}» no vale en una factura {'emitida' if f['tipo_factura'] == '1' else 'recibida'}: los valores son {', '.join(permitido)}.")
    for desde, hasta, marca in ((133, 146, 132), (148, 161, 147)):
        importe, m = _c(r, desde, hasta), _c(r, marca, marca)
        if m not in (" ", "S"):
            inf.error(n, f"La marca de la posición {marca} debe ser «S» o ir en blanco y es «{m}».")
        if importe.strip() and _importe(importe) is None:
            inf.error(n, f"El importe de las posiciones {desde}-{hasta} no tiene el formato +0000000000.00.")
        if m == "S" and importe.strip():
            inf.aviso(n, f"Con la marca «S» en la posición {marca} el importe de {desde}-{hasta} no se tiene en cuenta (se toma el total de la factura).")


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


def _coherencia_de_cuentas(inf: _Informe, facturas: list[dict], digitos: int) -> None:
    """Avisos sobre cómo se reparten las cuentas en el fichero (J6): un proveedor o un cliente con la subcuenta de la clase que no es, un gasto en una cuenta de ingresos (o al revés), varios NIF
    distintos en una misma subcuenta y un mismo NIF con subcuentas distintas. Solo avisan: a3 los admite, pero casi siempre son un error de configuración."""
    for f in facturas:
        grupo = f["cuenta"][:2] if re.fullmatch(r"\d{12}", f["cuenta"] or "") else ""
        if f["tipo_factura"] == "2" and grupo == "43":
            inf.aviso(f["registro"], f"La factura recibida {f['numero_completo']} lleva una subcuenta de clientes ({f['cuenta'][:digitos]}…): ¿es un proveedor?")
        elif f["tipo_factura"] == "1" and grupo in ("40", "41"):
            inf.aviso(f["registro"], f"La factura emitida {f['numero_completo']} lleva una subcuenta de proveedores ({f['cuenta'][:digitos]}…): ¿es un cliente?")
        for registro, cuenta in f["cuentas_detalle"]:
            clase = cuenta[:1] if re.fullmatch(r"\d{12}", cuenta) else ""
            if f["tipo_factura"] == "2" and clase == "7":
                inf.aviso(registro, f"La factura recibida {f['numero_completo']} lleva una cuenta de ingresos ({cuenta[:digitos]}…): ¿es un gasto?")
            elif f["tipo_factura"] == "1" and clase == "6":
                inf.aviso(registro, f"La factura emitida {f['numero_completo']} lleva una cuenta de gastos ({cuenta[:digitos]}…): ¿es un ingreso?")
    por_cuenta: dict[tuple[str, str], dict[str, int]] = {}
    por_nif: dict[tuple[str, str], dict[str, int]] = {}
    for f in facturas:
        if f["nif"] and re.fullmatch(r"\d{12}", f["cuenta"] or ""):
            por_cuenta.setdefault((f["tipo_factura"], f["cuenta"]), {}).setdefault(f["nif"], f["registro"])
            por_nif.setdefault((f["tipo_factura"], f["nif"]), {}).setdefault(f["cuenta"], f["registro"])
    for (_tipo, cuenta), nifs in por_cuenta.items():
        if len(nifs) > 1:
            inf.aviso(min(nifs.values()), f"La subcuenta {cuenta[:digitos]} se usa con {len(nifs)} NIF distintos: en a3 quedarán todos en la misma ficha (¿falta la subcuenta propia de cada uno?).")
    for (_tipo, nif), cuentas in por_nif.items():
        if len(cuentas) > 1:
            inf.aviso(min(cuentas.values()), f"El NIF {nif} aparece con {len(cuentas)} subcuentas distintas en este fichero: sus facturas se repartirán en varias fichas de a3.")


def _resultado(inf: _Informe, n_registros: int, facturas: list[dict], extra: dict) -> dict:
    return {"ok": not inf.errores, "registros": n_registros, "facturas": len(facturas), "errores": inf.errores, "avisos": inf.avisos,
            "totales": {"total": sum(f["total"] or 0 for f in facturas) / 100, "abonos": sum(1 for f in facturas if f["abono"])}, **extra}
