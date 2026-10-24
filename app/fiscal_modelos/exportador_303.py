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
# Quién DESARROLLA el programa que genera el fichero (campos 9 y 11 de la envoltura). No es quien presenta: la presentación la hace el colaborador social o el obligado con su certificado.
NIF_ENTIDAD_DESARROLLADORA = ""                                      # vacío por ahora (decisión de Jorge, 25-oct-2026); GUILDA ASSESSORS HISTORICS SL sería B16406233
VERSION_PROGRAMA = ""                                                # vacío por ahora; cuando se use: 4 posiciones, con el punto (la propia AEAT escribe «1.06»), p. ej. «1.00»; subir al cambiar el cálculo o el diseño
PERIODOS = tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T")
ULTIMOS = ("12", "4T")
TIPOS_DECLARACION = ("C", "D", "G", "I", "N", "V", "U", "X")          # Nota 1 de la página 1


class ErrorDeFormato(ValueError):
    """Un valor no cabe o no vale para su campo: se rechaza, no se recorta en silencio."""


def cargar_diseno(ruta: str | Path = DISENO_303_2026) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


_CONSTANTE = re.compile(r'^\s*(?:Constante\s*"([^"]*)"|"([^"]*)"\s*\.?\s*(?:Nota\s*\d+\.?\s*)*$)')   # «Constante "00400". Nota 7» · «"0000>"» · «"00050". Nota 7.» (pero NO «"1" SI, "2" NO»)
_DECIMALES = re.compile(r"(\d+)\s+enteros?\s+y\s+(\d+)\s+decimales?", re.I)


