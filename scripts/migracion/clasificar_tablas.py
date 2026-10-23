#!/usr/bin/env python3
"""Clasifica las tablas del esquema para Citus (fase 0 de la migración a PostgreSQL).

Entrada: el JSON de inventario_esquema.py. Salida: CSV con la clasificación propuesta.

    python scripts/migracion/clasificar_tablas.py inventario.json > clasificacion.csv

Clases:
  distribuida        lleva tenant_id: se distribuye por él.
  distribuida+hija   no lo lleva, pero cuelga por FK de una distribuida: se le añade
                     tenant_id (copiado del padre) y entra en su misma colocación.
  distribuida+usuario  solo lleva usuario_id (datos personales): se le añade tenant_id
                     = despacho en el que se creó el dato.
  referencia         catálogo global pequeño, replicado en todos los nodos.
  local              solo en el coordinador (corpus jurídico compartido, operativa global).
  virtual            tabla FTS5: se sustituye por columna tsvector.
  revisar            sin regla clara: decisión manual.
"""
import csv
import json
import sys

REFERENCIA = {
    "tenants": "raíz del modelo multitenant",
    "usuarios": "identidad global: un usuario puede estar en varios despachos",
    "planes_guilda": "catálogo comercial global",
    "extras_guilda": "catálogo comercial global",
    "reglas_fiscales": "catálogo fiscal global (lo valida el titular)",
    "reglas_laborales": "catálogo laboral global",
}
LOCAL = {
    "errores_servidor": "registro técnico global",
    "latidos": "latidos de procesos globales",
    "salud_alertas": "alertas de salud globales",
    "leads_contacto": "formulario público de la web de Guilda (aún sin despacho)",
    "solicitudes_acceso_portal": "solicitudes públicas previas a tener despacho",
    "auditoria_control": "claves de control de la cadena de auditoría (valores globales)",
    "api_cambios_purgado": "marca de purga global",
    "contabilidad_tarifas": "tarifas de consumo globales y por ámbito (revisar)",
    "auditoria_backoffice": "acciones del backoffice (operador de plataforma)",
}
PERSONALES_GLOBALES = {  # usuario_id sin despacho propio: viajan con la identidad
    "usuario_perfil": "perfil de la persona, no del despacho",
    "dispositivos_push": "dispositivos de la persona",
    "tokens_api": "credenciales de la persona (con despacho opcional)",
    "ver_como_tokens": "suplantación por el operador de plataforma",
    "mcp_uso": "contador diario por persona",
    "api_idempotencia": "idempotencia por persona",
    "comunicados_cerrados": "preferencia por persona",
}


def main(ruta):
    inv = json.load(open(ruta))
    T = inv["tablas"]
    cols = {n: {c["nombre"] for c in t["columnas"]} for n, t in T.items()}
    tiene = {n for n in T if "tenant_id" in cols[n]}

    def clase_inicial(n):
        t = T[n]
        if t["virtual"]:
            return "virtual", "FTS5 → tsvector + índice GIN"
        if n in REFERENCIA:
            return "referencia", REFERENCIA[n]
        if n.startswith("jur_") and n not in tiene and not any(f["tabla"] in tiene for f in t["fks"]):
            return "local", "corpus jurídico compartido (sin despacho)"
        if n in LOCAL:
            return "local", LOCAL[n]
        if n in tiene:
            return "distribuida", "ya lleva tenant_id"
        if n in PERSONALES_GLOBALES:
            return "referencia", PERSONALES_GLOBALES[n] + " (asociada a usuarios)"
        if "usuario_id" in cols[n] or any(f["tabla"] == "usuarios" for f in t["fks"]):
            return "distribuida+usuario", "datos personales: añadir tenant_id de creación"
        return "revisar", "sin regla"

    clase = {n: clase_inicial(n) for n in T}
    # Una tabla sin tenant_id propio hereda del padre (por FK) que sea o vaya a ser
    # distribuida; se repite hasta que no cambie nada (cadenas de varios niveles).
    cambiado = True
    while cambiado:
        cambiado = False
        for n in T:
            if clase[n][0] not in ("revisar", "distribuida+usuario") or n in tiene:
                continue
            for f in T[n]["fks"]:
                if clase[n][0] == "revisar" and clase.get(f["tabla"], ("",))[0] == "referencia" and f["tabla"] != "usuarios":
                    clase[n] = ("referencia", f"hija de {f['tabla']} (referencia)")
                    cambiado = True
                    break
                if f["tabla"] != "usuarios" and clase.get(f["tabla"], ("",))[0].startswith("distribuida"):
                    if clase[n][0] != "distribuida+hija":
                        clase[n] = ("distribuida+hija", f"hereda tenant_id de {f['tabla']}")
                        cambiado = True
                    break
    filas = []
    for n in sorted(T):
        t = T[n]
        c, motivo = clase[n]
        u_sin = [u["columnas"] for u in t["unicos"] if u["origen"] != "pk" and "tenant_id" not in u["columnas"]]
        pk = [x["nombre"] for x in t["columnas"] if x["pk"]]
        filas.append(dict(
            tabla=n, clase=c, motivo=motivo, filas=t.get("filas", ""),
            tiene_tenant_id=int(n in tiene), tiene_usuario_id=int("usuario_id" in cols[n]),
            pk="+".join(pk), unicos_sin_tenant=" | ".join(",".join(u) for u in u_sin),
            fks_a=",".join(sorted({f["tabla"] for f in t["fks"]})),
            triggers=",".join(t["triggers"]),
            tiene_blob=int(any((x["tipo"] or "").upper() == "BLOB" for x in t["columnas"])),
        ))
    w = csv.DictWriter(sys.stdout, fieldnames=list(filas[0]))
    w.writeheader()
    w.writerows(filas)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
