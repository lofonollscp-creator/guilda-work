#!/usr/bin/env python3
"""Lleva el contenido de los documentos de la base de datos al almacén de objetos (app/almacen_objetos.py) y lo mantiene.

    scripts/migrar_a_objetos.py estado                      qué hay en la base, qué hay fuera y qué almacén está configurado (no escribe nada)
    scripts/migrar_a_objetos.py migrar [--aplicar]          sube lo que sigue en la base; SIN --aplicar solo cuenta lo que haría
    scripts/migrar_a_objetos.py verificar [--aplicar]       lee cada objeto del almacén y comprueba tamaño y SHA-256; avisa de filas vacías que no tienen objeto
    scripts/migrar_a_objetos.py limpiar [--aplicar]         borra los objetos de filas que ya no existen y los que ningún registro menciona (requiere un almacén con permiso de borrado)
    scripts/migrar_a_objetos.py revertir [--aplicar]        devuelve el contenido del almacén a la base (marcha atrás)

Opciones: --tablas a,b (por defecto todas las que admite el almacén), --tenant N, --lote 200, --limite N (máximo de filas por tabla), --continuar (no parar al primer fallo),
--antiguedad-min 60 (para `limpiar`: no toca objetos más recientes), --borrar-objetos (con `revertir`: borra también los objetos).

Seguridad: es idempotente y se puede interrumpir y repetir. Cada objeto se sube, se LEE DE VUELTA y se compara su SHA-256 antes de vaciar la columna de la base, y solo se vacía si la fila no ha cambiado mientras tanto.
Necesita el mismo entorno que el servicio (la base de datos y GUILDA_OBJETOS…): `set -a; . /etc/guilda-work.env; set +a; .venv/bin/python scripts/migrar_a_objetos.py estado`.
Tras migrar mucho contenido, PostgreSQL no devuelve el espacio al sistema operativo hasta un `VACUUM FULL` de esas tablas (bloquea la tabla mientras dura: hazlo en una ventana de mantenimiento); SQLite, hasta un `VACUUM`."""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import almacen_objetos as ao  # noqa: E402
from app import db  # noqa: E402

DESPACHO = ao.DESPACHO


def _tablas(texto: str | None) -> list[str]:
    if not texto:
        return list(ao.TABLAS)
    pedidas = [t.strip() for t in texto.split(",") if t.strip()]
    malas = [t for t in pedidas if t not in ao.TABLAS]
    if malas:
        sys.exit(f"Tabla no admitida: {', '.join(malas)}. Admitidas: {', '.join(ao.TABLAS)}")
    return pedidas


def _filtro_tenant(tabla: str, tenant: int | None) -> tuple[str, list]:
    return (f" AND {DESPACHO[tabla][1]} = ?", [tenant]) if tenant else ("", [])


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:,.1f} MB"


# --- estado -----------------------------------------------------------------------------------------------------------------------------------------------

def estado(args) -> int:
    try:
        a = ao.almacen()
    except ao.ErrorAlmacenObjetos as e:
        print(f"ALMACÉN MAL CONFIGURADO: {e}")
        a = None
    print(f"Almacén configurado: {a.nombre if a else 'ninguno (todo sigue en la base)'}")
    conn = db.get_connection()
    try:
        total_dentro = total_fuera = 0
        print(f"{'tabla':36} {'en la base':>22} {'fuera':>22}")
        for tabla in _tablas(args.tablas):
            union, expr = DESPACHO[tabla]
            extra, p = _filtro_tenant(tabla, args.tenant)
            n, b = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(length(t.contenido)), 0) FROM {tabla} t {union} WHERE length(t.contenido) > 0 "
                                f"AND NOT EXISTS (SELECT 1 FROM objetos_almacenados o WHERE o.tabla = ? AND o.fila_id = t.id){extra}", [tabla, *p]).fetchone()
            r = conn.execute("SELECT COUNT(*), COALESCE(SUM(tamano_bytes), 0) FROM objetos_almacenados WHERE tabla = ?" + (" AND tenant_id = ?" if args.tenant else ""), [tabla, *([args.tenant] if args.tenant else [])]).fetchone()
            print(f"{tabla:36} {n:>8} ({_mb(b):>10}) {r[0]:>8} ({_mb(r[1]):>10})")
            total_dentro += b
            total_fuera += r[1]
        print(f"{'TOTAL':36} {'':>8} ({_mb(total_dentro):>10}) {'':>8} ({_mb(total_fuera):>10})")
    finally:
        conn.close()
    return 0


# --- migrar -----------------------------------------------------------------------------------------------------------------------------------------------

def _pendientes(conn, tabla: str, desde_id: int, lote: int, tenant: int | None):
    union, expr = DESPACHO[tabla]
    extra, p = _filtro_tenant(tabla, tenant)
    col_mime = ao.TABLAS[tabla]["mime"]
    return conn.execute(f"SELECT t.id, t.contenido, t.{col_mime} AS mime, {expr} AS tenant_id FROM {tabla} t {union} WHERE t.id > ? AND length(t.contenido) > 0 "
                        f"AND NOT EXISTS (SELECT 1 FROM objetos_almacenados o WHERE o.tabla = ? AND o.fila_id = t.id){extra} ORDER BY t.id LIMIT ?", [desde_id, tabla, *p, lote]).fetchall()


