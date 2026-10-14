"""Acceso a datos del calendario fiscal, el portal del cliente, el expediente documental del cliente y su registro de accesos.

Parte de la antigua `db.py`, dividida por dominios sin cambiar su comportamiento: todo lo que no está aquí (la conexión, las constantes y las funciones de otros
dominios) se usa a través de `_db`, que sigue siendo el único espacio de nombres (`_db.nombre` funciona igual que antes y se puede parchear en los tests)."""
import hashlib
import logging
import json
import time
import os
import re
import random
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

from . import db as _db


def serializar_modelos_fiscales(modelos: list[str] | None) -> str | None:
    """Pública (no `_`) porque tanto crear_cliente_fiscal como la ruta de
    edición (app/rutas_fiscal.py, que llama a editar_cliente_fiscal con el
    whitelist genérico CAMPOS_CLIENTE_FISCAL) necesitan serializar antes de
    guardar."""
    return json.dumps(modelos) if modelos else None


def modelos_fiscales_de_cliente(cliente: sqlite3.Row) -> list[str]:
    """Deserializa clientes_fiscales.modelos_fiscales -- fila puede venir de
    antes de que existiera la columna (None) o con JSON corrupto en teoría
    imposible (siempre se escribe con serializar_modelos_fiscales), pero se
    protege igual con un try/except silencioso, mismo criterio defensivo
    que el resto de columnas JSON de este módulo."""
    valor = cliente["modelos_fiscales"] if "modelos_fiscales" in cliente.keys() else None
    if not valor:
        return []
    try:
        return json.loads(valor)
    except (TypeError, ValueError):
        return []


def perfil_fiscal_de_cliente(cliente: sqlite3.Row) -> dict:
    """Perfil fiscal guardado (`{"tipo", "atributos"}`); sin perfil o con JSON ilegible, uno vacío de particular."""
    from . import perfil_fiscal
    valor = cliente["perfil_fiscal"] if "perfil_fiscal" in cliente.keys() else None
    try:
        datos = json.loads(valor) if valor else {}
    except (TypeError, ValueError):
        datos = {}
    return perfil_fiscal.perfil_limpio(datos.get("tipo"), datos.get("atributos") or ())


def vencimientos_por_cliente(tenant_id: int) -> dict[int, list[dict]]:
    """`{cliente_fiscal_id: [{estado, fecha_limite}]}` de todos los vencimientos vivos del despacho, en una sola consulta (para el semáforo)."""
    from . import acceso
    extra, extra_p = acceso.restriccion(tenant_id, "cliente_fiscal_id")
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            f"SELECT cliente_fiscal_id, estado, fecha_limite FROM vencimientos_fiscales WHERE tenant_id = ? AND papelera_en IS NULL{extra}",
            (tenant_id, *extra_p),
        ).fetchall()
    finally:
        conn.close()
    res: dict[int, list[dict]] = {}
    for f in filas:
        res.setdefault(f["cliente_fiscal_id"], []).append({"estado": f["estado"], "fecha_limite": f["fecha_limite"]})
    return res


def crear_cliente_fiscal(
    tenant_id: int, nombre: str, nif: str | None = None, notas: str | None = None,
    modelos_fiscales: list[str] | None = None, email: str | None = None,
    cliente_id: int | None = None, pais: str = "ES",
) -> int:
    """`cliente_id`: ficha del núcleo (`clientes`) ya existente a la que se enlaza esta ficha fiscal (alta única, ver app/alta_cliente.py);
    sin él se crea la ficha del núcleo a partir de esta, como siempre. `pais` entra ya en el alta porque de él depende la clave de duplicados del NIF."""
    from . import fiscal_identidad
    pais = (pais or "ES").strip().upper()
    conn = _db.get_connection()
    try:
        clave = fiscal_identidad.clave_unica(nif, pais)
        try:
            cur = conn.execute(
                "INSERT INTO clientes_fiscales (tenant_id, nombre, nif, nif_normalizado, pais, notas, modelos_fiscales, email, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant_id, nombre.strip(), (nif or "").strip() or None, clave, pais, (notas or "").strip() or None,
                    _db.serializar_modelos_fiscales(modelos_fiscales), (email or "").strip() or None, _db.now_iso(),
                ),
            )
        except sqlite3.IntegrityError:
            raise _db._cliente_duplicado(conn, tenant_id, pais, clave, nif) from None
        if cliente_id is not None:
            conn.execute("UPDATE clientes_fiscales SET cliente_id = ? WHERE id = ? AND tenant_id = ?", (cliente_id, cur.lastrowid, tenant_id))
        conn.commit()
        cliente_fiscal_id = cur.lastrowid
    finally:
        conn.close()
    _db._reindexar_cliente_fiscal(tenant_id, cliente_fiscal_id)
    from . import eventos, nucleo
    nucleo.vincular_cliente_fiscal(tenant_id, cliente_fiscal_id)
    eventos.emitir("cliente.creado", tenant_id, {"cliente_id": cliente_fiscal_id, "nombre": nombre.strip(), "nif": (nif or "").strip() or None})
    return cliente_fiscal_id


def _cliente_duplicado(conn, tenant_id: int, pais: str, clave: str | None, nif) -> Exception:
    """El error que explica con QUIÉN choca un NIF repetido (o el IntegrityError original si no se encuentra, para no ocultar otro fallo)."""
    from . import fiscal_identidad
    f = conn.execute("SELECT id, nombre FROM clientes_fiscales WHERE tenant_id = ? AND pais = ? AND nif_normalizado = ? AND papelera_en IS NULL AND nif_duplicado_autorizado IS NULL ORDER BY id LIMIT 1",
                     (tenant_id, pais, clave)).fetchone() if clave else None
    return fiscal_identidad.ClienteDuplicado(clave or (nif or "").strip(), f["id"], f["nombre"]) if f else sqlite3.IntegrityError("UNIQUE constraint failed: clientes_fiscales")


def _reindexar_cliente_fiscal(tenant_id: int, cliente_id: int) -> None:
    """Falla en silencio, mismo criterio que _reindexar_tarea/_reindexar_nota
    -- una mejora de UX (buscador global), nunca debe romper el alta/edición
    del cliente en sí."""
    from . import busqueda
    try:
        cliente = _db.obtener_cliente_fiscal(tenant_id, cliente_id)
        if cliente is not None:
            busqueda.indexar_cliente_fiscal(dict(cliente))
    except busqueda.ErrorBusqueda:
        pass


