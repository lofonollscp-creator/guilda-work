"""Aísla cada test en su propia base de datos SQLite temporal.

`db.py` guarda la ruta de la base de datos en el atributo de módulo
`DB_PATH`, y cada función abre/cierra su propia conexión a partir de ese
atributo — así que basta con parchearlo antes de cada test para que ningún
test toque nunca `data/registro.db` de verdad.
"""
import keyring
import keyring.errors
import pytest

from app import db


@pytest.fixture(autouse=True)
def base_de_datos_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path / "backups")
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def keyring_en_memoria(monkeypatch):
    """Sustituye keyring por un almacén en memoria durante los tests, para no
    tocar el Windows Credential Manager real al probar app/correo.py."""
    almacen: dict[tuple[str, str], str] = {}

    def fake_set(servicio, usuario, contrasena):
        almacen[(servicio, usuario)] = contrasena

    def fake_get(servicio, usuario):
        return almacen.get((servicio, usuario))

    def fake_delete(servicio, usuario):
        if (servicio, usuario) not in almacen:
            raise keyring.errors.PasswordDeleteError("no password set")
        del almacen[(servicio, usuario)]

    monkeypatch.setattr(keyring, "set_password", fake_set)
    monkeypatch.setattr(keyring, "get_password", fake_get)
    monkeypatch.setattr(keyring, "delete_password", fake_delete)
    yield
