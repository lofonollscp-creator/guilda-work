"""Del resultado del motor (casillas del 390) al fichero importable por la AEAT, a partir del diseño OFICIAL `disenos/390_2025.json` (`dr390e2025.xlsx`, actualizado 05/12/2025). Reutiliza el formato de
campos de `exportador_303` (mismas reglas: `An`, `Num`, `N` con la «N» de negativo). Qué páginas lleva: la 1 (identificación), la 2 (IVA devengado), la 3 y la 4 (IVA deducible y resultado del régimen
general) y la 6 (resultado de la liquidación anual y volumen de operaciones); las demás solo se incluyen si hay contenido que declarar y hoy no se calcula ninguno.

El fichero es **de prueba**: no hay todavía un `.390` exportado por el propio formulario de la AEAT con el que contrastar byte a byte (como se hizo con el 303), así que se importa en el simulador o en el
formulario de la AEAT para comprobarlo y NO se presenta tal cual."""
from __future__ import annotations

import json
from decimal import Decimal

from . import exportador_303 as ex
from .disenos_oficiales import indice_casillas
from .motor_390 import DISENO_390, Resultado390

PAGINAS = ("Pág. 1", "Pág. 2", "Pág. 3", "Pág. 4", "Pág. 6")


class FicheroNoGenerable(ValueError):
    pass


def cargar_diseno() -> dict:
    return json.loads(DISENO_390.read_text(encoding="utf-8"))


def _identificacion(nif: str, nombre: str, ejercicio: int, *, declaracion_anual_terceros: bool = False) -> dict:
    """Página 1. Los indicadores van como en un titular de régimen general, sin grupo, sin concurso y sin criterio de caja (lo contrario se bloquea en el motor)."""
    if len(nombre) > 60:
        raise FicheroNoGenerable(f"El nombre o razón social tiene {len(nombre)} caracteres y el diseño del 390 admite 60.")
    return {7: nif, 8: nombre, 10: str(ejercicio), 12: "0", 13: "0", 15: "0", 16: "0", 17: "0", 19: "2", 20: "2", 21: "2", 22: "0", 23: "0", 43: "1" if declaracion_anual_terceros else "0"}


def paginas_desde(diseno: dict, r: Resultado390, *, nif: str, nombre: str, declaracion_anual_terceros: bool = False) -> dict[str, dict]:
    if not r.calculable:
        raise FicheroNoGenerable("El cálculo está bloqueado: " + " · ".join(r.bloqueos[:3]))
    indice = indice_casillas(diseno)
    paginas: dict[str, dict] = {h: {} for h in PAGINAS}
    paginas["Pág. 1"] = _identificacion(nif, nombre, r.ejercicio, declaracion_anual_terceros=declaracion_anual_terceros)
    for casilla, valor in r.casillas.items():
        apariciones = indice.get(casilla)
        if not apariciones:
            raise FicheroNoGenerable(f"La casilla {casilla} no existe en el diseño oficial.")
        for a in apariciones:
            if a["hoja"] not in paginas:
                raise FicheroNoGenerable(f"La casilla {casilla} está en la página {a['hoja']}, que este fichero no incluye.")
            paginas[a["hoja"]][a["n"]] = Decimal(valor) / 100          # importes en euros con 2 decimales y porcentajes (centésimas) ya con su escala: el formato lo ajusta al campo
    return paginas


def construir(diseno: dict, paginas: dict[str, dict], *, ejercicio: int, version_programa: str | None = None, nif_empresa_desarrollo: str | None = None, codificacion: str = "iso-8859-15",
              salto_de_linea: str = "") -> bytes:
    """La envoltura `<T3900EEEE0A0000><AUX>…</AUX>` + páginas + `</T3900EEEE0A0000>` según la hoja «Pág. 0» del diseño."""
    if not 2025 <= ejercicio <= 9999:
        raise ex.ErrorDeFormato("este diseño es para el ejercicio 2025 y siguientes")
    envoltura = next(p for p in diseno["paginas"] if p["hoja"] == diseno["envoltura"])
    por_hoja = {p["hoja"]: p for p in diseno["paginas"]}
    campos = {c["n"]: c for c in envoltura["campos"]}
    version_programa = ex.VERSION_PROGRAMA if version_programa is None else version_programa
    nif_empresa_desarrollo = ex.NIF_ENTIDAD_DESARROLLADORA if nif_empresa_desarrollo is None else nif_empresa_desarrollo
    cabecera = "".join([
        ex.formatear(campos[1], None), ex.formatear(campos[2], None), ex.formatear(campos[3], None), ex.formatear(campos[4], str(ejercicio)), ex.formatear(campos[5], "0A"),
        ex.formatear(campos[6], None), ex.formatear(campos[7], None), ex.formatear(campos[8], None), str(version_programa)[:campos[9]["lon"]].ljust(campos[9]["lon"]),
        ex.formatear(campos[10], None), ex.formatear(campos[11], nif_empresa_desarrollo), ex.formatear(campos[12], None), ex.formatear(campos[13], None)])
    orden = [p["hoja"] for p in diseno["paginas"]]
    cuerpo = salto_de_linea.join(ex._pagina(por_hoja[h], v) for h, v in sorted(paginas.items(), key=lambda x: orden.index(x[0])))
    cierre = f"</T3900{ejercicio}0A0000>"
    return (cabecera + salto_de_linea + cuerpo + salto_de_linea + cierre).encode(codificacion)


def generar(r: Resultado390, *, nif: str, nombre: str, declaracion_anual_terceros: bool = False, diseno: dict | None = None) -> bytes:
    diseno = diseno or cargar_diseno()
    return construir(diseno, paginas_desde(diseno, r, nif=nif, nombre=nombre, declaracion_anual_terceros=declaracion_anual_terceros), ejercicio=r.ejercicio)


def leer_casillas(diseno: dict, datos: bytes, *, codificacion: str = "iso-8859-15") -> dict[str, int]:
    """Los valores numéricos de las casillas de un fichero `.390` (el nuestro o uno exportado por la AEAT) como enteros: importes en céntimos con signo y porcentajes en centésimas. Solo los distintos de
    cero. Sirve para comprobar que lo escrito es lo calculado y, con un fichero oficial, para compararlo con el motor."""
    texto = datos.decode(codificacion)
    envoltura = next(p for p in diseno["paginas"] if p["hoja"] == diseno["envoltura"])
    pos = 328                                                       # cabecera fija de la «Pág. 0» (campos 1 a 13); el contenido empieza justo después
    por_id = {}
    for p in diseno["paginas"][1:]:
        por_id[next(c["contenido"].split('"')[1] for c in p["campos"][:4] if c["contenido"].startswith("Constante") and c["lon"] == 5)] = p
    salida: dict[str, int] = {}
    indice = indice_casillas(diseno)
    por_campo = {(a["hoja"], a["n"]): k for k, apariciones in indice.items() for a in apariciones}
    while texto[pos:pos + 5] == "<T390":
        pagina = por_id[texto[pos + 5:pos + 10]]
        bloque, p0 = texto[pos:pos + pagina["total_posiciones"]], 0
        for c in pagina["campos"]:
            valor = bloque[p0:p0 + c["lon"]]
            p0 += c["lon"]
            k = por_campo.get((pagina["hoja"], c["n"]))
            if k is None or c["tipo"].strip() not in ("Num", "N") or not valor.strip():
                continue
            negativo = valor.startswith("N")
            cifras = valor[1:] if negativo else valor
            if cifras.isdigit() and int(cifras):
                salida[k] = int(cifras) * (-1 if negativo else 1)
        pos += pagina["total_posiciones"]
    return salida
