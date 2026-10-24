"""Exportador del fichero importable del modelo 303 (ejercicio 2026 y siguientes) a partir del diseño de registro OFICIAL ya extraído (`disenos/303_2026_v101.json`).

NUNCA se escriben posiciones, longitudes ni constantes a mano: todo sale del diseño. Este módulo solo sabe **rellenar** campos con un valor según su tipo (reglas de la Nota 2 de cada hoja) y
**componer** la envoltura `<T3030EEEEPP0000>…</T3030EEEEPP0000>`. Qué valor lleva cada casilla lo decide el motor de cálculo (F4), no este módulo.

Lo que NO está verificado todavía (docs/fiscal-f0-informe.md §5, fiscal-vias-aeat.md §5) y por eso es un PARÁMETRO, no una constante: la **codificación** de caracteres y los **saltos de línea**
del fichero. Se fijan con un `.303` exportado por el propio formulario de la AEAT. Hasta entonces, un fichero de aquí es **de prueba**: se importa en el simulador, nunca se presenta.

Reglas de formato del diseño (Nota 2): `An`/`A` alineado a la izquierda con blancos; `Num` a la derecha con ceros, sin signo; `N` con signo: a la derecha con ceros y, si es **negativo**, una `N` en la
PRIMERA posición del campo. Los importes («15 enteros y 2 decimales») ocupan 17 posiciones **sin separador decimal**."""
from __future__ import annotations

import json
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

DISENO_303_2026 = Path(__file__).resolve().parent / "disenos" / "303_2026_v101.json"
PERIODOS = tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T")
ULTIMOS = ("12", "4T")
TIPOS_DECLARACION = ("C", "D", "G", "I", "N", "V", "U", "X")          # Nota 1 de la página 1


class ErrorDeFormato(ValueError):
    """Un valor no cabe o no vale para su campo: se rechaza, no se recorta en silencio."""


def cargar_diseno(ruta: str | Path = DISENO_303_2026) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


_CONSTANTE = re.compile(r'^\s*(?:Constante\s*)?"([^"]*)"\s*$')
_DECIMALES = re.compile(r"(\d+)\s+enteros?\s+y\s+(\d+)\s+decimales?", re.I)


def _constante(campo: dict) -> str | None:
    """El texto fijo de un campo, si el diseño lo da entre comillas (con o sin la palabra «Constante»)."""
    m = _CONSTANTE.match(campo["contenido"])
    return m.group(1) if m else None


def _en_blanco(campo: dict) -> bool:
    c = campo["contenido"].strip().lower()
    return c in ("blancos", "en blanco") or campo["descripcion"].lower().startswith("reservado")


def _decimales(campo: dict) -> int:
    m = _DECIMALES.search(campo["contenido"])
    return int(m.group(2)) if m else 0


def limpiar_texto(valor: str) -> str:
    """Los campos alfanuméricos solo admiten letras, números y blancos (Nota 2): sin tildes ni signos; en mayúsculas, como en el resto de la presentación electrónica."""
    s = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"[^A-Z0-9 ]", " ", s)


