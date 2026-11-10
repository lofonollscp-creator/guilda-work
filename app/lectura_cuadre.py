"""Cuadre de las líneas de una factura leída (L6): tipos de IVA, recargo y retención poco habituales y, cuando el total no sale de las líneas, qué combinación habitual de IVA, recargo y retención sí
lo haría. Solo avisa: nunca cambia lo leído, porque adivinar una operación fiscal no es cosa del programa. Los porcentajes van en centésimas de punto (2100 = 21 %), como en `facturas_contables`."""
from __future__ import annotations

from itertools import product

from . import enlace_a3, facturas_contables as fc

TIPOS_IVA = (0, 200, 400, 500, 750, 1000, 2100)                  # general, reducidos, superreducido y los temporales de 2 %, 5 % y 7,5 %
RETENCIONES = (0, 100, 200, 700, 1500, 1900, 2100, 2400)         # agrícola, ganadera, nuevos profesionales, profesionales, alquileres, capital y no residentes


def _pct(valor) -> int | None:
    try:
        return fc.porcentaje_a_centesimas(valor)
    except ValueError:
        return None


def _texto_pct(c: int) -> str:
    return f"{c / 100:g}".replace(".", ",")


def tipos_raros(lineas: list[dict]) -> list[str]:
    """Avisos de las líneas cuyo IVA, recargo o retención no son de los habituales, o cuyo recargo no acompaña a su tipo de IVA."""
    salida = []
    for i, l in enumerate(lineas, 1):
        iva, rec, ret = _pct(l.get("pct_iva")), _pct(l.get("pct_recargo")), _pct(l.get("pct_retencion"))
        if iva is not None and str(l.get("pct_iva") or "").strip() and iva not in TIPOS_IVA:
            salida.append(f"Línea {i}: el {_texto_pct(iva)} % de IVA no es un tipo habitual (0, 4, 5, 10 y 21 %): puede estar mal leído.")
        if rec and iva is not None and fc.RECARGO_ESTANDAR.get(iva) != rec:
            salida.append(f"Línea {i}: el recargo de equivalencia del {_texto_pct(rec)} % no es el que corresponde a un IVA del {_texto_pct(iva)} %.")
        if ret and ret not in RETENCIONES:
            salida.append(f"Línea {i}: la retención del {_texto_pct(ret)} % no es una de las habituales (7, 15, 19, 21 y 24 %).")
    return salida


def _bases(lineas: list[dict]) -> list[int] | None:
    try:
        return [fc.importe_a_centimos(l.get("base")) for l in lineas]
    except ValueError:
        return None


def _describir(iva: int | None, rec: int, ret: int) -> str:
    partes = [] if iva is None else [f"{_texto_pct(iva)} % de IVA"]
    if rec:
        partes.append(f"recargo del {_texto_pct(rec)} %")
    if ret:
        partes.append(f"retención del {_texto_pct(ret)} %")
    return ", ".join(partes)


def _buscar(lineas: list[dict], suplidos: str, total: str) -> dict | None:
    """La única explicación (con lo menos extraño) que hace cuadrar el total con las líneas: {"sin_iva": True} si el total es la suma de las bases, o {"iva", "rec", "ret"} (iva None = se deja el leído de
    cada línea). None si no hay explicación o hay varias igual de probables, o si las líneas ya cuadran."""
    bases = _bases(lineas)
    if not bases or total in ("", None, "0.00"):
        return None
    try:
        objetivo, extra = fc.importe_a_centimos(total), fc.importe_a_centimos(suplidos or "0")
    except ValueError:
        return None
    if abs(sum(bases) + extra - objetivo) <= fc.TOLERANCIA_CENTIMOS and any(str(l.get("cuota_iva") or "").strip() not in ("", "0", "0.00") for l in lineas):
        return {"sin_iva": True}
    if len(lineas) == 1:
        iva_leido = _pct(lineas[0].get("pct_iva"))
        opciones = [(iva, rec, ret) for iva, ret in product(TIPOS_IVA, RETENCIONES) for rec in {0, fc.RECARGO_ESTANDAR.get(iva, 0)}]

        def total_de(o):
            iva, rec, ret = o
            return bases[0] + enlace_a3.cuota(bases[0], iva) + enlace_a3.cuota(bases[0], rec) - enlace_a3.cuota(bases[0], ret) + extra
    else:
        ivas = [_pct(l.get("pct_iva")) for l in lineas]
        if any(i is None for i in ivas):
            return None
        iva_leido = None
        opciones = [(None, rec, ret) for rec, ret in product((0, 1), RETENCIONES)]

        def total_de(o):
            _, rec, ret = o
            return sum(b + enlace_a3.cuota(b, i) + (enlace_a3.cuota(b, fc.RECARGO_ESTANDAR.get(i, 0)) if rec else 0) - enlace_a3.cuota(b, ret) for b, i in zip(bases, ivas)) + extra
    encajan = [o for o in opciones if abs(total_de(o) - objetivo) <= fc.TOLERANCIA_CENTIMOS]
    if not encajan:
        return None

    def rareza(o):                                                   # cuanto menos cambie lo leído y menos extras lleve, más probable
        return (o[0] not in (iva_leido, None)) * 2 + bool(o[1]) + bool(o[2])
    mejor = min(rareza(o) for o in encajan)
    elegidas = [o for o in encajan if rareza(o) == mejor]
    if len({(o[0], bool(o[1]), o[2]) for o in elegidas}) != 1:
        return None
    iva, rec, ret = elegidas[0]
    return {"iva": iva, "rec": bool(rec) if len(lineas) > 1 else rec, "ret": ret, "iva_leido": iva_leido}


