"""«Tus datos» (Q9): el cliente descarga desde su portal una copia de lo suyo que hay en la plataforma, y puede pedir a su gestoría la supresión.

La copia es un ZIP con: sus datos de contacto y accesos (`datos.json`), sus conversaciones con la gestoría, sus peticiones, citas y avisos, todas sus facturas en CSV, y los documentos que subió o que
ve en su portal (facturas, peticiones, adjuntos de las conversaciones), con un tope de tamaño (lo que no cabe se lista en `omitidos.txt`). No lleva nada interno del despacho (notas internas, reglas,
cuentas contables ni lo que haya escrito el equipo para sí). La supresión NO es un botón que borra: el responsable de los datos es la gestoría, así que se le abre una conversación con la solicitud
(que queda en la auditoría) para que la atienda como corresponde con su deber de conservación."""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime

from . import db, facturas_contables as fc, portal_citas, portal_conversaciones, portal_novedades, portal_personas, portal_peticiones

TOPE_DOCUMENTOS_BYTES = 120 * 1024 * 1024
TOPE_DOCUMENTOS = 400


def _nombre_seguro(nombre: str, i: int) -> str:
    base = re.sub(r"[^A-Za-z0-9._\- ]+", "_", nombre or "archivo").strip(" .")[:80] or "archivo"
    return f"{i:03d}-{base}"


def _ids_de_documentos(cliente) -> list[int]:
    t, c = cliente["tenant_id"], cliente["id"]
    conn = db.get_connection()
    try:
        ids = [r[0] for r in conn.execute("SELECT documento_id FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND documento_id IS NOT NULL", (t, c)).fetchall()]
        ids += [r[0] for r in conn.execute("SELECT d.documento_id FROM portal_peticiones_documentos d JOIN portal_peticiones p ON p.id = d.peticion_id AND p.tenant_id = d.tenant_id "
                                           "WHERE p.tenant_id = ? AND p.cliente_fiscal_id = ?", (t, c)).fetchall()]
        ids += [r[0] for r in conn.execute("SELECT a.documento_id FROM portal_conversaciones_adjuntos a JOIN portal_conversaciones_mensajes m ON m.id = a.mensaje_id AND m.tenant_id = a.tenant_id "
                                           "JOIN portal_conversaciones v ON v.id = m.conversacion_id AND v.tenant_id = m.tenant_id WHERE v.tenant_id = ? AND v.cliente_fiscal_id = ?", (t, c)).fetchall()]
    finally:
        conn.close()
    return list(dict.fromkeys(ids))