def formatear(campo: dict, valor) -> str:
    """El valor ya ajustado a la longitud y alineación del campo. `None` = el valor por defecto del campo (constante, blancos o ceros)."""
    lon, tipo = campo["lon"], campo["tipo"].strip()
    fija = _constante(campo)
    if valor is None:
        if fija is not None:
            valor = fija
        elif _en_blanco(campo) or tipo in ("An", "A"):
            valor = ""
        else:
            valor = 0
    if tipo in ("An", "A"):
        texto = limpiar_texto(valor) if fija is None or valor != fija else str(valor)
        if len(texto) > lon:
            raise ErrorDeFormato(f"campo {campo['n']} ({campo['descripcion'][:50]}): «{texto}» tiene {len(texto)} caracteres y caben {lon}")
        return texto.ljust(lon)
    # Num / N
    if isinstance(valor, str) and fija is not None and valor == fija:
        return valor.rjust(lon, "0")
    if isinstance(valor, str) and valor.strip() == "":
        return " " * lon                                              # un indicador numérico que el diseño pide EN BLANCO (p. ej. Nota 6 en periodos que no son el último)
    dec = _decimales(campo)
    d = Decimal(str(valor)) if not isinstance(valor, Decimal) else valor
    entero = int((d * (10 ** dec)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    negativo = entero < 0
    if negativo and tipo != "N":
        raise ErrorDeFormato(f"campo {campo['n']} ({campo['descripcion'][:50]}): es numérico SIN signo y el valor es negativo ({valor})")
    cifras = str(abs(entero))
    cabida = lon - (1 if negativo else 0)
    if len(cifras) > cabida:
        raise ErrorDeFormato(f"campo {campo['n']} ({campo['descripcion'][:50]}): {valor} no cabe en {lon} posiciones")
    return ("N" + cifras.rjust(cabida, "0")) if negativo else cifras.rjust(lon, "0")


def _pagina(pagina: dict, valores: dict) -> str:
    """Una página completa. `valores`: `{n_de_campo: valor}` (entero) o `{casilla: valor}` (texto como «150»); lo que no se da lleva su valor por defecto."""
    por_casilla = {}
    for c in pagina["campos"]:
        m = re.search(r"\[(\d{2,3})\]\s*$", c["descripcion"])
        if m:
            por_casilla[m.group(1)] = c
    usados = set()
    partes = []
    for c in pagina["campos"]:
        v = valores.get(c["n"])
        if v is not None:
            usados.add(c["n"])
        partes.append(formatear(c, v))
    for clave, v in valores.items():
        if isinstance(clave, str):
            campo = por_casilla.get(clave)
            if campo is None:
                raise ErrorDeFormato(f"la casilla [{clave}] no existe en la página {pagina['hoja']}")
            partes[pagina["campos"].index(campo)] = formatear(campo, v)
        elif clave not in {c["n"] for c in pagina["campos"]}:
            raise ErrorDeFormato(f"el campo {clave} no existe en la página {pagina['hoja']}")
    texto = "".join(partes)
    if len(texto) != pagina["total_posiciones"]:
        raise ErrorDeFormato(f"la página {pagina['hoja']} mide {len(texto)} y el diseño dice {pagina['total_posiciones']}")
    return texto


def indicadores_pagina1(periodo: str, *, prorrata_especial: str | None = None, revocacion_prorrata: str | None = None) -> dict:
    """Los valores que el diseño fija según el PERIODO en la identificación de la página 1 (Notas 3, 4, 6 y 8), para un titular que NO tributa a una Administración foral, en régimen general
    (solo RG), sin autoliquidación conjunta, sin criterio de caja, fuera del SII y no exonerado del 390. Lo demás (perfil real del titular) lo aporta el motor. SUPUESTOS marcados con ↯ se
    comprueban en el simulador: la Nota 6 se lee como «en blanco salvo en el último periodo»."""
    ultimo = periodo in ULTIMOS
    return {
        11: "2",                        # tributación exclusivamente foral: NO
        12: "2",                        # registro de devolución mensual: NO
        13: "3",                        # solo régimen general
        14: "2",                        # autoliquidación conjunta: NO
        15: "2",                        # criterio de caja: NO
        16: "2",                        # destinatario de operaciones en criterio de caja: NO
        17: (prorrata_especial or ("2" if ultimo else " ")),            # ↯ Nota 6
        18: (revocacion_prorrata or ("2" if ultimo else " ")),          # ↯ Nota 6
        19: "2",                        # concurso: NO
        22: "2",                        # SII: NO
        23: "2" if ultimo else "0",     # exonerado del 390 (Nota 4)
        24: "2" if ultimo else "0",     # volumen de operaciones distinto de cero (Nota 3) ↯ en el último periodo hay que declararlo
        25: "0" if periodo in ("1T", "2T", "3T", "4T", "01") else "2",   # pago a cuenta de carburantes (Nota 8)
    }


def construir(diseno: dict, *, ejercicio: int, periodo: str, paginas: dict[str, dict], version_programa: str = "", nif_empresa_desarrollo: str = "",
              codificacion: str = "iso-8859-15", salto_de_linea: str = "") -> bytes:
    """El fichero completo. `paginas`: `{"DP30301": {valores…}, "DP30303": {…}}` en el orden en que van en el fichero (las hojas del diseño son las páginas)."""
    if periodo not in PERIODOS:
        raise ErrorDeFormato(f"periodo no válido: {periodo!r} (01…12 o 1T…4T)")
    if not 2026 <= ejercicio <= 9999:
        raise ErrorDeFormato("este diseño es para ejercicios 2026 y siguientes")
    envoltura = next(p for p in diseno["paginas"] if p["hoja"] == diseno["envoltura"])
    por_hoja = {p["hoja"]: p for p in diseno["paginas"]}
    contenido = salto_de_linea.join(_pagina(por_hoja[h], v) for h, v in paginas.items())
    campos = {c["n"]: c for c in envoltura["campos"]}
    cabecera = "".join([
        formatear(campos[1], None), formatear(campos[2], None), formatear(campos[3], None),
        formatear(campos[4], str(ejercicio)), formatear(campos[5], periodo), formatear(campos[6], None),
        formatear(campos[7], None), formatear(campos[8], None), formatear(campos[9], version_programa), formatear(campos[10], None),
        formatear(campos[11], nif_empresa_desarrollo), formatear(campos[12], None), formatear(campos[13], None)])
    cierre = f"</T3030{ejercicio}{periodo}0000>"
    return (cabecera + salto_de_linea + contenido + salto_de_linea + cierre).encode(codificacion)


def descomponer(diseno: dict, datos: bytes, *, codificacion: str = "iso-8859-15") -> dict:
    """Lee un fichero `.303` con el diseño: `{"cabecera": {...}, "paginas": [{"hoja", "campos": {n: texto}}]}`. Sirve para comprobar lo que construimos y, sobre todo, **para analizar un `.303`
    exportado por el formulario oficial** (codificación, saltos de línea, qué páginas lleva). No valida: describe."""
    texto = datos.decode(codificacion)
    envoltura = next(p for p in diseno["paginas"] if p["hoja"] == diseno["envoltura"])
    cab = {}
    pos = 0
    for c in envoltura["campos"]:
        if not isinstance(c["lon"], int):
            break
        cab[c["n"]] = texto[pos:pos + c["lon"]]
        pos += c["lon"]
    resto = texto[pos:]
    paginas = []
    indice = 0
    while True:
        m = re.match(r"(\r?\n)?<T303(\w{5})>", resto[indice:])
        if not m:
            break
        pagina_id = m.group(2)
        hoja = next((p for p in diseno["paginas"][1:] if any(_constante(c) == pagina_id for c in p["campos"][:4])), None)
        if hoja is None:
            raise ErrorDeFormato(f"página desconocida: {pagina_id}")
        indice += len(m.group(1) or "")
        bloque = resto[indice:indice + hoja["total_posiciones"]]
        campos, p0 = {}, 0
        for c in hoja["campos"]:
            campos[c["n"]] = bloque[p0:p0 + c["lon"]]
            p0 += c["lon"]
        paginas.append({"hoja": hoja["hoja"], "campos": campos})
        indice += hoja["total_posiciones"]
    return {"cabecera": cab, "paginas": paginas, "cola": resto[indice:]}