def migrar(args) -> int:
    a = ao.almacen()
    if a is None:
        sys.exit("No hay almacén configurado (GUILDA_OBJETOS). Nada que hacer.")
    fallos = 0
    for tabla in _tablas(args.tablas):
        hechas = bytes_ = saltadas = 0
        ultimo = 0
        conn = db.get_connection()
        try:
            while True:
                filas = _pendientes(conn, tabla, ultimo, args.lote, args.tenant)
                if not filas or (args.limite and hechas + saltadas >= args.limite):
                    break
                for f in filas:
                    ultimo = f["id"]
                    if args.limite and hechas + saltadas >= args.limite:
                        break
                    datos = bytes(f["contenido"])
                    if f["tenant_id"] is None:
                        print(f"  {tabla} #{f['id']}: sin despacho, se salta")
                        saltadas += 1
                        continue
                    if not args.aplicar:
                        hechas += 1
                        bytes_ += len(datos)
                        continue
                    try:
                        sha = hashlib.sha256(datos).hexdigest()
                        clave = ao.clave_de(f["tenant_id"], tabla, f["id"], sha)
                        a.poner(clave, datos, f["mime"])
                        if hashlib.sha256(a.leer(clave)).hexdigest() != sha:
                            raise ao.ErrorAlmacenObjetos("la lectura de vuelta no coincide con lo subido")
                        actual = conn.execute(f"SELECT contenido FROM {tabla} WHERE id = ?", (f["id"],)).fetchone()
                        if actual is None or hashlib.sha256(bytes(actual["contenido"] or b"")).hexdigest() != sha:
                            saltadas += 1                      # la fila cambió (o desapareció) mientras se subía: se deja como está; el objeto sobrante lo recoge `limpiar`
                            conn.rollback()
                            continue
                        ao._registrar(conn, f["tenant_id"], tabla, f["id"], clave, a.nombre, datos)
                        conn.execute(f"UPDATE {tabla} SET contenido = ? WHERE id = ?", (b"", f["id"]))
                        conn.commit()
                        hechas += 1
                        bytes_ += len(datos)
                    except ao.ErrorAlmacenObjetos as e:
                        conn.rollback()
                        fallos += 1
                        print(f"  FALLO {tabla} #{f['id']}: {e}")
                        if not args.continuar:
                            print("Se para en el primer fallo (usa --continuar para seguir).")
                            return 1
                if args.aplicar and hechas and hechas % 1000 < args.lote:
                    print(f"  {tabla}: {hechas} subidas ({_mb(bytes_)})…", flush=True)
        finally:
            conn.close()
        verbo = "migradas" if args.aplicar else "se migrarían"
        print(f"{tabla}: {verbo} {hechas} filas ({_mb(bytes_)}){f', saltadas {saltadas}' if saltadas else ''}")
    if not args.aplicar:
        print("\n(simulación: añade --aplicar para hacerlo de verdad)")
    return 1 if fallos else 0


# --- verificar --------------------------------------------------------------------------------------------------------------------------------------------

def verificar(args) -> int:
    a = ao.almacen()
    if a is None:
        sys.exit("No hay almacén configurado (GUILDA_OBJETOS).")
    problemas = revisados = 0
    conn = db.get_connection()
    try:
        for tabla in _tablas(args.tablas):
            filtro = " AND tenant_id = ?" if args.tenant else ""
            for o in conn.execute(f"SELECT * FROM objetos_almacenados WHERE tabla = ?{filtro} ORDER BY id", [tabla, *([args.tenant] if args.tenant else [])]).fetchall():
                revisados += 1
                try:
                    datos = a.leer(o["clave"])
                except ao.ErrorAlmacenObjetos as e:
                    problemas += 1
                    print(f"FALTA {tabla} #{o['fila_id']} ({o['clave']}): {e}")
                    continue
                if len(datos) != o["tamano_bytes"] or hashlib.sha256(datos).hexdigest() != o["sha256"]:
                    problemas += 1
                    print(f"DISTINTO {tabla} #{o['fila_id']} ({o['clave']}): el objeto no coincide con su registro")
                elif args.aplicar:
                    conn.execute("UPDATE objetos_almacenados SET verificado_en = ? WHERE id = ?", (db.now_iso(), o["id"]))
                    conn.commit()
            union, expr = DESPACHO[tabla]
            extra, p = _filtro_tenant(tabla, args.tenant)
            huerfanas = conn.execute(f"SELECT t.id FROM {tabla} t {union} WHERE length(t.contenido) = 0 AND t.tamano_bytes > 0 "
                                     f"AND NOT EXISTS (SELECT 1 FROM objetos_almacenados o WHERE o.tabla = ? AND o.fila_id = t.id){extra}", [tabla, *p]).fetchall()
            for f in huerfanas:
                problemas += 1
                print(f"SIN CONTENIDO {tabla} #{f['id']}: la fila está vacía y no tiene objeto anotado (¿vaciada por otro medio?)")
    finally:
        conn.close()
    print(f"Revisados {revisados} objetos: {'sin problemas' if not problemas else f'{problemas} problemas'}.")
    return 1 if problemas else 0