def _facturas_csv(cliente) -> str:
    """Todas las facturas del cliente (también las pendientes y las devueltas) con base, IVA y total; sin cuentas ni notas internas."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT x.fecha, x.numero, x.tipo, x.tercero_nombre, x.tercero_nif, x.estado, x.total_centimos, COALESCE(SUM(l.base_centimos), 0) AS base, COALESCE(SUM(l.cuota_iva), 0) AS iva "
                             "FROM facturas_contables x LEFT JOIN facturas_contables_lineas l ON l.factura_id = x.id WHERE x.tenant_id = ? AND x.cliente_fiscal_id = ? "
                             "GROUP BY x.id, x.fecha, x.numero, x.tipo, x.tercero_nombre, x.tercero_nif, x.estado, x.total_centimos ORDER BY x.fecha, x.id", (cliente["tenant_id"], cliente["id"])).fetchall()
    finally:
        conn.close()
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    w.writerow(["Fecha", "Número", "Tipo", "Proveedor o cliente", "NIF", "Base imponible", "IVA", "Total", "Estado"])
    eur = lambda c: f"{(c or 0) / 100:.2f}".replace(".", ",")
    for f in filas:
        w.writerow([f["fecha"], f["numero"] if f["numero"] != "(por leer)" else "", "Emitida" if f["tipo"] == "emitida" else "Recibida", f["tercero_nombre"] if f["tercero_nombre"] != "(por leer)" else "",
                    f["tercero_nif"] or "", eur(f["base"]), eur(f["iva"]), eur(f["total_centimos"]), f["estado"]])
    return "\ufeff" + salida.getvalue()


def zip_de_mis_datos(cliente, email: str) -> bytes:
    """El ZIP con la copia de los datos de este cliente (ver el docstring del módulo). Nunca falla por un documento que no se pueda abrir: lo lista en `omitidos.txt`."""
    from . import almacen_documentos
    personas = [{"email": p["email"], "nombre": p["nombre"], "perfil": p["rol"], "avisos": p["avisos"], "titular": p["es_titular"]} for p in portal_personas.listar(cliente)]
    conversaciones = []
    for h in portal_conversaciones.listar(cliente):
        c = portal_conversaciones.obtener(cliente, h["id"])
        conversaciones.append({"asunto": c["asunto"], "estado": c["estado"], "creada": c["creado_en"], "mensajes": [{"de": "yo" if m["de"] == "cliente" else "la gestoría", "cuando": m["creado_en"], "texto": m["texto"],
                                                                                                                       "adjuntos": [a["nombre"] for a in m["adjuntos"]]} for m in c["mensajes"]]})
    datos = {"generado_en": datetime.now().isoformat(timespec="seconds"), "solicitado_por": email,
             "cliente": {"nombre": cliente["nombre"], "nif": cliente["nif"], "email": cliente["email"], "pais": cliente["pais"]}, "personas_con_acceso": personas,
             "peticiones": [{"titulo": p["titulo"], "estado": p["estado"], "fecha_limite": p["fecha_limite"], "creada": p["creado_en"]} for p in portal_peticiones.listar(cliente)],
             "citas": [{k: c.get(k) for k in ("canal", "motivo", "estado", "fecha_hora", "creado_en")} for c in portal_citas.listar(cliente)] if hasattr(portal_citas, "listar") else [],
             "avisos": [{"titulo": a["titulo"], "detalle": a["detalle"], "cuando": a["creado_en"]} for a in portal_novedades.listar(cliente, email, 500)]}
    memoria = io.BytesIO()
    omitidos: list[str] = []
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("datos.json", json.dumps(datos, ensure_ascii=False, indent=1))
        z.writestr("conversaciones.json", json.dumps(conversaciones, ensure_ascii=False, indent=1))
        z.writestr("facturas.csv", _facturas_csv(cliente))
        total = 0
        for i, doc_id in enumerate(_ids_de_documentos(cliente)[:TOPE_DOCUMENTOS], 1):
            try:
                d = almacen_documentos.leer_de_cliente_fiscal(cliente["tenant_id"], cliente["id"], doc_id)
                if d is None:
                    continue
                contenido = bytes(d["contenido"])
                if total + len(contenido) > TOPE_DOCUMENTOS_BYTES:
                    omitidos.append(f"{d['nombre_archivo']} (no cabe en la descarga: pídelo a tu gestoría)")
                    continue
                z.writestr("documentos/" + _nombre_seguro(d["nombre_archivo"], i), contenido)
                total += len(contenido)
            except Exception:  # noqa: BLE001 -- despacho cifrado y bloqueado, almacén caído…
                omitidos.append(f"documento {doc_id} (no se ha podido abrir ahora: pídelo a tu gestoría)")
        if omitidos:
            z.writestr("omitidos.txt", "\n".join(omitidos))
        z.writestr("LEEME.txt", "Copia de tus datos en el portal de tu gestoría.\n\n"
                                "datos.json: tus datos de contacto, las personas con acceso, tus peticiones, citas y avisos.\n"
                                "conversaciones.json: tus conversaciones con la gestoría.\nfacturas.csv: tus facturas enviadas y su estado.\n"
                                "documentos/: los archivos que has enviado o que ves en tu portal.\n")
    return memoria.getvalue()


def pedir_supresion(cliente, email: str) -> int:
    """Abre una conversación con la gestoría con la solicitud de supresión de los datos (RGPD). Devuelve el id de la conversación."""
    texto = (f"Solicito la supresión de mis datos personales conforme al artículo 17 del RGPD. Solicitud hecha desde el portal por {email} el {datetime.now().strftime('%d/%m/%Y')}. "
             "Os pido que me confirméis qué datos se pueden suprimir y cuáles debéis conservar por obligación legal.")
    return portal_conversaciones.iniciar(cliente, "Solicitud de supresión de mis datos (RGPD)", texto, "cliente", email)
