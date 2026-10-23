"""Excepciones de base de datos válidas para cualquiera de los dos motores.

Son TUPLAS de clases para usar directamente en `except ErrorIntegridad:`; para
registrar un manejador de Flask hay que iterarlas. Si `psycopg` no está instalado
solo contienen las de `sqlite3`.
"""
import sqlite3

_integridad = [sqlite3.IntegrityError]
_operacional = [sqlite3.OperationalError]
_general = [sqlite3.Error]
try:
    import psycopg

    _integridad.append(psycopg.IntegrityError)
    _operacional.append(psycopg.OperationalError)
    _general.append(psycopg.Error)
except ImportError:                                  # PostgreSQL es opcional hasta el corte
    pass

ErrorIntegridad = tuple(_integridad)                 # UNIQUE, FOREIGN KEY, NOT NULL, CHECK
ErrorOperacional = tuple(_operacional)
ErrorBD = tuple(_general)
