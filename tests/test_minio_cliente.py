"""Tests del cliente de MinIO (app/minio_cliente.py) — se mockea
minio_cliente._cliente() con un objeto falso, sin un MinIO de verdad ni
credenciales reales."""
from datetime import datetime

import pytest

from app import minio_cliente


class _BucketFalso:
    def __init__(self, name):
        self.name = name
        self.creation_date = datetime(2026, 1, 1)


class _ObjetoFalso:
    def __init__(self, nombre, size):
        self.object_name = nombre
        self.size = size
        self.last_modified = datetime(2026, 1, 2)


def test_listar_buckets_sin_password_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(minio_cliente, "MINIO_ROOT_PASSWORD", None)
    assert minio_cliente.listar_buckets() == []


def test_listar_buckets_ok(monkeypatch):
    class _ClienteFalso:
        def list_buckets(self):
            return [_BucketFalso("guilda-backups")]

    monkeypatch.setattr(minio_cliente, "_cliente", lambda: _ClienteFalso())
    resultado = minio_cliente.listar_buckets()
    assert resultado == [{"nombre": "guilda-backups", "creado_en": "2026-01-01T00:00:00"}]


def test_listar_archivos_sin_password_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(minio_cliente, "MINIO_ROOT_PASSWORD", None)
    assert minio_cliente.listar_archivos("guilda-backups") == []


def test_listar_archivos_ok(monkeypatch):
    class _ClienteFalso:
        def list_objects(self, bucket, prefix=None, recursive=False):
            return [_ObjetoFalso("registro.db", 2048)]

    monkeypatch.setattr(minio_cliente, "_cliente", lambda: _ClienteFalso())
    resultado = minio_cliente.listar_archivos("guilda-backups")
    assert resultado == [{"nombre": "registro.db", "tamano_bytes": 2048, "modificado_en": "2026-01-02T00:00:00"}]


def test_url_descarga_sin_password_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(minio_cliente, "MINIO_ROOT_PASSWORD", None)
    with pytest.raises(minio_cliente.ErrorMinio):
        minio_cliente.url_descarga("guilda-backups", "registro.db")


def test_url_descarga_ok(monkeypatch):
    class _ClienteFalso:
        def presigned_get_object(self, bucket, nombre, expires=None):
            return f"https://minio.local/{bucket}/{nombre}?firma=abc"

    monkeypatch.setattr(minio_cliente, "_cliente", lambda: _ClienteFalso())
    url = minio_cliente.url_descarga("guilda-backups", "registro.db")
    assert url == "https://minio.local/guilda-backups/registro.db?firma=abc"
