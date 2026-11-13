"""Evaluación de la lectura de facturas (W8): una lista de casos con la respuesta correcta y una medida de acierto por campo, para comparar modelos y detectar cuándo un cambio de modelo o de prompt empeora la lectura.

No llama a ningún modelo por sí mismo: `ejecutar` recibe una función `leer(texto) -> dict` (el script `scripts/evaluar_facturas.py` pone la de producción; las pruebas, una falsa). Los casos de `tests/evals/facturas_casos.json`
son SINTÉTICOS (NIF y cifras inventados): ninguna factura real sale de la base de datos hacia un fichero de pruebas."""
from __future__ import annotations

import json
import re
from pathlib import Path

CAMPOS = ("numero", "fecha", "emisor_nif", "receptor_nif", "total", "es_abono", "lineas")
CASOS = Path(__file__).resolve().parent.parent / "tests" / "evals" / "facturas_casos.json"
TOLERANCIA = 0.01


def cargar_casos(ruta: Path | str | None = None) -> list[dict]:
    return json.loads(Path(ruta or CASOS).read_text(encoding="utf-8"))["casos"]


def _nif(v) -> str | None:
    from .lectura_nif import sin_es
    return sin_es(v) or None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _igual_num(a, b) -> bool:
    x, y = _num(a), _num(b)
    return x is not None and y is not None and abs(x - y) <= TOLERANCIA


def _lineas_iguales(esperadas, obtenidas) -> bool:
    """Mismas líneas sin importar el orden: cada tipo de IVA con su base y su cuota (y la retención si el caso la espera)."""
    if not isinstance(obtenidas, list) or len(esperadas) != len(obtenidas):
        return False
    clave = lambda l: (_num(l.get("pct_iva")) or 0, _num(l.get("base")) or 0)
    for e, o in zip(sorted(esperadas, key=clave), sorted((x for x in obtenidas if isinstance(x, dict)), key=clave)):
        if not (_igual_num(e["base"], o.get("base")) and _igual_num(e["pct_iva"], o.get("pct_iva")) and _igual_num(e["cuota_iva"], o.get("cuota_iva"))):
            return False
        if "pct_retencion" in e and not _igual_num(e["pct_retencion"], o.get("pct_retencion")):
            return False
    return True


def puntuar(esperado: dict, obtenido: dict | None) -> dict[str, bool]:
    """Acierto de cada campo esperado (los que el caso no define no se miden)."""
    o = obtenido or {}
    r: dict[str, bool] = {}
    for c in CAMPOS:
        if c not in esperado:
            continue
        e = esperado[c]
        if c in ("emisor_nif", "receptor_nif"):
            r[c] = _nif(e) == _nif(o.get(c))
        elif c == "total":
            r[c] = _igual_num(e, o.get(c))
        elif c == "es_abono":
            r[c] = bool(e) == bool(o.get(c))
        elif c == "lineas":
            r[c] = _lineas_iguales(e, o.get(c))
        else:
            r[c] = str(e or "").strip() == str(o.get(c) or "").strip()
    return r


def ejecutar(casos: list[dict], leer) -> dict:
    """Pasa cada caso por `leer` y resume: `{casos, acierto_global, por_campo: {campo: %}, fallos: [{caso, campos}], errores: [{caso, error}]}`. Un caso que lanza error cuenta como fallo de todos sus campos."""
    totales: dict[str, list[bool]] = {}
    fallos, errores = [], []
    for c in casos:
        try:
            puntos = puntuar(c["esperado"], leer(c["texto"]))
        except Exception as e:  # noqa: BLE001 -- un caso roto no para la evaluación
            errores.append({"caso": c["id"], "error": str(e)[:200]})
            puntos = {k: False for k in puntuar(c["esperado"], {})}
        for campo, ok in puntos.items():
            totales.setdefault(campo, []).append(ok)
        malos = [k for k, ok in puntos.items() if not ok]
        if malos:
            fallos.append({"caso": c["id"], "campos": malos})
    todos = [ok for v in totales.values() for ok in v]
    return {"casos": len(casos), "acierto_global": round(100 * sum(todos) / len(todos), 1) if todos else 0.0,
            "por_campo": {k: round(100 * sum(v) / len(v), 1) for k, v in sorted(totales.items())}, "fallos": fallos, "errores": errores}


def comparar(actual: dict, base: dict, margen: float = 2.0) -> list[str]:
    """Los campos (y el global) cuyo acierto ha bajado más de `margen` puntos respecto a una evaluación anterior. Vacío = no hay regresión."""
    peores = []
    if actual["acierto_global"] < base["acierto_global"] - margen:
        peores.append(f"global: {base['acierto_global']} → {actual['acierto_global']}")
    for campo, antes in base["por_campo"].items():
        ahora = actual["por_campo"].get(campo)
        if ahora is not None and ahora < antes - margen:
            peores.append(f"{campo}: {antes} → {ahora}")
    return peores


def leer_con_ia(usuario_id: int):
    """La función `leer` de producción (texto de la factura → datos) con el modelo configurado de esa persona (la usan scripts/evaluar_facturas.py y scripts/calidad_ia.py)."""
    from . import ia_asistente, lectura_facturas, lectura_nif

    def leer(texto: str) -> dict:
        datos = lectura_facturas._json_de(ia_asistente.completar_partes(usuario_id, lectura_facturas.PROMPT_TEXTO, [{"type": "text", "text": "Extrae los datos de esta factura.\n\nTEXTO DEL DOCUMENTO:\n" + texto}]))
        lectura_nif.completar(datos, texto)              # igual que en producción: el NIF que el modelo deja vacío se busca en el texto
        return datos
    return leer
