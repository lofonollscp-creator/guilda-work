"""Importación de datos exportados previamente (JSON o CSV) de vuelta a la
base de datos. Reconoce el mismo formato que genera app/export.py, así que
un archivo exportado desde esta misma app (o desde una copia de seguridad
antigua) se puede volver a cargar sin tocar nada a mano.

Cada fila se valida por separado: si una fila no tiene lo mínimo (texto,
timestamp de inicio válido...) se omite y se cuenta en "omitidos" en vez de
abortar toda la importación por un solo dato mal formado.
"""
import csv
import io
import json
from datetime import datetime

from . import db


class ErrorImportacion(Exception):
    """Error legible para mostrar en la interfaz cuando el archivo no se puede leer."""


def _timestamp_valido(valor) -> bool:
    if not valor:
        return False
    try:
        datetime.fromisoformat(valor)
        return True
    except (ValueError, TypeError):
        return False


def _importar_registro(registro: dict, resumen: dict) -> None:
    origen = registro.get("origen")
    texto = (registro.get("texto_o_nombre") or "").strip()
    categoria_nombre = (registro.get("categoria") or "").strip()
    timestamp_inicio = registro.get("timestamp_inicio")

    if not texto or not _timestamp_valido(timestamp_inicio):
        resumen["omitidos"] += 1
        return

    categoria_id = db.crear_categoria(categoria_nombre) if categoria_nombre else None

    if origen == "nota":
        db.importar_nota(texto, categoria_id, timestamp_inicio)
        resumen["notas"] += 1
        return

    if origen == "tarea":
        if categoria_id is None:
            resumen["omitidos"] += 1
            return
        tipo = registro.get("tipo") or "duracion"
        if tipo == "instantanea":
            db.importar_tarea(texto, categoria_id, "instantanea", timestamp_inicio, None, None)
            resumen["tareas"] += 1
            return

        timestamp_fin = registro.get("timestamp_fin")
        if not _timestamp_valido(timestamp_fin):
            # Una tarea con duración sin fin era una tarea en curso en el
            # momento de exportar: no hay forma segura de importarla como
            # histórico cerrado, así que se omite en vez de inventarse un fin.
            resumen["omitidos"] += 1
            return

        duracion = registro.get("duracion_segundos")
        if not isinstance(duracion, int):
            try:
                inicio = datetime.fromisoformat(timestamp_inicio)
                fin = datetime.fromisoformat(timestamp_fin)
                duracion = max(int((fin - inicio).total_seconds()), 0)
            except ValueError:
                resumen["omitidos"] += 1
                return

        db.importar_tarea(texto, categoria_id, "duracion", timestamp_inicio, timestamp_fin, duracion)
        resumen["tareas"] += 1
        return

    resumen["omitidos"] += 1


def importar_json(contenido: str) -> dict:
    """Devuelve {"notas": N, "tareas": N, "omitidos": N}."""
    resumen = {"notas": 0, "tareas": 0, "omitidos": 0}
    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError as e:
        raise ErrorImportacion(f"El archivo no es un JSON válido: {e}") from e

    registros = datos.get("registros") if isinstance(datos, dict) else None
    if not isinstance(registros, list):
        raise ErrorImportacion("El JSON no tiene el formato esperado (falta la lista \"registros\").")

    for registro in registros:
        if isinstance(registro, dict):
            _importar_registro(registro, resumen)
        else:
            resumen["omitidos"] += 1
    return resumen


def importar_csv(contenido: str) -> dict:
    """Devuelve {"notas": N, "tareas": N, "omitidos": N}."""
    resumen = {"notas": 0, "tareas": 0, "omitidos": 0}
    lector = csv.DictReader(io.StringIO(contenido))
    campos_esperados = {"origen", "texto_o_nombre", "timestamp_inicio"}
    if not campos_esperados.issubset(set(lector.fieldnames or [])):
        raise ErrorImportacion(
            "El CSV no tiene las columnas esperadas "
            "(origen, texto_o_nombre, timestamp_inicio, categoria...)."
        )
    for fila in lector:
        registro = dict(fila)
        duracion = registro.get("duracion_segundos")
        if duracion not in (None, ""):
            try:
                registro["duracion_segundos"] = int(duracion)
            except ValueError:
                registro["duracion_segundos"] = None
        else:
            registro["duracion_segundos"] = None
        if registro.get("timestamp_fin") == "":
            registro["timestamp_fin"] = None
        _importar_registro(registro, resumen)
    return resumen