def _constante(campo: dict) -> str | None:
    """El texto fijo de un campo, si el diseño lo da entre comillas (con o sin la palabra «Constante»)."""
    m = _CONSTANTE.match(campo["contenido"])
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else None


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
    (solo RG), sin autoliquidación conjunta, sin criterio de caja, fuera del SII y no exonerado del 390. Lo demás (perfil real del titular) lo aporta el motor. Los valores se han
    contrastado con el simulador de la AEAT (docs/fiscal-vias-aeat.md §4d)."""
    ultimo = periodo in ULTIMOS
    return {
        11: "2",                        # tributación exclusivamente foral: NO
        12: "2",                        # registro de devolución mensual: NO
        13: "3",                        # solo régimen general
        14: "2",                        # autoliquidación conjunta: NO
        15: "2",                        # criterio de caja: NO
        16: "2",                        # destinatario de operaciones en criterio de caja: NO
        17: prorrata_especial or "2",   # Nota 6: «2» (en periodos que no son el último el diseño lo llama «blanco», pero el simulador rechaza un blanco real: E010170)
        18: revocacion_prorrata or "2", # ídem (E010180)
        19: "2",                        # concurso: NO
        20: "00000000",                 # fecha del auto de concurso: la AEAT escribe ceros, no blancos, cuando no hay concurso (comparado con su propio «Exportar»)
        22: "2",                        # SII: NO
        23: "2" if ultimo else "0",     # exonerado del 390 (Nota 4)
        24: "2" if ultimo else "0",     # volumen de operaciones distinto de cero (Nota 3) ↯ en el último periodo hay que declararlo
        25: "0" if periodo in ("1T", "2T", "3T", "4T", "01") else "2",   # pago a cuenta de carburantes (Nota 8)
    }


def _orden(diseno: dict, hoja: str) -> int:
    return [p["hoja"] for p in diseno["paginas"]].index(hoja)


def construir(diseno: dict, *, ejercicio: int, periodo: str, paginas: dict[str, dict], version_programa: str | None = None, nif_empresa_desarrollo: str | None = None,
              codificacion: str = "iso-8859-15", salto_de_linea: str = "") -> bytes:
    """El fichero completo. `paginas`: `{"DP30301": {valores…}, "DP30303": {…}}` en el orden en que van en el fichero (las hojas del diseño son las páginas)."""
    version_programa = VERSION_PROGRAMA if version_programa is None else version_programa
    nif_empresa_desarrollo = NIF_ENTIDAD_DESARROLLADORA if nif_empresa_desarrollo is None else nif_empresa_desarrollo
    if periodo not in PERIODOS:
        raise ErrorDeFormato(f"periodo no válido: {periodo!r} (01…12 o 1T…4T)")
    if not 2026 <= ejercicio <= 9999:
        raise ErrorDeFormato("este diseño es para ejercicios 2026 y siguientes")
    envoltura = next(p for p in diseno["paginas"] if p["hoja"] == diseno["envoltura"])
    por_hoja = {p["hoja"]: p for p in diseno["paginas"]}
    paginas = {**paginas}
    paginas.setdefault("DP303DID", {})                                 # la página de domiciliación/devolución VA SIEMPRE (si falta: E060010 en el simulador), aunque vacía
    contenido = salto_de_linea.join(_pagina(por_hoja[h], v) for h, v in sorted(paginas.items(), key=lambda x: _orden(diseno, x[0])))
    campos = {c["n"]: c for c in envoltura["campos"]}
    cabecera = "".join([
        formatear(campos[1], None), formatear(campos[2], None), formatear(campos[3], None),
        formatear(campos[4], str(ejercicio)), formatear(campos[5], periodo), formatear(campos[6], None),
        formatear(campos[7], None), formatear(campos[8], None), str(version_programa)[:campos[9]["lon"]].ljust(campos[9]["lon"]), formatear(campos[10], None),
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


def segmentos(diseno: dict, datos: bytes, *, codificacion: str = "iso-8859-15") -> list[tuple[int, int, str, int | str, str]]:
    """`[(inicio, fin, hoja, n_de_campo, descripción)]` con posiciones ABSOLUTAS (base 0, fin exclusivo) de cada campo de un fichero construido con este diseño. Sirve para decir **qué campo** es el que
    difiere entre dos ficheros (p. ej. el nuestro y el que exporta el simulador de la AEAT)."""
    envoltura = next(p for p in diseno["paginas"] if p["hoja"] == diseno["envoltura"])
    seg, pos = [], 0
    for c in envoltura["campos"]:
        if not isinstance(c["lon"], int):
            break
        seg.append((pos, pos + c["lon"], envoltura["hoja"], c["n"], c["descripcion"]))
        pos += c["lon"]
    texto = datos.decode(codificacion)
    while True:
        m = re.match(r"<T303(\w{5})>", texto[pos:])
        if not m:
            break
        hoja = next(p for p in diseno["paginas"][1:] if any(_constante(c) == m.group(1) for c in p["campos"][:4]))
        for c in hoja["campos"]:
            seg.append((pos, pos + c["lon"], hoja["hoja"], c["n"], c["descripcion"]))
            pos += c["lon"]
    seg.append((pos, len(texto), "cierre", 0, "Cierre de la envoltura"))
    return seg


def campos_distintos(diseno: dict, a: bytes, b: bytes) -> list[tuple[str, int | str, str]]:
    """Los campos (hoja, n, descripción) en los que dos ficheros de la misma estructura difieren."""
    if len(a) != len(b):
        raise ErrorDeFormato(f"los ficheros miden {len(a)} y {len(b)}: no tienen la misma estructura")
    distintos = {i for i, (x, y) in enumerate(zip(a, b)) if x != y}
    return [(h, n, d) for ini, fin, h, n, d in segmentos(diseno, a) if any(i in distintos for i in range(ini, fin))]


def leer_casillas(diseno: dict, datos: bytes, *, codificacion: str = "iso-8859-15") -> dict[str, int]:
    """Los valores NUMÉRICOS de las casillas de un `.303` (el nuestro o el que exporta la AEAT) como enteros: los importes en CÉNTIMOS (con signo: una `N` en la primera posición = negativo) y los
    porcentajes en centésimas. Solo las casillas con valor distinto de cero. Es lo que se compara con lo que calcula nuestro motor."""
    from .disenos_oficiales import indice_casillas
    por_pagina = {p["hoja"]: p["campos"] for p in descomponer(diseno, datos, codificacion=codificacion)["paginas"]}
    salida: dict[str, int] = {}
    for casilla, apariciones in indice_casillas(diseno).items():
        for c in apariciones:
            texto = por_pagina.get(c["hoja"], {}).get(c["n"])
            if texto is None or c["tipo"].strip() not in ("Num", "N") or not texto.strip():
                continue
            negativo = texto.startswith("N")
            digitos = texto[1:] if negativo else texto
            if not digitos.strip().isdigit():
                continue
            valor = int(digitos) * (-1 if negativo else 1)
            if valor:
                salida[casilla] = valor
    return salida