def _quitar_cliente_fiscal_del_indice(cliente_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("cliente_fiscal", cliente_id)
    except busqueda.ErrorBusqueda:
        pass


def listar_clientes_fiscales(tenant_id: int, q: str | None = None, pais: str | None = None) -> list[sqlite3.Row]:
    """`q` filtra por nombre/NIF (LIKE, insensible a mayúsculas) -- tabla
    pequeña por tenant, no hace falta Meilisearch para esto. `pais` filtra
    por país de tributación exacto (ver app/vencimientos_fiscales.py)."""
    conn = _db.get_connection()
    try:
        cond = ["tenant_id = ?", "papelera_en IS NULL"]
        params: list = [tenant_id]
        if q:
            cond.append("(nombre LIKE ? OR nif LIKE ?)")
            comodin = f"%{q.strip()}%"
            params.extend([comodin, comodin])
        if pais:
            cond.append("pais = ?")
            params.append(pais)
        from . import acceso
        extra, extra_p = acceso.restriccion(tenant_id, "id")
        return conn.execute(
            f"SELECT * FROM clientes_fiscales WHERE {' AND '.join(cond)}{extra} ORDER BY nombre", [*params, *extra_p],
        ).fetchall()
    finally:
        conn.close()


def paises_clientes_fiscales(tenant_id: int) -> list[str]:
    """Países de tributación en uso por los clientes de este tenant
    (distintos, orden alfabético) -- para el <select> de filtro por país
    en /fiscal/clientes y /fiscal/vencimientos. Con un solo país en uso
    (el caso normal hoy) el filtro no aporta mucho, pero no hace falta
    tocar esta función cuando se añada soporte a un segundo país."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT DISTINCT pais FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY pais",
            (tenant_id,),
        ).fetchall()
        return [f["pais"] for f in filas]
    finally:
        conn.close()


def obtener_cliente_fiscal(tenant_id: int, cliente_id: int) -> sqlite3.Row | None:
    from . import acceso
    extra, extra_p = acceso.restriccion(tenant_id, "id")
    conn = _db.get_connection()
    try:
        return conn.execute(
            f"SELECT * FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL{extra}",
            (cliente_id, tenant_id, *extra_p),
        ).fetchone()
    finally:
        conn.close()


def editar_cliente_fiscal(tenant_id: int, cliente_id: int, **campos) -> None:
    columnas = [c for c in campos if c in _db.CAMPOS_CLIENTE_FISCAL]
    if not columnas:
        return
    from . import fiscal_identidad
    conn = _db.get_connection()
    try:
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        clave, pais = None, None
        if "nif" in campos or "pais" in campos:
            actual = conn.execute("SELECT nif, pais FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_id, tenant_id)).fetchone()
            if actual is None:
                return
            pais = (campos.get("pais") or actual["pais"] or "ES").upper()
            nif_final = campos["nif"] if "nif" in campos else actual["nif"]
            clave = fiscal_identidad.clave_unica(nif_final, pais)
            asignaciones += ", nif_normalizado = ?"
            valores.append(clave)
        try:
            conn.execute(
                f"UPDATE clientes_fiscales SET {asignaciones}, version = version + 1 WHERE id = ? AND tenant_id = ?",
                [*valores, cliente_id, tenant_id],
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            raise _db._cliente_duplicado(conn, tenant_id, pais or "ES", clave, campos.get("nif")) from None
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_cliente_fiscal(tenant_id, cliente_id)
    from . import nucleo
    nucleo.sincronizar_desde_fiscal(tenant_id, cliente_id)


def eliminar_cliente_fiscal(tenant_id: int, cliente_id: int) -> None:
    """Manda el cliente a la papelera (no lo borra de verdad). No toca sus
    vencimientos -- se quedan huérfanos visualmente (el cliente ya no
    aparece en el listado) pero no se pierden, igual que pasa con una
    categoría y sus tareas."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE clientes_fiscales SET papelera_en = ? WHERE id = ? AND tenant_id = ?",
            (_db._marca_papelera(), cliente_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()
    _db._quitar_cliente_fiscal_del_indice(cliente_id)
    from . import nucleo
    nucleo.sincronizar_desde_fiscal(tenant_id, cliente_id)


def restaurar_cliente_fiscal(tenant_id: int, cliente_id: int) -> None:
    conn = _db.get_connection()
    try:
        try:
            conn.execute(
                "UPDATE clientes_fiscales SET papelera_en = NULL WHERE id = ? AND tenant_id = ?",
                (cliente_id, tenant_id),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            f = conn.execute("SELECT nif, pais, nif_normalizado FROM clientes_fiscales WHERE id = ?", (cliente_id,)).fetchone()
            raise _db._cliente_duplicado(conn, tenant_id, f["pais"] if f else "ES", f["nif_normalizado"] if f else None, f["nif"] if f else None) from None
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_cliente_fiscal(tenant_id, cliente_id)
    from . import nucleo
    nucleo.sincronizar_desde_fiscal(tenant_id, cliente_id)


def eliminar_cliente_fiscal_definitivamente(tenant_id: int, cliente_id: int) -> None:
    conn = _db.get_connection()
    try:
        # Los certificados conservan su historial sin el cliente; las concesiones de acceso se van con él.
        conn.execute("UPDATE certificados SET cliente_titular_id = NULL WHERE cliente_titular_id = ? AND tenant_id = ?", (cliente_id, tenant_id))
        conn.execute("UPDATE certificados_vinculos SET cliente_fiscal_id = NULL WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_id, tenant_id))
        conn.execute("DELETE FROM concesiones_cliente WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_id, tenant_id))
        conn.execute("DELETE FROM traspasos WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_id, tenant_id))
        conn.execute("DELETE FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    _db._quitar_cliente_fiscal_del_indice(cliente_id)


def crear_vencimiento_fiscal(
    tenant_id: int, cliente_fiscal_id: int, modelo: str, periodo: str, fecha_limite: str,
    usuario_id: int | None = None, notas: str | None = None, rectifica_a: int | None = None,
) -> int:
    """Alta de un vencimiento. Un mismo cliente, modelo y período solo puede tener uno (si no es una rectificación: `rectifica_a` lo vincula a su original);
    repetirlo lanza `sqlite3.IntegrityError` (la API lo contesta como 409)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO vencimientos_fiscales
               (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, notas, creado_en, rectifica_a)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tenant_id, cliente_fiscal_id, usuario_id, modelo.strip(), periodo.strip(),
                fecha_limite, (notas or "").strip() or None, _db.now_iso(), rectifica_a,
            ),
        )
        conn.commit()
        vencimiento_id = cur.lastrowid
    finally:
        conn.close()
    _db._reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)
    return vencimiento_id


def _reindexar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> None:
    from . import busqueda
    try:
        vencimiento = _db.obtener_vencimiento_fiscal(tenant_id, vencimiento_id)
        if vencimiento is not None:
            busqueda.indexar_vencimiento_fiscal(dict(vencimiento))
    except busqueda.ErrorBusqueda:
        pass


def _quitar_vencimiento_fiscal_del_indice(vencimiento_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("vencimiento_fiscal", vencimiento_id)
    except busqueda.ErrorBusqueda:
        pass


def listar_vencimientos_fiscales(
    tenant_id: int,
    desde: str | None = None,
    hasta: str | None = None,
    estado: str | None = None,
    cliente_fiscal_id: int | None = None,
    pais: str | None = None,
    limite: int | None = None,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """`limite`/`offset` paginan (sin `limite` devuelve todos, como siempre).
    `desde`/`hasta` filtran por fecha_limite (YYYY-MM-DD, inclusive/
    exclusive respectivamente, mismo criterio que listar_tareas_outlook).
    `pais` filtra por el país de tributación del CLIENTE (columna `c.pais`,
    no hay columna propia en vencimientos_fiscales -- ver
    app/vencimientos_fiscales.py)."""
    conn = _db.get_connection()
    try:
        cond = ["v.tenant_id = ?", "v.papelera_en IS NULL"]
        params: list = [tenant_id]
        if desde:
            cond.append("v.fecha_limite >= ?"); params.append(desde)
        if hasta:
            cond.append("v.fecha_limite < ?"); params.append(_db._fecha_exclusiva(hasta))
        if estado:
            cond.append("v.estado = ?"); params.append(estado)
        if cliente_fiscal_id:
            cond.append("v.cliente_fiscal_id = ?"); params.append(cliente_fiscal_id)
        if pais:
            cond.append("c.pais = ?"); params.append(pais)
        from . import acceso
        extra, extra_p = acceso.restriccion(tenant_id, "v.cliente_fiscal_id")
        where = " AND ".join(cond) + extra
        params += extra_p
        paginacion = ""
        if limite is not None:
            paginacion = " LIMIT ? OFFSET ?"
            params += [int(limite), max(int(offset), 0)]
        return conn.execute(
            f"""SELECT v.*, c.nombre AS cliente_nombre
                FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
                WHERE {where}
                ORDER BY v.fecha_limite, v.id{paginacion}""",
            params,
        ).fetchall()
    finally:
        conn.close()


def contar_vencimientos_fiscales(
    tenant_id: int, desde: str | None = None, hasta: str | None = None, estado: str | None = None,
    cliente_fiscal_id: int | None = None, pais: str | None = None,
) -> int:
    """Total con los mismos filtros que listar_vencimientos_fiscales (para paginar en SQL con X-Total-Count)."""
    cond = ["v.tenant_id = ?", "v.papelera_en IS NULL"]
    params: list = [tenant_id]
    if desde:
        cond.append("v.fecha_limite >= ?"); params.append(desde)
    if hasta:
        cond.append("v.fecha_limite < ?"); params.append(_db._fecha_exclusiva(hasta))
    if estado:
        cond.append("v.estado = ?"); params.append(estado)
    if cliente_fiscal_id:
        cond.append("v.cliente_fiscal_id = ?"); params.append(cliente_fiscal_id)
    if pais:
        cond.append("c.pais = ?"); params.append(pais)
    from . import acceso
    extra, extra_p = acceso.restriccion(tenant_id, "v.cliente_fiscal_id")
    conn = _db.get_connection()
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id WHERE {' AND '.join(cond)}{extra}", [*params, *extra_p]
        ).fetchone()[0]
    finally:
        conn.close()


def vencimiento_fiscal_existente(tenant_id: int, cliente_fiscal_id: int, modelo: str, periodo: str) -> int | None:
    """Id del vencimiento (no borrado) de ese cliente, modelo y periodo, si ya existe: evita duplicados al generar."""
    conn = _db.get_connection()
    try:
        f = conn.execute(
            "SELECT id FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = ? AND periodo = ? AND papelera_en IS NULL",
            (tenant_id, cliente_fiscal_id, modelo.strip(), periodo.strip()),
        ).fetchone()
        return f["id"] if f else None
    finally:
        conn.close()


def tenant_id_de_vencimiento_fiscal(vencimiento_id: int) -> int | None:
    """Resuelve el tenant de un vencimiento por su solo id -- usado por
    el webhook de Stripe (app/rutas_stripe_webhook.py), que no tiene
    ningún contexto de sesión/tenant propio para filtrar por él."""
    conn = _db.get_connection()
    try:
        fila = conn.execute("SELECT tenant_id FROM vencimientos_fiscales WHERE id = ?", (vencimiento_id,)).fetchone()
        return fila["tenant_id"] if fila else None
    finally:
        conn.close()


def obtener_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> sqlite3.Row | None:
    from . import acceso
    extra, extra_p = acceso.restriccion(tenant_id, "v.cliente_fiscal_id")
    conn = _db.get_connection()
    try:
        return conn.execute(
            f"""SELECT v.*, c.nombre AS cliente_nombre
               FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               WHERE v.id = ? AND v.tenant_id = ? AND v.papelera_en IS NULL{extra}""",
            (vencimiento_id, tenant_id, *extra_p),
        ).fetchone()
    finally:
        conn.close()


def editar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int, **campos) -> None:
    columnas = [c for c in campos if c in _db.CAMPOS_VENCIMIENTO_FISCAL]
    if not columnas:
        return
    conn = _db.get_connection()
    try:
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        if "estado" in campos:
            # El flujo de trabajo (`fase`) y el estado de siempre van a la par: presentar desde aquí también presenta el flujo; reabrir lo devuelve a «pendiente».
            asignaciones += ", fase = CASE WHEN ? = 'presentado' THEN CASE WHEN fase IN ('presentada', 'cerrada') THEN fase ELSE 'presentada' END " \
                            "WHEN fase IN ('presentada', 'cerrada') THEN 'pendiente' ELSE fase END"
            valores.append(campos["estado"])
        conn.execute(
            f"UPDATE vencimientos_fiscales SET {asignaciones}, actualizado_en = ?, version = version + 1 WHERE id = ? AND tenant_id = ?",
            [*valores, _db.now_iso(), vencimiento_id, tenant_id],
        )
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)
    if campos.get("estado") == "presentado":
        _db.cerrar_tareas_al_presentar(tenant_id, vencimiento_id)


def cerrar_tareas_al_presentar(tenant_id: int, vencimiento_id: int) -> int:
    """Al presentar un vencimiento se completan las tareas que una regla generó para él (ver db_tareas.completar_tareas_de_vencimiento). Nunca deshace la presentación: si falla
    se deja un aviso en el log y las tareas se pueden completar a mano."""
    try:
        return _db.completar_tareas_de_vencimiento(tenant_id, vencimiento_id)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("Vencimiento %s presentado: no se han podido completar sus tareas", vencimiento_id, exc_info=True)
        return 0


def marcar_presentado_vencimiento_fiscal(tenant_id: int, vencimiento_id: int, usuario_id: int | None = None) -> None:
    """Atajo de siempre: marca el vencimiento como presentado. Además deja la fase en «presentada», anota la presentación declarada por quien lo hizo (si se sabe quién)
    y su evento de auditoría, todo en la misma transacción."""
    conn = _db.get_connection()
    try:
        ahora = _db.now_iso()
        previo = conn.execute("SELECT fase FROM vencimientos_fiscales WHERE id = ? AND tenant_id = ?", (vencimiento_id, tenant_id)).fetchone()
        conn.execute(
            """UPDATE vencimientos_fiscales SET estado = 'presentado', actualizado_en = ?, version = version + 1,
                      fase = CASE WHEN fase IN ('presentada', 'cerrada') THEN fase ELSE 'presentada' END,
                      presentada_tarde = CASE WHEN fase IN ('presentada', 'cerrada') THEN presentada_tarde WHEN substr(fecha_limite, 1, 10) < ? THEN 1 ELSE 0 END
               WHERE id = ? AND tenant_id = ?""",
            (ahora, ahora[:10], vencimiento_id, tenant_id),
        )
        if previo is not None and previo["fase"] not in ("presentada", "cerrada"):
            from . import auditoria
            conn.execute("INSERT INTO obligaciones_evidencias (tenant_id, vencimiento_id, presentado_en, procedencia, declarada_por, creado_en) VALUES (?, ?, ?, 'declarada_por_gestor', ?, ?)",
                         (tenant_id, vencimiento_id, ahora[:16], usuario_id, ahora))
            auditoria.registrar(tenant_id, usuario_id, "obligacion.transicion", "obligacion", vencimiento_id, {"de": previo["fase"], "a": "presentada", "via": "marcar_presentado"}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)
    _db.cerrar_tareas_al_presentar(tenant_id, vencimiento_id)


def eliminar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE vencimientos_fiscales SET papelera_en = ? WHERE id = ? AND tenant_id = ?",
            (_db._marca_papelera(), vencimiento_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()
    _db._quitar_vencimiento_fiscal_del_indice(vencimiento_id)


def restaurar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> None:
    conn = _db.get_connection()
    try:
        # Sacar de la papelera algo «no aplica» o «anulado» lo reactiva: vuelve al principio del flujo y queda anotado.
        previo = conn.execute("SELECT fase FROM vencimientos_fiscales WHERE id = ? AND tenant_id = ?", (vencimiento_id, tenant_id)).fetchone()
        conn.execute(
            "UPDATE vencimientos_fiscales SET papelera_en = NULL, version = version + 1, "
            "fase = CASE WHEN fase IN ('no_aplica', 'anulada') THEN 'pendiente' ELSE fase END WHERE id = ? AND tenant_id = ?",
            (vencimiento_id, tenant_id),
        )
        if previo is not None and previo["fase"] in ("no_aplica", "anulada"):
            from . import auditoria
            auditoria.registrar(tenant_id, None, "obligacion.reactivada", "obligacion", vencimiento_id, {"desde": previo["fase"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)


def eliminar_vencimiento_fiscal_definitivamente(tenant_id: int, vencimiento_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM vencimientos_fiscales WHERE id = ? AND tenant_id = ?", (vencimiento_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    _db._quitar_vencimiento_fiscal_del_indice(vencimiento_id)


def marcar_recordatorio_vencimiento_fiscal_enviado(vencimiento_id: int) -> None:
    """Llamada por el hilo de recordatorio (app/main.py) tras un push
    correcto -- sin tenant_id porque ese hilo cruza todos los tenants a
    propósito, igual que vencimientos_fiscales_proximos()."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE vencimientos_fiscales SET recordatorio_enviado_en = ? WHERE id = ?",
            (_db.now_iso(), vencimiento_id),
        )
        conn.commit()
    finally:
        conn.close()


def vencimientos_fiscales_proximos(dias: int) -> list[sqlite3.Row]:
    """Cruza TODOS los tenants a propósito -- usada solo por el hilo de
    recordatorio periódico (app/main.py:_recordatorio_vencimientos_fiscales),
    nunca desde una ruta servida a un usuario concreto. Excluye lo que ya
    tenga recordatorio_enviado_en -- sin esto se reenviaba el mismo aviso
    cada día mientras el vencimiento siguiera pendiente y dentro de la
    ventana (hasta `dias` veces por vencimiento)."""
    conn = _db.get_connection()
    try:
        hoy = _db.now_iso()[:10]
        ultimo_dia = (_db.datetime.strptime(hoy, "%Y-%m-%d") + _db.timedelta(days=dias)).strftime("%Y-%m-%d")
        limite = _db._fecha_exclusiva(ultimo_dia)
        return conn.execute(
            """SELECT v.*, c.nombre AS cliente_nombre
               FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               WHERE v.estado = 'pendiente' AND v.papelera_en IS NULL
                 AND v.recordatorio_enviado_en IS NULL
                 AND v.fecha_limite >= ? AND v.fecha_limite < ?""",
            (hoy, limite),
        ).fetchall()
    finally:
        conn.close()


def papelera_fiscal(tenant_id: int) -> list[dict]:
    """Clientes fiscales y vencimientos en la papelera de un tenant, más
    recientes primero -- aparte de papelera() (que es por usuario_id) porque
    estas dos tablas son por tenant_id, otra granularidad (ver comentario
    de cabecera de la sección "Calendario fiscal" más arriba)."""
    from . import acceso
    ec, ec_p = acceso.restriccion(tenant_id, "c.id")
    ev, ev_p = acceso.restriccion(tenant_id, "v.cliente_fiscal_id")
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            f"""
            SELECT * FROM (
                SELECT 'cliente_fiscal' AS origen, c.id AS id, c.nombre AS texto,
                       NULL AS cliente_nombre, c.papelera_en AS papelera_en
                FROM clientes_fiscales c
                WHERE c.tenant_id = ? AND c.papelera_en IS NOT NULL{ec}

                UNION ALL

                SELECT 'vencimiento_fiscal' AS origen, v.id AS id,
                       v.modelo || ' ' || v.periodo AS texto,
                       c.nombre AS cliente_nombre, v.papelera_en AS papelera_en
                FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
                WHERE v.tenant_id = ? AND v.papelera_en IS NOT NULL{ev}
            )
            ORDER BY papelera_en DESC
            """,
            (tenant_id, *ec_p, tenant_id, *ev_p),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def _existe_vencimiento_fiscal(tenant_id: int, cliente_fiscal_id: int, modelo: str, periodo: str) -> bool:
    """Da igual si está en la papelera o no -- si ya se generó/borró antes
    este mismo periodo, no hay que volver a crearlo solo (el usuario pudo
    haberlo eliminado a propósito). Usada por generar_vencimientos_automaticos()
    para no duplicar en ejecuciones repetidas del cron (idempotencia)."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? "
            "AND modelo = ? AND periodo = ? LIMIT 1",
            (tenant_id, cliente_fiscal_id, modelo, periodo),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def generar_vencimientos_automaticos() -> int:
    """Recurrencia automática por cron (ver scripts/generar_vencimientos_fiscales.py
    y deploy/vencimientos-fiscales.timer) -- para cada cliente_fiscal con
    generacion_automatica=1 y modelos_fiscales definido, en CUALQUIER
    tenant, genera los vencimientos que falten y los inserta directamente
    (a diferencia de "Generar vencimientos" del backoffice, que solo
    propone y deja confirmar a mano).

    Sin lógica de "qué trimestre exacto toca hoy": se calculan las
    propuestas del año en curso y del anterior (cubre de sobra el caso
    T4/anuales, cuyo plazo cae en enero del año siguiente al periodo) y
    solo se inserta lo que no exista ya para ese cliente+modelo+periodo
    (`_existe_vencimiento_fiscal`) -- así el script es 100% idempotente:
    ejecutarlo todos los días no duplica nada, y no hace falta saber si
    hoy es el primer día de un trimestre nuevo o no.

    Devuelve cuántos vencimientos nuevos se han creado."""
    # Import tardío: vencimientos_fiscales.py es una función pura a
    # propósito (ver su docstring, "nunca un cron que auto-genera") y no
    # importa db.py -- este orquestador vive aquí, no allí, precisamente
    # para no romper esa separación.
    creados = 0
    conn = _db.get_connection()
    try:
        clientes = conn.execute(
            "SELECT * FROM clientes_fiscales WHERE generacion_automatica = 1 "
            "AND modelos_fiscales IS NOT NULL AND papelera_en IS NULL"
        ).fetchall()
    finally:
        conn.close()

    for cliente in clientes:
        creados += _db.generar_vencimientos_de_cliente(cliente)
    return creados


def generar_vencimientos_de_cliente(cliente) -> int:
    """Crea los vencimientos que le faltan a UN cliente fiscal (fila de `clientes_fiscales`) según sus modelos, para el año en curso y el anterior; idempotente.
    Lo usa el cron diario y el alta con plantilla de cliente (app/plantillas_cliente.py). Devuelve cuántos ha creado."""
    from . import laboral, nucleo
    modelos = _db.modelos_fiscales_de_cliente(cliente)
    creados = 0
    anio_actual = _db.datetime.now().year
    for anio in (anio_actual - 1, anio_actual):
        propuestas = nucleo.propuestas_vencimientos_ajustadas(cliente["tenant_id"], modelos, anio, cliente["pais"]) if modelos else []
        propuestas += laboral.propuestas_laborales(cliente["tenant_id"], cliente["id"], anio)      # TC y 190, solo con reglas aprobadas y trabajadores de alta
        for propuesta in propuestas:
            if _db._existe_vencimiento_fiscal(cliente["tenant_id"], cliente["id"], propuesta["modelo"], propuesta["periodo"]):
                continue
            _db.crear_vencimiento_fiscal(cliente["tenant_id"], cliente["id"], propuesta["modelo"], propuesta["periodo"], propuesta["fecha_limite"])
            creados += 1
    return creados


def sanear_vencimientos_fuera_plazo() -> int:
    """Marca `fuera_plazo` cualquier vencimiento `pendiente` cuya
    fecha_limite ya pasó -- llamado por el mismo cron que
    generar_vencimientos_automaticos() (ver scripts/generar_vencimientos_fiscales.py).
    Antes de esto, `fuera_plazo` era un estado del CHECK constraint que
    nadie escribía nunca -- la UI ya lo pinta en rojo en caliente (ver
    app/rutas_fiscal.py:vencimientos()) sin depender de este saneo, pero
    sin él el ESTADO real en BD se quedaba `pendiente` para siempre, lo
    que rompe cualquier filtro/export por estado. Devuelve cuántas filas
    se han marcado."""
    conn = _db.get_connection()
    try:
        hoy = _db.now_iso()[:10]
        cur = conn.execute(
            "UPDATE vencimientos_fiscales SET estado = 'fuera_plazo', actualizado_en = ? "
            "WHERE estado = 'pendiente' AND papelera_en IS NULL AND fecha_limite < ?",
            (_db.now_iso(), hoy),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def obtener_cliente_fiscal_por_id(cliente_fiscal_id: int) -> sqlite3.Row | None:
    """A diferencia de obtener_cliente_fiscal (que exige tenant_id porque
    lo llama personal ya autenticado en un tenant), el portal de cliente
    solo tiene cliente_fiscal_id en su sesión -- no hay tenant_id previo
    del que partir, es al revés: se lee de la fila devuelta."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM clientes_fiscales WHERE id = ? AND papelera_en IS NULL", (cliente_fiscal_id,),
        ).fetchone()
    finally:
        conn.close()


def clientes_fiscales_por_email(email: str) -> list[sqlite3.Row]:
    """A diferencia de obtener_cliente_fiscal_por_email (que ya sabe el
    tenant), esta busca en TODOS los tenants -- la usa /portal/entrar, que
    solo recibe un email sin contexto de tenant. Simplificación consciente
    de v1: si el mismo email está en varios tenants, se manda un enlace por
    cada fila (ver app/rutas_portal_cliente.py)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM clientes_fiscales WHERE LOWER(email) = ? AND papelera_en IS NULL",
            (email.strip().lower(),),
        ).fetchall()
    finally:
        conn.close()


def ultimo_acceso_solicitado_en(cliente_fiscal_id: int) -> str | None:
    """`creado_en` de la última solicitud de enlace de este cliente,
    exista o no la fila -- usado para el cooldown de 2 minutos por email
    en /portal/entrar (evita spamear la bandeja de alguien)."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT creado_en FROM clientes_fiscales_accesos WHERE cliente_fiscal_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (cliente_fiscal_id,),
        ).fetchone()
        return fila["creado_en"] if fila else None
    finally:
        conn.close()


def crear_acceso_cliente_fiscal(cliente_fiscal_id: int, ip_solicitante: str | None) -> str:
    token = secrets.token_urlsafe(32)
    ahora = _db.datetime.now()
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO clientes_fiscales_accesos "
            "(cliente_fiscal_id, token, creado_en, expira_en, ip_solicitante) VALUES (?, ?, ?, ?, ?)",
            (
                cliente_fiscal_id, token, ahora.isoformat(timespec="seconds"),
                (ahora + _db.timedelta(minutes=_db._MINUTOS_VIDA_ACCESO_PORTAL)).isoformat(timespec="seconds"),
                ip_solicitante,
            ),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def consumir_acceso_cliente_fiscal(token: str) -> int | None:
    """Valida y marca usado el token en la MISMA transacción (BEGIN
    IMMEDIATE) -- mismo cuidado de sección crítica que fichar() en
    fichajes: sin esto, dos peticiones casi simultáneas con el mismo
    token (el enlace abierto dos veces, p.ej. precarga del cliente de
    correo) podrían leer ambas "no usado todavía" antes de que ninguna
    marcara usado_en, y las dos entrarían con un token pensado para un
    solo uso. Devuelve cliente_fiscal_id si el token es válido y no
    caducado/usado, si no None."""
    conn = _db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute(
            "SELECT id, cliente_fiscal_id, expira_en, usado_en FROM clientes_fiscales_accesos WHERE token = ?",
            (token,),
        ).fetchone()
        if fila is None or fila["usado_en"] is not None:
            conn.rollback()
            return None
        if fila["expira_en"] < _db.now_iso():
            conn.rollback()
            return None
        conn.execute(
            "UPDATE clientes_fiscales_accesos SET usado_en = ? WHERE id = ?",
            (_db.now_iso(), fila["id"]),
        )
        conn.commit()
        return fila["cliente_fiscal_id"]
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def crear_acceso_facturacion(tenant_id: int, usuario_id: int) -> str:
    """Enlace de un solo uso para abrir facturacion.guildawork.com como el
    tenant del usuario actual -- ver app/rutas_facturacion_proxy.py."""
    token = secrets.token_urlsafe(32)
    ahora = _db.datetime.now()
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO facturacion_accesos (tenant_id, usuario_id, token, creado_en, expira_en) VALUES (?, ?, ?, ?, ?)",
            (
                tenant_id, usuario_id, token, ahora.isoformat(timespec="seconds"),
                (ahora + _db.timedelta(minutes=_db._MINUTOS_VIDA_ACCESO_FACTURACION)).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def consumir_acceso_facturacion(token: str) -> int | None:
    """Mismo cuidado de sección crítica que consumir_acceso_cliente_fiscal
    (BEGIN IMMEDIATE, un solo uso). Devuelve tenant_id si el token es
    válido y no caducado/usado, si no None."""
    conn = _db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute(
            "SELECT id, tenant_id, expira_en, usado_en FROM facturacion_accesos WHERE token = ?",
            (token,),
        ).fetchone()
        if fila is None or fila["usado_en"] is not None:
            conn.rollback()
            return None
        if fila["expira_en"] < _db.now_iso():
            conn.rollback()
            return None
        conn.execute(
            "UPDATE facturacion_accesos SET usado_en = ? WHERE id = ?",
            (_db.now_iso(), fila["id"]),
        )
        conn.commit()
        return fila["tenant_id"]
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def subir_documento_vencimiento(
    vencimiento_id: int, nombre_archivo: str, tipo_mime: str, contenido: bytes, origen: str = "cliente",
) -> int:
    """Guarda primero como BLOB local (garantiza que el documento queda
    a salvo aunque Nextcloud falle a medias) y, solo si el tenant tiene
    Nextcloud configurado y la subida sale bien, promueve el archivo
    ahí y vacía el BLOB -- best-effort, mismo criterio que el resto de
    integraciones opcionales: un fallo aquí deja el documento como BLOB,
    nunca lo pierde ni rompe la subida.

    Lanza ValueError si el archivo es o contiene una clave privada o un contenedor .p12/.pfx: no se guardan nunca."""
    from . import certificados
    motivo = certificados.contiene_clave_privada(contenido)
    if motivo:
        raise ValueError(f"Ese archivo {motivo}: no se guarda.")
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO vencimientos_fiscales_documentos "
            "(vencimiento_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en, origen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vencimiento_id, nombre_archivo, tipo_mime, len(contenido), contenido, _db.now_iso(),
             origen if origen in _db.ORIGENES_DOCUMENTO_VENCIMIENTO else "cliente"),
        )
        documento_id = cur.lastrowid
        conn.commit()

        try:
            from . import nextcloud
            fila = conn.execute(
                """SELECT t.nombre AS tenant_nombre FROM vencimientos_fiscales v
                   JOIN tenants t ON t.id = v.tenant_id WHERE v.id = ?""",
                (vencimiento_id,),
            ).fetchone()
            if fila is not None:
                ruta = f"{fila['tenant_nombre']}/vencimientos-fiscales/{documento_id}-{nombre_archivo}"
                nextcloud.subir_archivo(ruta, contenido)
                conn.execute(
                    "UPDATE vencimientos_fiscales_documentos SET ruta_nextcloud = ?, contenido = NULL WHERE id = ?",
                    (ruta, documento_id),
                )
                conn.commit()
        except Exception:
            pass  # se queda como BLOB local, comportamiento de siempre
        return documento_id
    finally:
        conn.close()


def contenido_documento_vencimiento(documento: sqlite3.Row) -> bytes:
    """Sirve el contenido de un documento sea cual sea su almacenamiento
    (BLOB local o Nextcloud) -- para que las rutas no tengan que saber
    dónde vive cada documento. A diferencia de la subida, aquí SÍ deja
    propagar un fallo de Nextcloud (app.nextcloud.ErrorNextcloud): es la
    acción principal de esta llamada, no un efecto secundario -- quien
    llama decide cómo mostrarlo (ver app/rutas_fiscal.py)."""
    if documento["ruta_nextcloud"]:
        from . import nextcloud
        return nextcloud.descargar_archivo(documento["ruta_nextcloud"])
    return documento["contenido"]


def listar_documentos_vencimiento(
    vencimiento_id: int, origen: str | None = None, excluir_origenes: tuple[str, ...] = (),
) -> list[sqlite3.Row]:
    """Todos los documentos del vencimiento, o solo los de un `origen`
    ('cliente' = lo que ha subido el cliente desde el portal)."""
    conn = _db.get_connection()
    try:
        sql = (
            "SELECT id, vencimiento_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en, origen "
            "FROM vencimientos_fiscales_documentos WHERE vencimiento_id = ?"
        )
        params: list = [vencimiento_id]
        if origen is not None:
            sql += " AND origen = ?"
            params.append(origen)
        if excluir_origenes:
            sql += f" AND origen NOT IN ({','.join('?' * len(excluir_origenes))})"
            params.extend(excluir_origenes)
        return conn.execute(sql + " ORDER BY creado_en, id", params).fetchall()
    finally:
        conn.close()


def eliminar_documentos_vencimiento_por_origen(vencimiento_id: int, origen: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM vencimientos_fiscales_documentos WHERE vencimiento_id = ? AND origen = ?",
            (vencimiento_id, origen),
        )
        conn.commit()
    finally:
        conn.close()


def _lista_de_dias(texto, minimo: int, maximo: int, tope: int) -> list[int]:
    """«14, 7 3» -> [14, 7, 3] (sin repetidos, de mayor a menor). Lanza ValueError si algo no es un número del rango."""
    if isinstance(texto, (list, tuple)):
        trozos = [str(t) for t in texto]
    else:
        trozos = [t for t in re.split(r"[\s,;]+", str(texto or "")) if t]
    dias = set()
    for t in trozos:
        if not t.isdigit() or not minimo <= int(t) <= maximo:
            raise ValueError(f"«{t}» no es un número de días válido ({minimo} a {maximo}).")
        dias.add(int(t))
    if len(dias) > tope:
        raise ValueError(f"Como máximo {tope} avisos.")
    return sorted(dias, reverse=True)


def obtener_config_recordatorios(tenant_id: int) -> dict:
    conn = _db.get_connection()
    try:
        f = conn.execute("SELECT * FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    if f is None:
        return {**_db.CONFIG_RECORDATORIOS_DEFECTO, "dias_antes": list(_db.CONFIG_RECORDATORIOS_DEFECTO["dias_antes"]), "dias_despues": []}
    try:
        antes = _db._lista_de_dias(f["dias_antes"], 0, 60, 99)
        despues = _db._lista_de_dias(f["dias_despues"], 1, 30, 99)
    except ValueError:
        antes, despues = list(_db.CONFIG_RECORDATORIOS_DEFECTO["dias_antes"]), []
    return {"dias_antes": antes, "dias_despues": sorted(despues), "avisar_equipo": bool(f["avisar_equipo"]),
            "asunto": f["asunto"] or "", "cuerpo": f["cuerpo"] or ""}


def guardar_config_recordatorios(tenant_id: int, dias_antes, dias_despues, avisar_equipo: bool, asunto: str = "", cuerpo: str = "") -> dict:
    """Valida y guarda. `dias_antes`: de 0 (el mismo día) a 60, hasta 6 avisos; `dias_despues`: de 1 a 30, hasta 4.
    Lanza ValueError con un mensaje legible si algo no vale."""
    antes = _db._lista_de_dias(dias_antes, 0, 60, _db.MAX_AVISOS_ANTES)
    despues = sorted(_db._lista_de_dias(dias_despues, 1, 30, _db.MAX_AVISOS_DESPUES))
    asunto, cuerpo = (asunto or "").strip()[:150], (cuerpo or "").strip()[:2000]
    if bool(asunto) != bool(cuerpo):
        raise ValueError("Para usar tu propio texto rellena el asunto y el cuerpo (o deja los dos vacíos).")
    conn = _db.get_connection()
    try:
        conn.execute(
            """INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id) DO UPDATE SET dias_antes = excluded.dias_antes, dias_despues = excluded.dias_despues,
                   avisar_equipo = excluded.avisar_equipo, asunto = excluded.asunto, cuerpo = excluded.cuerpo, actualizado_en = excluded.actualizado_en""",
            (tenant_id, ",".join(map(str, antes)), ",".join(map(str, despues)), 1 if avisar_equipo else 0, asunto or None, cuerpo or None, _db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return _db.obtener_config_recordatorios(tenant_id)


def vencimientos_sin_documentos_del_cliente(tenant_id: int, fecha_objetivo: str, dias_antes: int) -> list[sqlite3.Row]:
    """Vencimientos pendientes de `fecha_objetivo` en los que se pidió un documento y el cliente no ha subido nada,
    aún sin avisar al equipo de esta antelación. Con el responsable (`usuario_id`) si lo tiene."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT v.id, v.modelo, v.periodo, v.fecha_limite, v.documento_solicitado, v.usuario_id, c.nombre AS cliente_nombre
               FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               WHERE v.tenant_id = ? AND v.estado = 'pendiente' AND v.papelera_en IS NULL AND c.papelera_en IS NULL
                 AND v.fecha_limite >= ? AND v.fecha_limite < ?
                 AND trim(COALESCE(v.documento_solicitado, '')) <> ''
                 AND NOT EXISTS (SELECT 1 FROM vencimientos_fiscales_documentos d WHERE d.vencimiento_id = v.id AND d.origen = 'cliente')
                 AND NOT EXISTS (SELECT 1 FROM vencimientos_escalados e WHERE e.vencimiento_id = v.id AND e.dias_antes = ?)""",
            (tenant_id, fecha_objetivo, _db._fecha_exclusiva(fecha_objetivo), dias_antes),
        ).fetchall()
    finally:
        conn.close()


def marcar_vencimiento_escalado(vencimiento_id: int, dias_antes: int) -> bool:
    """True si es la primera vez que se avisa al equipo de este vencimiento y antelación."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO vencimientos_escalados (vencimiento_id, dias_antes, avisado_en) VALUES (?, ?, ?)",
            (vencimiento_id, dias_antes, _db.now_iso()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def destinatarios_aviso_vencimiento(tenant_id: int, usuario_id: int | None) -> list[int]:
    """A quién avisar de un vencimiento: su responsable si sigue en el despacho; si no, los supervisores."""
    conn = _db.get_connection()
    try:
        if usuario_id is not None and conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (usuario_id, tenant_id)).fetchone():
            return [usuario_id]
        return [f["id"] for f in conn.execute("SELECT id FROM usuarios WHERE tenant_id = ? AND supervisor_tenant = 1", (tenant_id,))]
    finally:
        conn.close()


def vencimientos_para_recordatorio_portal(fecha_objetivo: str, dias_antes: int, tenant_id: int | None = None) -> list[sqlite3.Row]:
    """Vencimientos pendientes que vencen justo `fecha_objetivo` (YYYY-MM-DD),
    de clientes con email y recordatorios activos, y a los que todavía no se
    ha enviado el recordatorio de esta antelación (negativa = después del
    vencimiento). Sin `tenant_id` cruza todos los despachos: solo la usa el
    hilo periódico del servidor."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT v.*, c.nombre AS cliente_nombre, c.email AS cliente_email, c.idioma AS cliente_idioma,
                      t.nombre AS tenant_nombre
               FROM vencimientos_fiscales v
               JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               JOIN tenants t ON t.id = v.tenant_id
               WHERE v.estado = 'pendiente' AND v.papelera_en IS NULL AND c.papelera_en IS NULL
                 AND c.recordatorios_portal = 1 AND c.email IS NOT NULL AND trim(c.email) <> ''
                 AND v.fecha_limite >= ? AND v.fecha_limite < ? AND (? IS NULL OR v.tenant_id = ?)
                 AND NOT EXISTS (SELECT 1 FROM vencimientos_recordatorios r
                                 WHERE r.vencimiento_id = v.id AND r.dias_antes = ?)""",
            (fecha_objetivo, _db._fecha_exclusiva(fecha_objetivo), tenant_id, tenant_id, dias_antes),
        ).fetchall()
    finally:
        conn.close()


def marcar_recordatorio_portal_enviado(vencimiento_id: int, dias_antes: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO vencimientos_recordatorios (vencimiento_id, dias_antes, enviado_en) VALUES (?, ?, ?)",
            (vencimiento_id, dias_antes, _db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_documento_vencimiento(documento_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM vencimientos_fiscales_documentos WHERE id = ?", (documento_id,),
        ).fetchone()
    finally:
        conn.close()


def crear_mensaje_vencimiento(vencimiento_id: int, autor: str, texto: str, usuario_id: int | None = None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO vencimientos_fiscales_mensajes (vencimiento_id, autor, usuario_id, texto, creado_en) "
            "VALUES (?, ?, ?, ?, ?)",
            (vencimiento_id, autor, usuario_id, texto.strip(), _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_mensajes_vencimiento(vencimiento_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT m.*, u.email AS usuario_email FROM vencimientos_fiscales_mensajes m "
            "LEFT JOIN usuarios u ON u.id = m.usuario_id "
            "WHERE m.vencimiento_id = ? ORDER BY m.creado_en",
            (vencimiento_id,),
        ).fetchall()
    finally:
        conn.close()


def marcar_mensajes_leidos(vencimiento_id: int, autor_que_lee: str) -> None:
    """Marca leídos los mensajes del OTRO autor -- si lee el cliente
    (autor_que_lee='cliente'), se marcan los de autor='empleado', y
    viceversa. Llamado al abrir la conversación desde cada lado."""
    otro_autor = "empleado" if autor_que_lee == "cliente" else "cliente"
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE vencimientos_fiscales_mensajes SET leido_en = ? "
            "WHERE vencimiento_id = ? AND autor = ? AND leido_en IS NULL",
            (_db.now_iso(), vencimiento_id, otro_autor),
        )
        conn.commit()
    finally:
        conn.close()


def crear_solicitud_acceso_portal(nombre: str, email: str, nif: str | None = None, mensaje: str | None = None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO solicitudes_acceso_portal (nombre, email, nif, mensaje, creado_en) VALUES (?, ?, ?, ?, ?)",
            (nombre.strip(), email.strip(), (nif or "").strip() or None, (mensaje or "").strip() or None, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_solicitudes_acceso_portal() -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM solicitudes_acceso_portal ORDER BY atendida ASC, creado_en DESC"
        ).fetchall()
    finally:
        conn.close()


def marcar_solicitud_atendida(solicitud_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE solicitudes_acceso_portal SET atendida = 1 WHERE id = ?", (solicitud_id,))
        conn.commit()
    finally:
        conn.close()


def listar_todos_los_clientes_fiscales() -> list[sqlite3.Row]:
    """Para el backoffice (admin, sin tenant fijo) -- a diferencia de
    listar_clientes_fiscales(tenant_id), esta cruza todos los tenants,
    con el nombre del tenant para que el admin sepa a cuál pertenece
    cada fila al vincular una solicitud de acceso."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT c.*, t.nombre AS tenant_nombre FROM clientes_fiscales c "
            "JOIN tenants t ON t.id = c.tenant_id WHERE c.papelera_en IS NULL ORDER BY t.nombre, c.nombre"
        ).fetchall()
    finally:
        conn.close()


def _nombre_de_archivo_seguro(nombre: str | None) -> str:
    nombre = (nombre or "").replace("\\", "/").rsplit("/", 1)[-1]
    nombre = "".join(c for c in nombre if c.isprintable() and c not in '<>:"|?*').strip(" .")
    return nombre[:200] or "documento"


def archivar_documento_cliente(
    usuario_id: int, cliente_fiscal_id: int, nombre: str, tipo_mime: str | None, contenido: bytes,
    categoria: str | None = None, origen: str = "subida", mensaje_correo_id: int | None = None, asunto_origen: str | None = None,
) -> tuple[str, int | None]:
    """Guarda un documento en el expediente de un cliente del despacho del usuario.
    Devuelve (resultado, id): 'ok', 'duplicado' (ya estaba el mismo archivo; id del existente),
    'grande', 'vacio', 'limite' o 'cliente' (no es un cliente de su despacho)."""
    if origen not in ("subida", "correo"):
        origen = "subida"
    if not contenido:
        return "vacio", None
    if len(contenido) > _db.MAX_DOCUMENTO_CLIENTE_BYTES:
        return "grande", None
    huella = hashlib.sha256(contenido).hexdigest()
    conn = _db.get_connection()
    try:
        u = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if u is None or u["tenant_id"] is None or conn.execute(
            "SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, u["tenant_id"])
        ).fetchone() is None:
            return "cliente", None
        repetido = conn.execute(
            "SELECT id FROM cliente_documentos WHERE cliente_fiscal_id = ? AND hash_sha256 = ?", (cliente_fiscal_id, huella)
        ).fetchone()
        if repetido:
            return "duplicado", repetido["id"]
        if conn.execute("SELECT COUNT(*) FROM cliente_documentos WHERE cliente_fiscal_id = ?", (cliente_fiscal_id,)).fetchone()[0] >= _db.MAX_DOCUMENTOS_POR_CLIENTE:
            return "limite", None
        mensaje_correo_id = _db._mensaje_correo_id_propio(conn, usuario_id, mensaje_correo_id)
        from . import almacen_documentos
        guardado, cifrado, sobre = almacen_documentos._sellar(u["tenant_id"], contenido)      # cifrado con la clave del despacho si lo tiene activado
        from . import cifrado_despacho
        nombre_seguro = _db._nombre_de_archivo_seguro(nombre)
        nombre_col, nombre_sellado = cifrado_despacho.sellar_nombre(u["tenant_id"], nombre_seguro) if cifrado else (nombre_seguro, None)
        if cifrado and cifrado_despacho.nombre_cifrado_en(cifrado_despacho.nivel_de(u["tenant_id"])):
            asunto_origen = None          # el asunto del correo de origen es un dato que el nivel no deja en claro
        cur = conn.execute(
            """INSERT INTO cliente_documentos
               (tenant_id, cliente_fiscal_id, nombre_archivo, nombre_cifrado, tipo_mime, tamano_bytes, contenido, categoria, origen,
                mensaje_correo_id, asunto_origen, subido_por, hash_sha256, creado_en, cifrado, sobre)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (u["tenant_id"], cliente_fiscal_id, nombre_col, nombre_sellado, (tipo_mime or "application/octet-stream")[:100],
             len(contenido), guardado, (categoria or "").strip()[:60] or None, origen, mensaje_correo_id,
             (asunto_origen or "").strip()[:200] or None, usuario_id, huella, _db.now_iso(), cifrado, sobre),
        )
        conn.commit()
        return "ok", cur.lastrowid
    finally:
        conn.close()


def registrar_acceso_cliente(tenant_id: int, cliente_fiscal_id: int, usuario_id: int | None, accion: str, detalle: str = "") -> bool:
    """Anota un acceso. Nunca lanza (es un rastro, no puede romper lo que se está haciendo) y no repite «ficha_vista»
    de la misma persona sobre el mismo cliente dentro de la ventana. Devuelve si ha escrito."""
    if accion not in _db.ACCIONES_ACCESO_CLIENTE or tenant_id is None:
        return False
    if detalle and "documento" in accion:
        from . import cifrado_despacho
        if cifrado_despacho.nombre_cifrado_en(cifrado_despacho.nivel_de(tenant_id)):
            detalle = ""          # el nombre del archivo va sellado: no se copia al registro de accesos
    try:
        conn = _db.get_connection()
        try:
            if accion in ("ficha_vista", "laboral_visto"):
                desde = (_db.datetime.now() - _db.timedelta(minutes=_db.VENTANA_FICHA_VISTA_MINUTOS)).isoformat(timespec="seconds")
                if conn.execute(
                    "SELECT 1 FROM cliente_accesos WHERE cliente_fiscal_id = ? AND usuario_id IS ? AND accion = ? AND creado_en >= ? LIMIT 1",
                    (cliente_fiscal_id, usuario_id, accion, desde),
                ).fetchone():
                    return False
            conn.execute(
                "INSERT INTO cliente_accesos (tenant_id, cliente_fiscal_id, usuario_id, accion, detalle, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, cliente_fiscal_id, usuario_id, accion, (detalle or "")[:200] or None, _db.now_iso()),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return False


def listar_accesos_cliente(tenant_id: int, cliente_fiscal_id: int, limite: int = 100) -> list[dict]:
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT a.id, a.accion, a.detalle, a.creado_en, a.usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email, '—') AS usuario
               FROM cliente_accesos a LEFT JOIN usuarios u ON u.id = a.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = a.usuario_id
               WHERE a.tenant_id = ? AND a.cliente_fiscal_id = ? ORDER BY a.id DESC LIMIT ?""",
            (tenant_id, cliente_fiscal_id, max(1, min(limite, 5000))))]
    finally:
        conn.close()


def purgar_accesos_antiguos(dias: int = _db.RETENCION_ACCESOS_DIAS) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute("DELETE FROM cliente_accesos WHERE creado_en < ?", ((_db.datetime.now() - _db.timedelta(days=dias)).isoformat(timespec="seconds"),))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def listar_documentos_cliente(tenant_id: int, cliente_fiscal_id: int, limite: int = 300) -> list[dict]:
    from . import acceso
    extra, extra_p = acceso.restriccion(tenant_id, "d.cliente_fiscal_id")
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT d.id, d.nombre_archivo, d.nombre_cifrado, d.tipo_mime, d.tamano_bytes, d.categoria, d.origen, d.asunto_origen, d.subido_por,
                      d.creado_en, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS subido_por_nombre
               FROM cliente_documentos d LEFT JOIN usuarios u ON u.id = d.subido_por LEFT JOIN usuario_perfil pf ON pf.usuario_id = d.subido_por
               WHERE d.tenant_id = ? AND d.cliente_fiscal_id = ?{extra} ORDER BY d.creado_en DESC, d.id DESC LIMIT ?""",
            (tenant_id, cliente_fiscal_id, *extra_p, max(1, min(limite, 1000))),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def obtener_documento_cliente(tenant_id: int, cliente_fiscal_id: int, documento_id: int) -> sqlite3.Row | None:
    from . import acceso
    extra, extra_p = acceso.restriccion(tenant_id, "cliente_fiscal_id")
    conn = _db.get_connection()
    try:
        return conn.execute(
            f"SELECT * FROM cliente_documentos WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?{extra}",
            (documento_id, tenant_id, cliente_fiscal_id, *extra_p),
        ).fetchone()
    finally:
        conn.close()


def eliminar_documento_cliente(usuario_id: int, cliente_fiscal_id: int, documento_id: int) -> bool:
    """Lo borra quien lo subió o un supervisor del despacho."""
    conn = _db.get_connection()
    try:
        u = conn.execute("SELECT tenant_id, supervisor_tenant FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if u is None or u["tenant_id"] is None:
            return False
        d = conn.execute(
            "SELECT subido_por FROM cliente_documentos WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?",
            (documento_id, u["tenant_id"], cliente_fiscal_id),
        ).fetchone()
        if d is None or not (d["subido_por"] == usuario_id or u["supervisor_tenant"]):
            return False
        conn.execute("DELETE FROM cliente_documentos WHERE id = ?", (documento_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def contar_documentos_cliente(tenant_id: int, cliente_fiscal_id: int) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM cliente_documentos WHERE tenant_id = ? AND cliente_fiscal_id = ?", (tenant_id, cliente_fiscal_id)
        ).fetchone()[0]
    finally:
        conn.close()


def listar_reglas_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT r.*, c.nombre AS categoria_nombre, c.color AS categoria_color, cf.nombre AS cliente_fiscal_nombre
               FROM correo_reglas r LEFT JOIN correo_categorias c ON c.id = r.categoria_id
               LEFT JOIN clientes_fiscales cf ON cf.id = r.cliente_fiscal_id
               WHERE r.usuario_id = ? ORDER BY r.id""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_regla_correo(usuario_id: int, regla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM correo_reglas WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def reglas_correo_aplicables(usuario_id: int, direccion: str | None, asunto: str | None) -> list[sqlite3.Row]:
    """Reglas avanzadas cuyas condiciones (todas las indicadas) coinciden.
    Remitente: "@dominio.com" = dominio, "x@y.com" = exacto, otro texto = contiene.
    Asunto: contiene, sin distinguir mayúsculas."""
    direccion = (direccion or "").strip().lower()
    asunto_min = (asunto or "").lower()
    resultado = []
    for r in _db.listar_reglas_correo(usuario_id):
        rp, ap = r["remitente_patron"], r["asunto_patron"]
        if rp:
            if rp.startswith("@"):
                ok = direccion.endswith(rp)
            elif "@" in rp:
                ok = direccion == rp
            else:
                ok = rp in direccion
            if not ok:
                continue
        if ap and ap not in asunto_min:
            continue
        resultado.append(r)
    return resultado


def categoria_id_por_remitente_correo(usuario_id: int, direccion: str | None) -> int | None:
    """Busca primero una regla de email exacto, luego una de dominio
    (`remitente_patron` empezando por "@")."""
    if not direccion:
        return None
    direccion = direccion.strip().lower()
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT categoria_id FROM correo_reglas_categoria
               WHERE usuario_id = ? AND remitente_patron = ?""",
            (usuario_id, direccion),
        ).fetchone()
        if fila:
            return fila["categoria_id"]
        dominio = "@" + direccion.split("@", 1)[1] if "@" in direccion else None
        if dominio:
            fila = conn.execute(
                """SELECT categoria_id FROM correo_reglas_categoria
                   WHERE usuario_id = ? AND remitente_patron = ?""",
                (usuario_id, dominio),
            ).fetchone()
            if fila:
                return fila["categoria_id"]
        return None
    finally:
        conn.close()
