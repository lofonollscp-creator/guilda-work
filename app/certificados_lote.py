"""Importación de certificados públicos en lote (K4): se suben varios ficheros (.cer, .crt, .pem), se revisan —cuáles son nuevos, cuáles ya estaban, cuáles no valen y a qué cliente pertenecen por su
NIF— y solo entonces se importan los nuevos, ya enlazados a su cliente cuando el NIF identifica a uno solo. Cada fichero pasa por las mismas comprobaciones que la importación suelta: se rechazan
claves privadas y contenedores, y nada se guarda hasta confirmar."""
from __future__ import annotations

import re

from . import certificados as ce
from . import db

MAX_FICHEROS = 40


def _nif(valor: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (valor or "").upper())


def _clientes_por_nif(tenant_id: int) -> dict[str, list[dict]]:
    por_nif: dict[str, list[dict]] = {}
    for c in db.listar_clientes_fiscales(tenant_id):
        n = _nif(c["nif"])
        if n:
            por_nif.setdefault(n, []).append({"id": c["id"], "nombre": c["nombre"]})
    return por_nif


def revisar(tenant_id: int, usuario_id: int, ficheros: list[tuple[str, bytes]]) -> list[dict]:
    """Una fila por fichero: `estado` es nuevo | duplicado | elegir | error, con su motivo, el certificado que trae y el cliente al que se enlazaría (si el NIF identifica a uno solo)."""
    ce._exigir(usuario_id, tenant_id)
    por_nif = _clientes_por_nif(tenant_id)
    conn = db.get_connection()
    try:
        existentes = {f["huella_sha256"] for f in conn.execute("SELECT huella_sha256 FROM certificados WHERE tenant_id = ?", (tenant_id,))}
    finally:
        conn.close()
    filas, vistas = [], set()
    for nombre, datos in ficheros[:MAX_FICHEROS]:
        fila = {"nombre": nombre, "estado": "error", "motivo": None, "sujeto": None, "caduca": None, "nif": None, "cliente": None, "huella": None}
        try:
            a = ce.analizar(datos)
        except ValueError as e:
            fila["motivo"] = str(e)
            filas.append(fila)
            continue
        if a["hoja"] is None:
            fila.update(estado="elegir", motivo="Trae varios certificados finales: súbelo suelto para elegir cuál es el del cliente.")
            filas.append(fila)
            continue
        info = a["_infos"][a["hoja"]]
        fila.update(sujeto=info["nombre_comun"] or info["sujeto"], caduca=(info["not_after"] or "")[:10], nif=info["nif_sugerido"], huella=a["hoja"])
        candidatos = por_nif.get(_nif(info["nif_sugerido"]), [])
        if len(candidatos) == 1:
            fila["cliente"] = candidatos[0]
        if a["hoja"] in existentes or a["hoja"] in vistas:
            fila.update(estado="duplicado", motivo="Ya está en el registro." if a["hoja"] in existentes else "Está repetido en esta misma subida.")
        else:
            fila["estado"] = "nuevo"
            vistas.add(a["hoja"])
        filas.append(fila)
    return filas


def importar(tenant_id: int, usuario_id: int, ficheros: list[tuple[str, bytes]]) -> dict:
    """Importa lo que `revisar` marca como nuevo y enlaza cada uno con su cliente cuando el NIF lo identifica. Devuelve {importados, enlazados, saltados, errores}."""
    resultado = {"importados": 0, "enlazados": 0, "saltados": 0, "errores": []}
    for fila, (nombre, datos) in zip(revisar(tenant_id, usuario_id, ficheros), ficheros[:MAX_FICHEROS]):
        if fila["estado"] != "nuevo":
            resultado["saltados"] += 1
            if fila["estado"] in ("error", "elegir"):
                resultado["errores"].append(f"{nombre}: {fila['motivo']}")
            continue
        try:
            r = ce.importar(tenant_id, usuario_id, datos, huella=fila["huella"], origen="importacion_lote")
        except ValueError as e:
            resultado["saltados"] += 1
            resultado["errores"].append(f"{nombre}: {e}")
            continue
        if not r["nuevo"]:
            resultado["saltados"] += 1
            continue
        resultado["importados"] += 1
        if fila["cliente"]:
            try:
                ce.editar(tenant_id, usuario_id, r["id"], cliente_fiscal_id=fila["cliente"]["id"])
                resultado["enlazados"] += 1
            except ValueError:
                pass
    return resultado
