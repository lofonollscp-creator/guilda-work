"""Lectura del diseño de registro OFICIAL de la AEAT (hoja de cálculo `DR303e26v101.xlsx`) a una estructura que el exportador usa y las pruebas verifican.

Regla de la casa (docs/plan-modulo-fiscal-alquileres.md §5): **las posiciones, longitudes y constantes no se escriben nunca de memoria**: salen de este fichero oficial, con su huella
(sha256) guardada junto al resultado. Si la AEAT publica otra revisión, se descarga, se regenera el JSON y las pruebas dicen qué ha cambiado.

Cada hoja `DP303xx` es una página del fichero (`<T303xxxxx>` … `</T303xxxxx>`): una tabla `Nº · Posic. · Lon · Tipo · [Comp] · Descripción · Validación · Contenido`, una fila TOTAL con las
posiciones de la página y unas notas. La hoja `DP30300` es la envoltura del fichero entero (`<T3030EEEEPP0000>` … `</T3030EEEEPP0000>`)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ESQUEMA = 1


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor).replace("\xa0", " ")).strip()


def _entero(valor):
    t = _texto(valor)
    return int(t) if re.fullmatch(r"\d+", t) else None


def _cabecera(fila) -> dict[str, int] | None:
    nombres = [_texto(c).lower() for c in fila]
    if not nombres or nombres[0] not in ("nº", "n°", "no", "n.º") or "lon" not in nombres:
        return None
    mapa = {}
    for i, n in enumerate(nombres):
        clave = {"nº": "n", "n°": "n", "no": "n", "n.º": "n", "posic.": "pos", "lon": "lon", "tipo": "tipo", "comp": "comp", "descripción": "descripcion",
                 "validación": "validacion", "contenido": "contenido"}.get(n)
        if clave and clave not in mapa:
            mapa[clave] = i
    return mapa


def leer_hoja(ws) -> dict:
    """La tabla de una hoja: campos, total declarado y notas. No interpreta nada: copia lo que dice el diseño."""
    filas = [tuple(c for c in f) for f in ws.iter_rows(values_only=True, max_col=10)]
    cab, mapa = None, None
    for i, f in enumerate(filas):
        mapa = _cabecera(f)
        if mapa:
            cab = i
            break
    if cab is None:
        raise ValueError(f"la hoja {ws.title} no tiene la tabla de registro (Nº, Posic., Lon, Tipo…)")
    campos, total, notas, en_tabla = [], None, [], True
    for f in filas[cab + 1:]:
        if not any(_texto(c) for c in f):
            continue
        primera = _texto(f[0])
        if en_tabla and primera.upper() == "TOTAL":
            total = _entero(f[mapa["lon"]])
            en_tabla = False
            continue
        if not en_tabla:
            notas.append(" | ".join(t for t in (_texto(c) for c in f) if t))
            continue
        pos_bruta, lon_bruta = _texto(f[mapa["pos"]]), _texto(f[mapa["lon"]])
        campos.append({
            "n": _entero(primera) if _entero(primera) is not None else primera,
            "pos": _entero(pos_bruta) if _entero(pos_bruta) is not None else pos_bruta,
            "lon": _entero(lon_bruta) if _entero(lon_bruta) is not None else lon_bruta,
            "tipo": _texto(f[mapa["tipo"]]),
            "comp": _texto(f[mapa["comp"]]) if "comp" in mapa else "",
            "descripcion": _texto(f[mapa["descripcion"]]),
            "validacion": _texto(f[mapa["validacion"]]),
            "contenido": _texto(f[mapa["contenido"]]),
        })
    return {"hoja": ws.title, "campos": campos, "total_posiciones": total, "notas": notas}


def leer_diseno(ruta_xlsx: str | Path) -> dict:
    import openpyxl

    ruta = Path(ruta_xlsx)
    huella = hashlib.sha256(ruta.read_bytes()).hexdigest()
    wb = openpyxl.load_workbook(ruta, data_only=True)
    paginas = [leer_hoja(ws) for ws in wb.worksheets]
    cabecera = paginas[0]["hoja"]
    return {"esquema": ESQUEMA, "origen": {"fichero": ruta.name, "sha256": huella, "bytes": ruta.stat().st_size}, "envoltura": cabecera, "paginas": paginas}


def comprobar(diseno: dict) -> list[str]:
    """Incoherencias del propio diseño (lista vacía = coherente): posiciones contiguas desde 1, suma de longitudes igual al TOTAL declarado y marcas de inicio y fin."""
    problemas = []
    for p in diseno["paginas"]:
        if p["hoja"] == diseno["envoltura"]:
            continue
        esperada = 1
        for c in p["campos"]:
            if not isinstance(c["pos"], int) or not isinstance(c["lon"], int):
                problemas.append(f"{p['hoja']} campo {c['n']}: posición/longitud no numérica ({c['pos']!r}/{c['lon']!r})")
                continue
            if c["pos"] != esperada:
                problemas.append(f"{p['hoja']} campo {c['n']}: empieza en {c['pos']} y debería en {esperada}")
            esperada = c["pos"] + c["lon"]
        if p["total_posiciones"] is not None and esperada - 1 != p["total_posiciones"]:
            problemas.append(f"{p['hoja']}: los campos suman {esperada - 1} posiciones y el TOTAL declarado es {p['total_posiciones']}")
        if not p["campos"] or '"<T"' not in p["campos"][0]["contenido"].replace(" ", "") and "<T" not in p["campos"][0]["contenido"]:
            problemas.append(f"{p['hoja']}: no empieza con la marca «<T»")
        if "</T" not in p["campos"][-1]["contenido"]:
            problemas.append(f"{p['hoja']}: no acaba con la marca «</T…>»")
    return problemas


_CASILLA = re.compile(r"\[(\d{2,3})\]\s*\.?\s*$")


def indice_casillas(diseno: dict) -> dict[str, list[dict]]:
    """`{casilla: [campo…]}`: los campos del fichero cuya descripción ACABA en «[nnn]» (el diseño oficial nombra así la casilla del formulario; los «[nnn]» de dentro de una fórmula son
    referencias a otras casillas y no definen el campo). Una casilla puede aparecer en varias páginas o repetirse en páginas complementarias, por eso es una lista; cada campo lleva su `hoja`."""
    indice: dict[str, list[dict]] = {}
    for p in diseno["paginas"]:
        for c in p["campos"]:
            m = _CASILLA.search(c["descripcion"])
            if m:
                indice.setdefault(m.group(1), []).append({**c, "hoja": p["hoja"]})
    return indice