# --- limpiar ----------------------------------------------------------------------------------------------------------------------------------------------

def limpiar(args) -> int:
    a = ao.almacen()
    if a is None:
        sys.exit("No hay almacén configurado (GUILDA_OBJETOS).")
    quitar = borrados = fallos = 0
    conn = db.get_connection()
    try:
        referenciadas: set[str] = set()
        for tabla in _tablas(args.tablas):
            filtro = " AND tenant_id = ?" if args.tenant else ""
            for o in conn.execute(f"SELECT * FROM objetos_almacenados WHERE tabla = ?{filtro} ORDER BY id", [tabla, *([args.tenant] if args.tenant else [])]).fetchall():
                if conn.execute(f"SELECT 1 FROM {tabla} WHERE id = ?", (o["fila_id"],)).fetchone() is not None:
                    referenciadas.add(o["clave"])
                    continue
                quitar += 1                                  # la fila ya no existe: su objeto sobra
                if args.aplicar:
                    try:
                        a.borrar(o["clave"])
                        conn.execute("DELETE FROM objetos_almacenados WHERE id = ?", (o["id"],))
                        conn.commit()
                        borrados += 1
                    except ao.ErrorAlmacenObjetos as e:
                        fallos += 1
                        print(f"  no se pudo borrar {o['clave']}: {e}")
        # objetos del almacén que ningún registro menciona (subidas que no llegaron a anotarse, versiones anteriores tras una reescritura…)
        todas = {r["clave"] for r in conn.execute("SELECT clave FROM objetos_almacenados").fetchall()}
        corte = time.time() - args.antiguedad_min * 60
        tablas = _tablas(args.tablas)
        for clave, _tamano, modificado in a.listar(ao.prefijo_de(args.tenant)):
            if not any(f"/{t}/" in "/" + clave for t in tablas) or clave in todas or modificado > corte:
                continue
            quitar += 1
            if args.aplicar:
                try:
                    a.borrar(clave)
                    borrados += 1
                except ao.ErrorAlmacenObjetos as e:
                    fallos += 1
                    print(f"  no se pudo borrar {clave}: {e}")
    finally:
        conn.close()
    print(f"{'Borrados' if args.aplicar else 'Sobrarían'}: {borrados if args.aplicar else quitar}" + (f" · fallos: {fallos}" if fallos else ""))
    if not args.aplicar:
        print("(simulación: añade --aplicar para borrar de verdad)")
    return 1 if fallos else 0


# --- revertir ---------------------------------------------------------------------------------------------------------------------------------------------

def revertir(args) -> int:
    a = ao.almacen()
    if a is None:
        sys.exit("No hay almacén configurado (GUILDA_OBJETOS).")
    hechas = fallos = 0
    conn = db.get_connection()
    try:
        for tabla in _tablas(args.tablas):
            filtro = " AND tenant_id = ?" if args.tenant else ""
            for o in conn.execute(f"SELECT * FROM objetos_almacenados WHERE tabla = ?{filtro} ORDER BY id", [tabla, *([args.tenant] if args.tenant else [])]).fetchall():
                if not args.aplicar:
                    hechas += 1
                    continue
                try:
                    datos = a.leer(o["clave"])
                    if hashlib.sha256(datos).hexdigest() != o["sha256"]:
                        raise ao.ErrorAlmacenObjetos("no coincide con su huella")
                    conn.execute(f"UPDATE {tabla} SET contenido = ? WHERE id = ?", (datos, o["fila_id"]))
                    conn.execute("DELETE FROM objetos_almacenados WHERE id = ?", (o["id"],))
                    conn.commit()
                    hechas += 1
                    if args.borrar_objetos:
                        try:
                            a.borrar(o["clave"])
                        except ao.ErrorAlmacenObjetos as e:
                            print(f"  el objeto {o['clave']} se queda en el almacén: {e}")
                except ao.ErrorAlmacenObjetos as e:
                    conn.rollback()
                    fallos += 1
                    print(f"  FALLO {tabla} #{o['fila_id']}: {e}")
    finally:
        conn.close()
    print(f"{'Devueltas' if args.aplicar else 'Se devolverían'} a la base: {hechas}" + (f" · fallos: {fallos}" if fallos else ""))
    return 1 if fallos else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("orden", choices=["estado", "migrar", "verificar", "limpiar", "revertir"])
    p.add_argument("--tablas")
    p.add_argument("--tenant", type=int)
    p.add_argument("--lote", type=int, default=200)
    p.add_argument("--limite", type=int, default=0)
    p.add_argument("--aplicar", action="store_true")
    p.add_argument("--continuar", action="store_true")
    p.add_argument("--antiguedad-min", type=int, default=60)
    p.add_argument("--borrar-objetos", action="store_true")
    args = p.parse_args(argv)
    return {"estado": estado, "migrar": migrar, "verificar": verificar, "limpiar": limpiar, "revertir": revertir}[args.orden](args)


if __name__ == "__main__":
    sys.exit(main())
