"""Cliente de MinIO (Fase MCP: listar buckets/objetos y generar enlaces de
descarga desde un asistente, ver mcp_server.py).

**Única excepción del proyecto al criterio "solo `urllib`"**: el
protocolo de firma de peticiones S3 (AWS Signature V4) es real y
complejo — reinventarlo a mano con `urllib` sería mucho más frágil que
usar el SDK oficial (`minio`, paquete `minio-py`), que es exactamente
para lo que existe. Añadido a `requirements-mcp.txt`, no a
`requirements.txt` (no se empaqueta en el `.exe`, igual que `mcp`).

Auth: MINIO_ROOT_USER/MINIO_ROOT_PASSWORD — las mismas credenciales que
ya usa el contenedor en `docker-compose.yml`, sin generar nada nuevo.
Opcional a propósito, mismo criterio que el resto de app/*.py: sin
`MINIO_ROOT_PASSWORD`, las tools de solo lectura devuelven listas vacías.

`MINIO_S3_ENDPOINT` es el puerto de la API S3 (9000), no el de la
consola web (9001, ya usado por `HERRAMIENTA_MINIO_URL` en
app/herramientas.py) — son dos puertos distintos del mismo contenedor.
"""
import os
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

MINIO_S3_ENDPOINT = os.environ.get("MINIO_S3_ENDPOINT", "127.0.0.1:9000")
MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "guilda_admin")
MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"


class ErrorMinio(Exception):
    """Error legible para mostrar cuando MinIO falla."""


def _cliente() -> Minio | None:
    if not MINIO_ROOT_PASSWORD:
        return None
    return Minio(MINIO_S3_ENDPOINT, access_key=MINIO_ROOT_USER, secret_key=MINIO_ROOT_PASSWORD, secure=MINIO_SECURE)


def listar_buckets() -> list[dict]:
    """Lista los buckets existentes. [] si MINIO_ROOT_PASSWORD no está
    configurada."""
    cliente = _cliente()
    if cliente is None:
        return []
    try:
        return [{"nombre": b.name, "creado_en": b.creation_date.isoformat()} for b in cliente.list_buckets()]
    except S3Error as e:
        raise ErrorMinio(f"No se han podido listar los buckets de MinIO: {e}") from e


def listar_archivos(bucket: str, prefijo: str = "", limite: int = 50) -> list[dict]:
    """Lista los objetos de un bucket (opcionalmente bajo un prefijo, tipo
    carpeta). [] si MinIO no está configurado."""
    cliente = _cliente()
    if cliente is None:
        return []
    try:
        objetos = cliente.list_objects(bucket, prefix=prefijo or None, recursive=True)
        resultado = []
        for objeto in objetos:
            resultado.append({
                "nombre": objeto.object_name,
                "tamano_bytes": objeto.size,
                "modificado_en": objeto.last_modified.isoformat() if objeto.last_modified else None,
            })
            if len(resultado) >= limite:
                break
        return resultado
    except S3Error as e:
        raise ErrorMinio(f"No se han podido listar los archivos de '{bucket}' en MinIO: {e}") from e


def url_descarga(bucket: str, nombre_archivo: str, expira_minutos: int = 60) -> str:
    """Genera una URL de descarga firmada y temporal para un objeto —
    válida `expira_minutos` (60 por defecto)."""
    cliente = _cliente()
    if cliente is None:
        raise ErrorMinio("MinIO no está configurado (falta MINIO_ROOT_PASSWORD).")
    try:
        return cliente.presigned_get_object(bucket, nombre_archivo, expires=timedelta(minutes=expira_minutos))
    except S3Error as e:
        raise ErrorMinio(f"No se ha podido generar la URL de descarga para '{nombre_archivo}' en MinIO: {e}") from e
