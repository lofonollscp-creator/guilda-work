"""Motor de cálculo del **modelo 390** (declaración-resumen anual del IVA, ejercicio 2025 y siguientes del diseño `390_2025.json`). Función PURA: de los apuntes del año (y de los cuatro 303) a las casillas
del 390. Para clasificar cada apunte REUTILIZA la lógica del 303 (`motor_303`) trimestre a trimestre —así el devengo, la fecha de deducción y los bloqueos son los mismos— y lo desglosa por tipo de IVA
usando el tipo del propio apunte, porque el 303 agrupa las cuotas deducibles y el 390 las pide por tipo.

Los números de casilla NO se escriben de memoria: se buscan por su descripción en el diseño oficial (`disenos/390_2025.json`) la primera vez que se usan, y las pruebas comprueban que cada una existe.
Como en el 303, **lo que no está soportado se BLOQUEA** en vez de dar un número que podría ser falso: adquisiciones intracomunitarias (el 390 separa bienes y servicios y el apunte no lo recoge), criterio de
caja, recargo de equivalencia, prorrata, régimen simplificado, tributación foral, tipos de IVA que el 390 no desglosa, exenciones sin clasificar…

Importes en céntimos enteros con signo; porcentajes en centésimas."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import motor_303 as m303
from .apuntes import EXPEDIDAS, RECIBIDAS, RECTIFICATIVAS, Apunte

DISENO_390 = Path(__file__).resolve().parent / "disenos" / "390_2025.json"
TRIMESTRES = ("1T", "2T", "3T", "4T")
TIPOS_DEVENGO = (0, 400, 500, 1000, 2100)                      # el 303 solo soporta estos; el 390 también tiene 2 % y 7,5 %, que el 303 bloquea
TIPOS_DEDUCIBLE = (400, 500, 1000, 2100)


class ErrorDeCalculo390(ValueError):
    pass


@dataclass
class Resultado390:
    ejercicio: int
    casillas: dict[str, int] = field(default_factory=dict)
    origen: dict[str, list[int]] = field(default_factory=dict)
    bloqueos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def calculable(self) -> bool:
        return not self.bloqueos

    def sumar(self, casilla: str, importe: int, indice: int | None = None) -> None:
        self.casillas[casilla] = self.casillas.get(casilla, 0) + importe
        if indice is not None and indice not in self.origen.setdefault(casilla, []):
            self.origen[casilla].append(indice)


@lru_cache(maxsize=1)
def _descripciones() -> list[tuple[str, str, str]]:
    """`[(hoja, casilla, descripción sin el «N. » del principio)]` del diseño oficial."""
    d = json.loads(DISENO_390.read_text(encoding="utf-8"))
    salida = []
    for p in d["paginas"]:
        for c in p["campos"]:
            m = re.search(r"\[(\d+)\]\s*\.?\s*$", c["descripcion"])
            if m:
                salida.append((p["hoja"], m.group(1), re.sub(r"^\d+\.\s*", "", c["descripcion"])))
    return salida


@lru_cache(maxsize=None)
def casilla(hoja: str, *fragmentos: str, final: str = "") -> str:
    """La casilla del diseño oficial, en esa hoja, cuya descripción contiene TODOS los fragmentos y cuyo último tramo (tras el último « - », sin el «[nnn]») empieza por `final`. Debe haber una sola."""
    hallazgos = []
    for h, c, t in _descripciones():
        ultimo = re.sub(r"\s*\[\d+\]\s*\.?\s*$", "", t).rsplit(" - ", 1)[-1]
        if h == hoja and all(f in t for f in fragmentos) and ultimo.startswith(final):
            hallazgos.append(c)
    if len(hallazgos) != 1:
        raise ErrorDeCalculo390(f"el diseño 390 no tiene una casilla única para {hoja} {fragmentos} {final!r}: {hallazgos}")
    return hallazgos[0]


def _pct(tipo: int) -> str:
    return f"{tipo / 100:g}".replace(".", ",") + "%"


def _par(hoja: str, bloque: str, tipo: int, base: str) -> tuple[str, str]:
    t = f"Tipo {_pct(tipo)} -"
    return casilla(hoja, bloque, t, final=base), casilla(hoja, bloque, t, final="Cuota")


def _par_total(hoja: str, bloque: str) -> tuple[str, str]:
    return casilla(hoja, "Total " + bloque, final="Base"), casilla(hoja, "Total " + bloque, final="Cuota")


# --- bloques del diseño (hoja, texto que identifica el bloque en la descripción)
DEV_ORDINARIO = ("Pág. 2", "Reg. ordin.")
DED_INTERIOR_CORRIENTE = ("Pág. 3", "Oper. inter. corrientes")
DED_INTERIOR_INVERSION = ("Pág. 3", "Oper. inter. bienes de inversion")
DED_IMPORT_CORRIENTE = ("Pág. 3", "Import. bienes corrientes")
DED_IMPORT_INVERSION = ("Pág. 3", "Importacion bienes inversion")


def _devengo_ordinario(tipo: int) -> tuple[str, str]:
    return _par("Pág. 2", "Reg. ordin.", tipo, "Base")


def _deducible(bloque: tuple[str, str], tipo: int) -> tuple[str, str]:
    return _par(bloque[0], bloque[1], tipo, "Base")


_TOTAL_DEDUCIBLE = {DED_INTERIOR_CORRIENTE: "oper. inter. corrientes", DED_INTERIOR_INVERSION: "oper. inter. bienes de inversion", DED_IMPORT_CORRIENTE: "import. bienes corrientes",
                    DED_IMPORT_INVERSION: "importacion bienes inversion"}


def _clasificar_trimestre(apuntes: list[Apunte], ejercicio: int, trimestre: str, r390: Resultado390, **ajustes) -> None:
    """Pasa por el 303 del trimestre y vuelca cada apunte en la casilla del 390 que le corresponde (por el tipo de IVA del propio apunte)."""
    r3 = m303.calcular(apuntes, ejercicio=ejercicio, periodo=trimestre, **{k: v for k, v in ajustes.items() if k != "destino_negativo"})
    for b in r3.bloqueos:
        if b not in r390.bloqueos:
            r390.bloqueos.append(b)
    bases_dev = {"150": 0, "01": 400, "154": 500, "04": 1000, "07": 2100}
    cuotas_dev = {"152": 0, "03": 400, "155": 500, "06": 1000, "09": 2100}
    for c3, tipo in bases_dev.items():
        for i in r3.origen.get(c3, []):
            r390.sumar(_devengo_ordinario(tipo)[0], apuntes[i].base, i)
    for c3, tipo in cuotas_dev.items():
        for i in r3.origen.get(c3, []):
            r390.sumar(_devengo_ordinario(tipo)[1], apuntes[i].cuota, i)
    for c3, (c390, atributo) in {"14": (casilla("Pág. 2", "Modificac. bases y cuotas -", final="Base"), "base"), "15": (casilla("Pág. 2", "Modificac. bases y cuotas -", final="Cuota"), "cuota"),
                                 "12": (casilla("Pág. 2", "invers. sujeto pasivo", final="Base"), "base"), "13": (casilla("Pág. 2", "invers. sujeto pasivo", final="Cuota"), "cuota")}.items():
        for i in r3.origen.get(c3, []):
            r390.sumar(c390, getattr(apuntes[i], atributo), i)
    if r3.origen.get("10") or r3.origen.get("11"):
        r390.bloqueos.append("Hay adquisiciones intracomunitarias: el 390 separa bienes y servicios y los apuntes todavía no lo recogen.")
    mapa_ded = {"28": (DED_INTERIOR_CORRIENTE, "base"), "29": (DED_INTERIOR_CORRIENTE, "deducible"), "30": (DED_INTERIOR_INVERSION, "base"), "31": (DED_INTERIOR_INVERSION, "deducible"),
                "32": (DED_IMPORT_CORRIENTE, "base"), "33": (DED_IMPORT_CORRIENTE, "deducible"), "34": (DED_IMPORT_INVERSION, "base"), "35": (DED_IMPORT_INVERSION, "deducible")}
    for c3, (bloque, atributo) in mapa_ded.items():
        for i in r3.origen.get(c3, []):
            a = apuntes[i]
            if a.tipo_iva not in TIPOS_DEDUCIBLE:
                msg = f"Recibida {a.serie}{a.numero}: el 390 no desglosa el tipo de IVA {a.tipo_iva / 100:g} %."
                if msg not in r390.bloqueos:
                    r390.bloqueos.append(msg)
                continue
            r390.sumar(_deducible(bloque, a.tipo_iva)[0 if atributo == "base" else 1], a.base if atributo == "base" else a.deducible, i)
    for c3, (c390, atributo) in {"40": (casilla("Pág. 4", "Rectificación de deducciones -", final="Base"), "base"), "41": (casilla("Pág. 4", "Rectificación de deducciones -", final="Cuota"), "deducible")}.items():
        for i in r3.origen.get(c3, []):
            r390.sumar(c390, getattr(apuntes[i], atributo), i)


def _volumen_de_operaciones(apuntes: list[Apunte], ejercicio: int, r: Resultado390) -> None:
    """Sección 10 del 390 (casillas 99, 103, 104, 105, 110, 125, 108), con las reglas de las instrucciones oficiales: el volumen suma lo declarado y RESTA las entregas de inmuebles y bienes de inversión
    (106 y 107), que van incluidas en la 99 y que los apuntes no distinguen: se dejan a 0 y se avisa."""
    c99, c103, c104, c105 = casilla("Pág. 6", "Volumen de operaciones", "régimen general"), casilla("Pág. 6", "Entregas intracomunitarias"), casilla("Pág. 6", "Exportaciones"), casilla("Pág. 6", "exentas sin derecho")
    c110, c125 = casilla("Pág. 6", "no sujetas por reglas de localización (excepto"), casilla("Pág. 6", "Operaciones sujetas con inversión del sujeto pasivo")
    for i, a in enumerate(apuntes):
        if a.libro != EXPEDIDAS:
            continue
        fecha = a.fecha_expedicion if a.tipo_factura in RECTIFICATIVAS else (a.fecha_operacion or a.fecha_expedicion)
        if fecha.year != ejercicio:
            continue
        if a.calificacion == "N1":
            continue
        if a.calificacion == "N2":
            r.sumar(c110, a.base, i)
        elif a.calificacion == "S2":
            r.sumar(c125, a.base, i)
        elif a.exenta:
            if a.exenta == "E5" and a.clave in ("01", "15"):
                r.sumar(c103, a.base, i)
            elif a.exenta in ("E2", "E3", "E4") and a.clave in ("01", "02", "05") or a.exenta == "E6" and a.clave in ("02", "05"):
                r.sumar(c104, a.base, i)
            elif a.exenta == "E1":
                r.sumar(c105, a.base, i)
            else:
                msg = f"Expedida {a.serie}{a.numero}: la exención {a.exenta} con la clave {a.clave} no se sabe clasificar en el volumen de operaciones."
                if msg not in r.bloqueos:
                    r.bloqueos.append(msg)
        elif a.calificacion == "S1":
            r.sumar(c99, a.base, i)
    total = sum(r.casillas.get(c, 0) for c in (c99, c103, c104, c105, c110, c125))
    r.casillas[casilla("Pág. 6", "Volumen de operaciones", "Total volumen")] = total
    if any(a.libro == EXPEDIDAS for a in apuntes):
        r.avisos.append("El volumen de operaciones no resta las entregas de inmuebles ni de bienes de inversión no habituales (casillas 106 y 107): se han tomado como 0. Si las hubo, corrígelo en el formulario.")


def volumen_anual(apuntes: list[Apunte], ejercicio: int) -> Resultado390:
    """Solo la sección de volumen de operaciones del año (casillas 99, 103, 104, 105, 110, 125 y 108 del 390): es lo que el 303 del último periodo pide a quien está exonerado del 390."""
    r = Resultado390(ejercicio)
    _volumen_de_operaciones(apuntes, ejercicio, r)
    return r


def _resultados_303(apuntes: list[Apunte], ejercicio: int, saldo_inicial: int, declaraciones: dict[str, dict] | None, ajustes: dict) -> list[dict]:
    """Los cuatro 303 del año: el de la declaración REVISADA o posterior si la hay, y si no el calculado ahora (con destino «C»)."""
    declaraciones = declaraciones or {}
    pendiente = max(0, saldo_inicial)
    salida = []
    for t in TRIMESTRES:
        calculo = m303.calcular(apuntes, ejercicio=ejercicio, periodo=t, cuotas_a_compensar_anteriores=pendiente, **ajustes)
        previo = declaraciones.get(t)
        casillas, tipo = (dict(previo["casillas"]), previo["tipo_declaracion"]) if previo else (dict(calculo.casillas), calculo.tipo_declaracion)
        salida.append({"periodo": t, "casillas": casillas, "tipo_declaracion": tipo, "de_declaracion": bool(previo), "calculo": calculo})
        pendiente = max(0, pendiente - casillas.get("78", 0) + (-casillas.get("71", 0) if tipo == "C" and casillas.get("71", 0) < 0 else 0))
    return salida


def calcular(apuntes: list[Apunte], *, ejercicio: int, saldo_compensar_inicial: int = 0, declaraciones_303: dict[str, dict] | None = None, tributacion_foral: bool = False, criterio_caja: bool = False,
             prorrata: bool = False, regimen_simplificado: bool = False, recargo_equivalencia: bool = False,
             prorrata_general: int | None = None) -> Resultado390:
    """Las casillas del 390 de `ejercicio`. `declaraciones_303`: `{"1T": {"casillas": {...}, "tipo_declaracion": "I"}, …}` con los 303 ya revisados (si falta un trimestre se calcula ahora)."""
    r = Resultado390(ejercicio)
    ajustes = {"tributacion_foral": tributacion_foral, "criterio_caja": criterio_caja, "prorrata": prorrata, "regimen_simplificado": regimen_simplificado, "recargo_equivalencia": recargo_equivalencia}
    for activo, motivo in ((tributacion_foral, "tributación foral"), (criterio_caja, "criterio de caja"), (prorrata or prorrata_general is not None, "prorrata o sectores diferenciados"), (regimen_simplificado, "régimen simplificado o agrario"),
                           (recargo_equivalencia, "recargo de equivalencia")):
        if activo:
            r.bloqueos.append(f"El titular tiene {motivo}: el cálculo automático del 390 en ese caso no está soportado todavía.")
    for t in TRIMESTRES:
        _clasificar_trimestre(apuntes, ejercicio, t, r, **{k: v for k, v in ajustes.items()})
    c = r.casillas
    # --- totales por bloque y del IVA devengado
    for bloque, etiqueta in _TOTAL_DEDUCIBLE.items():
        tb, tc = _par_total(bloque[0], etiqueta)
        tipos = TIPOS_DEDUCIBLE
        c[tb] = sum(c.get(_deducible(bloque, t)[0], 0) for t in tipos)
        c[tc] = sum(c.get(_deducible(bloque, t)[1], 0) for t in tipos)
    bases_dev = [_devengo_ordinario(t)[0] for t in TIPOS_DEVENGO]
    cuotas_dev = [_devengo_ordinario(t)[1] for t in TIPOS_DEVENGO]
    otras_bases = [casilla("Pág. 2", "Modificac. bases y cuotas -", final="Base"), casilla("Pág. 2", "invers. sujeto pasivo", final="Base")]
    otras_cuotas = [casilla("Pág. 2", "Modificac. bases y cuotas -", final="Cuota"), casilla("Pág. 2", "invers. sujeto pasivo", final="Cuota")]
    c[casilla("Pág. 2", "Total bases y cuotas IVA", final="Base")] = sum(c.get(k, 0) for k in bases_dev + otras_bases)
    c[casilla("Pág. 2", "Total bases y cuotas IVA", final="Cuota")] = devengado = sum(c.get(k, 0) for k in cuotas_dev + otras_cuotas)
    rect_cuota = casilla("Pág. 4", "Rectificación de deducciones -", final="Cuota")
    deducciones = sum(c.get(_par_total(b[0], e)[1], 0) for b, e in _TOTAL_DEDUCIBLE.items()) + c.get(rect_cuota, 0)
    c[casilla("Pág. 4", "Suma de deducciones")] = deducciones
    resultado_rg = devengado - deducciones
    c[casilla("Pág. 4", "Resultado régimen general")] = resultado_rg
    _volumen_de_operaciones(apuntes, ejercicio, r)
    # --- resultado de la liquidación anual y de las autoliquidaciones del año
    trimestrales = _resultados_303(apuntes, ejercicio, saldo_compensar_inicial, declaraciones_303, {k: v for k, v in ajustes.items()})
    compensado = sum(t["casillas"].get("78", 0) for t in trimestrales)
    c[casilla("Pág. 6", "Resultado liquidación anual", "Suma de resultados")] = resultado_rg
    if compensado:
        c[casilla("Pág. 6", "Compensación de cuotas ejercicio anterior")] = compensado
    c[casilla("Pág. 6", "Resultado liquidación anual", "Resultado de la liquidación")] = resultado_rg - compensado
    c[casilla("Pág. 6", "Territorio común")] = 10000
    c[casilla("Pág. 6", "Resultado atribuible a territorio común")] = resultado_rg
    if compensado:
        c[casilla("Pág. 6", "Compens. cuotas ej. anterior atrib.")] = compensado
    c[casilla("Pág. 6", "Resultado liq. anual atribuible territ. comun")] = resultado_rg - compensado
    c[casilla("Pág. 6", "Total resultados a ingresar autoliquidaciones")] = sum(t["casillas"].get("71", 0) for t in trimestrales if t["casillas"].get("71", 0) > 0)
    ultimo = trimestrales[-1]
    if ultimo["casillas"].get("71", 0) < 0:
        k = casilla("Pág. 6", "último periodo - A devolver") if ultimo["tipo_declaracion"] == "D" else casilla("Pág. 6", "último periodo - A compensar")
        c[k] = -ultimo["casillas"]["71"]
    r.casillas = {k: v for k, v in c.items() if v != 0 or k in (casilla("Pág. 4", "Resultado régimen general"), casilla("Pág. 2", "Total bases y cuotas IVA", final="Base"), casilla("Pág. 2", "Total bases y cuotas IVA", final="Cuota"))}
    r.avisos.extend(_cuadre_con_los_303(r, trimestrales, devengado, deducciones))
    return r


def _cuadre_con_los_303(r: Resultado390, trimestrales: list[dict], devengado: int, deducciones: int) -> list[str]:
    """El 390 tiene que cuadrar con la suma de los cuatro 303 (casillas 27 y 45). Si no, se dice cuál es la diferencia: o falta corregir una declaración, o el cálculo anual no coincide con lo declarado."""
    avisos = []
    s27 = sum(t["casillas"].get("27", 0) for t in trimestrales)
    s45 = sum(t["casillas"].get("45", 0) for t in trimestrales)
    if s27 != devengado:
        avisos.append(f"El IVA devengado del año ({devengado / 100:.2f} €) no coincide con la suma de los cuatro 303 ({s27 / 100:.2f} €).")
    if s45 != deducciones:
        avisos.append(f"El IVA deducible del año ({deducciones / 100:.2f} €) no coincide con la suma de los cuatro 303 ({s45 / 100:.2f} €).")
    sin_declarar = [t["periodo"] for t in trimestrales if not t["de_declaracion"]]
    if sin_declarar:
        avisos.append("Sin declaración revisada del 303 en: " + ", ".join(sin_declarar) + " (se han calculado ahora a partir de los apuntes).")
    return avisos