def explicar_descuadre(lineas: list[dict], suplidos: str, total: str) -> str | None:
    """Si las líneas no suman el total, dice qué explicación cuadra con él (ver `_buscar`): con una sola base prueba los tipos habituales de IVA, con o sin recargo y retención; con varias deja el IVA leído y
    prueba solo recargo y retención. Si hay varias explicaciones o ninguna, calla."""
    e = _buscar(lineas, suplidos, total)
    otra = _otra_explicacion(lineas, suplidos, total)
    if e is None or otra:
        return None if (e and otra) else otra                      # si IVA, recargo o retención y una exenta o un descuento lo explican a la vez, no se elige: se calla
    if e.get("sin_iva"):
        return "El total de la factura coincide con la suma de las bases: el total leído parece no incluir el IVA."
    rec = e["rec"] if len(lineas) == 1 else (fc.RECARGO_ESTANDAR.get(_pct(lineas[0].get("pct_iva")), 0) if e["rec"] else 0)
    return f"El total de la factura cuadraría con {_describir(e['iva'], rec, e['ret'])}: compruébalo en el documento."


DESCUENTOS_HABITUALES = (100, 200, 300, 500, 1000, 1500, 2000)      # en centésimas de punto: 1 %, 2 %, 3 %, 5 %, 10 %, 15 % y 20 % (pronto pago y descuentos de pie de factura)


def _otra_explicacion(lineas: list[dict], suplidos: str, total: str) -> str | None:
    """Lo que explica un descuadre cuando no es IVA, recargo ni retención: que alguna línea sea exenta (sin IVA) o que haya un descuento general sobre las bases (pronto pago, pie de factura). Si hay una
    sola explicación, la dice; si hay varias o ninguna, calla. Con una sola línea no hay «alguna línea»."""
    bases = _bases(lineas)
    if not bases or total in ("", None, "0.00"):
        return None
    try:
        objetivo, extra = fc.importe_a_centimos(total), fc.importe_a_centimos(suplidos or "0")
    except ValueError:
        return None
    ivas = [_pct(l.get("pct_iva")) for l in lineas]
    if any(i is None for i in ivas):
        return None
    tol = fc.TOLERANCIA_CENTIMOS
    exentas = []
    if len(lineas) > 1:
        for mascara in range(1, 2 ** len(lineas) - 1):                          # no todas las líneas: una factura entera sin IVA no es «alguna línea exenta»
            if abs(sum(b + (0 if mascara >> i & 1 else enlace_a3.cuota(b, iv)) for i, (b, iv) in enumerate(zip(bases, ivas))) + extra - objetivo) <= tol:
                exentas.append([i + 1 for i in range(len(lineas)) if mascara >> i & 1])
    if len(exentas) == 1:
        n = exentas[0]
        return f"El total de la factura cuadraría si {'la línea ' + str(n[0]) if len(n) == 1 else 'las líneas ' + ', '.join(map(str, n))} {'fuera exenta o no sujeta' if len(n) == 1 else 'fueran exentas o no sujetas'} (sin IVA): compruébalo en el documento."
    descuentos = [d for d in DESCUENTOS_HABITUALES
                  if abs(sum(b - enlace_a3.cuota(b, d) + enlace_a3.cuota(b - enlace_a3.cuota(b, d), iv) for b, iv in zip(bases, ivas)) + extra - objetivo) <= tol]
    if len(descuentos) == 1 and not exentas:
        return f"El total de la factura cuadraría con un descuento del {_texto_pct(descuentos[0])} % sobre las bases (pronto pago o descuento general): comprueba si las bases leídas ya lo llevan."
    return None


PALABRAS_RETENCION = ("irpf", "retencion", "retenciones")


def aplicar_retencion(lineas: list[dict], suplidos: str, total: str, texto: str) -> str | None:
    """Cuando el documento habla de IRPF o de retención y el total solo cuadra con una retención habitual sobre las líneas leídas (sin cambiar su IVA), la pone en las líneas que no la traen y lo cuenta. Sin
    texto del documento no se toca nada (lo único que hay es el aviso de `explicar_descuadre`). Devuelve el aviso, o None si no se aplicó."""
    from . import lectura_evidencias
    if not texto or not any(p in lectura_evidencias._plano(texto) for p in PALABRAS_RETENCION) or any(_pct(l.get("pct_retencion")) for l in lineas):
        return None
    e = _buscar(lineas, suplidos, total)
    if not e or e.get("sin_iva") or not e["ret"] or e["rec"] or (e["iva"] is not None and e["iva"] != e["iva_leido"]):
        return None
    for l in lineas:
        l["pct_retencion"] = _texto_pct(e["ret"]).replace(",", ".")
    return f"Se ha aplicado la retención del {_texto_pct(e['ret'])} % (IRPF) que menciona el documento, porque con ella el total cuadra; compruébalo."


def suplidos_del_texto(lineas: list[dict], suplidos: str, total: str, texto: str) -> str | None:
    """Cuando el total supera lo que suman las líneas y el documento habla de suplidos, la diferencia se anota como suplidos (importes pagados por cuenta del cliente, sin IVA). Devuelve el importe en texto
    («45.00») o None si no procede: sin texto del documento, con suplidos ya anotados o si la diferencia no es positiva."""
    from . import lectura_evidencias
    if not texto or "suplido" not in lectura_evidencias._plano(texto) or fc.importe_a_centimos(suplidos or "0") or not lineas or total in ("", None, "0.00"):
        return None
    try:
        calculado = fc._total_de(fc._lineas_limpias(lineas), 0)
        dif = fc.importe_a_centimos(total) - calculado
    except ValueError:
        return None
    return f"{dif / 100:.2f}" if dif > fc.TOLERANCIA_CENTIMOS else None
