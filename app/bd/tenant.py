"""Modelo multitenant (fase 6 de la migración a PostgreSQL + Citus): a qué despacho (`tenant_id`) pertenece cada fila de cada tabla.

Citus reparte las tablas por `tenant_id`, así que TODA tabla con datos de un despacho debe llevarlo. Hoy 105 tablas lo tienen; las demás lo heredan:

  * ``propio``          la tabla ya tiene `tenant_id`.
  * ``usuario``         datos personales (correo, notas, IA…): el despacho en el que se crearon. Hoy, el despacho principal del usuario (`usuarios.tenant_id`);
                        con usuarios en varios despachos (tabla `usuarios_tenants`) lo fijará el despacho activo al insertar.
  * ``hija``            cuelga por clave foránea de otra tabla con despacho: lo hereda de su padre.
  * ``referencia``      catálogo global pequeño, replicado en todos los nodos.
  * ``local``           solo en el coordinador (corpus jurídico compartido, registros técnicos globales).

No añade triggers a SQLite (chocarían con los que ya llevan `tareas_outlook`, `notas`… y harían saltar su historial): en SQLite solo sirve para medir y rellenar
una COPIA; el relleno definitivo ocurre al cargar los datos en PostgreSQL (fase 8), donde cada inserción toma el despacho de la conexión (`app.tenant_id`).
tests/test_tenant_modelo.py obliga a decidir la clase de cada tabla nueva.
"""
from __future__ import annotations

import json
from pathlib import Path

# Despacho reservado para lo que no pertenece a ningún despacho (personas sin despacho —operador de plataforma, usuario local— y eventos de plataforma): Citus no admite
# NULL en la columna de distribución. Existe en el esquema de PostgreSQL (app/bd/esquema_pg/07_semillas.sql); no es un despacho de verdad y no se puede borrar.
TENANT_PLATAFORMA = 0
NOMBRE_PLATAFORMA = "Plataforma"

# --- Decisiones manuales -------------------------------------------------------------------------------------------------------------------------
REFERENCIA = {
    "tenants": "raíz del modelo multitenant",
    "usuarios": "identidad global: un usuario puede estar en varios despachos",
    "usuarios_tenants": "pertenencia usuario ↔ despacho (puede haber varias por usuario)",
    "planes_guilda": "catálogo comercial global",
    "extras_guilda": "catálogo comercial global",
    "reglas_fiscales": "catálogo fiscal global (lo valida el titular)",
    "reglas_laborales": "catálogo laboral global",
    "usuario_perfil": "perfil de la persona, no del despacho",
    "dispositivos_push": "dispositivos de la persona",
    "tokens_api": "credenciales de la persona",
    "ver_como_tokens": "suplantación por el operador de plataforma",
    "mcp_uso": "contador diario por persona",
    "api_idempotencia": "idempotencia por persona",
    "comunicados_cerrados": "preferencia por persona",
}
LOCAL = {
    "errores_servidor": "registro técnico global",
    "latidos": "latidos de procesos globales",
    "salud_alertas": "alertas de salud globales",
    "leads_contacto": "formulario público de la web de Guilda (aún sin despacho)",
    "solicitudes_acceso_portal": "solicitudes públicas previas a tener despacho",
    "auditoria_control": "claves de control de la cadena de auditoría (valores globales)",
    "api_cambios_purgado": "marca de purga global",
    "contabilidad_tarifas": "tarifas de consumo globales y por ámbito",
    "auditoria_backoffice": "acciones del operador de plataforma",
    "bd_esquema_version": "versión del esquema",
}
# Tablas que YA tienen tenant_id pero con filas sin él: se rellenan desde la persona.
RELLENO_DE_NULOS = {"fichajes": "usuario_id", "auditoria_eventos": "usuario_id"}
# Tablas con tenant_id nullable que se quedan con filas sin despacho a propósito (eventos de plataforma): se ven en el informe, no cuentan como error.
NULOS_ADMITIDOS = {"jur_auditoria": "eventos de plataforma (registrar políticas, habilitar fuentes)"}


class Via:
    """Cómo se deduce el despacho de una fila: de la columna `columna` (clave foránea hacia `padre`, cuya clave es `clave`)."""

    def __init__(self, columna: str, padre: str, clave: str, obligatoria: bool):
        self.columna, self.padre, self.clave, self.obligatoria = columna, padre, clave, obligatoria

    def __repr__(self):
        return f"{self.columna}→{self.padre}.{self.clave}{'' if self.obligatoria else '?'}"

    def como_dict(self):
        return {"columna": self.columna, "padre": self.padre, "clave": self.clave, "obligatoria": self.obligatoria}


class Clase:
    def __init__(self, nombre: str, motivo: str, via: list[Via] | None = None):
        self.nombre, self.motivo, self.via = nombre, motivo, via or []

    def como_dict(self):
        return {"clase": self.nombre, "motivo": self.motivo, "via": [v.como_dict() for v in self.via]}

    @classmethod
    def desde_dict(cls, d):
        return cls(d["clase"], d["motivo"], [Via(v["columna"], v["padre"], v["clave"], v["obligatoria"]) for v in d["via"]])


# --- Lectura del esquema -------------------------------------------------------------------------------------------------------------------------
def tablas_de_datos(conn) -> list[str]:
    maestro = conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    virtuales = {r[1] for r in maestro if r[0] == "table" and (r[2] or "").upper().startswith("CREATE VIRTUAL")}
    sombras = tuple(v + "_" for v in virtuales)
    return sorted(r[1] for r in maestro if r[0] == "table" and not r[1].startswith("sqlite_") and r[1] not in virtuales and not r[1].startswith(sombras))


def _info(conn, tabla):
    cols = conn.execute(f'PRAGMA table_info("{tabla}")').fetchall()
    pk = [c[1] for c in sorted((c for c in cols if c[5]), key=lambda c: c[5])]
    fks = {}
    for f in conn.execute(f'PRAGMA foreign_key_list("{tabla}")').fetchall():
        fks.setdefault(f[0], []).append(f)
    return {"columnas": {c[1]: {"nonulo": bool(c[3]) or c[1] in pk, "pk": c[1] in pk} for c in cols}, "pk": pk, "fks": fks}


def _vias_candidatas(conn, tabla, info, hacia):
    """Claves foráneas de una sola columna de `tabla` que apuntan a tablas de `hacia`, mejor primero: obligatorias, luego las de la clave primaria."""
    res = []
    for filas in info["fks"].values():
        if len(filas) != 1:
            continue
        f = filas[0]
        col, padre, clave = f[3], f[2], f[4]
        if padre not in hacia:
            continue
        if clave is None:
            pk = _info(conn, padre)["pk"]
            clave = pk[0] if len(pk) == 1 else None
        if clave is None:
            continue
        c = info["columnas"][col]
        res.append(Via(col, padre, clave, c["nonulo"]))
    return sorted(res, key=lambda v: (not v.obligatoria, not info["columnas"][v.columna]["pk"], v.columna))


# --- Clasificación -------------------------------------------------------------------------------------------------------------------------------
def clasificar(conn) -> dict[str, Clase]:
    tablas = tablas_de_datos(conn)
    infos = {t: _info(conn, t) for t in tablas}
    tiene = {t for t in tablas if "tenant_id" in infos[t]["columnas"]}
    clases: dict[str, Clase] = {}
    for t in tablas:
        if t in REFERENCIA:
            clases[t] = Clase("referencia", REFERENCIA[t])
        elif t in LOCAL:
            clases[t] = Clase("local", LOCAL[t])
        elif t.startswith("jur_") and t not in tiene and not any(f[0][2] in tiene for f in infos[t]["fks"].values()):
            clases[t] = Clase("local", "corpus jurídico compartido (sin despacho)")
        elif t in tiene:
            via = [Via(RELLENO_DE_NULOS[t], "usuarios", "id", False)] if t in RELLENO_DE_NULOS else []
            clases[t] = Clase("propio", "ya lleva tenant_id" + (" (filas sin él: se rellenan desde la persona)" if via else ""), via)

    def via_usuario(t):
        i = infos[t]["columnas"]
        if "usuario_id" in i:
            col = "usuario_id"
        else:                                                                       # sin «usuario_id»: solo vale una única clave obligatoria hacia usuarios (no un «hecho_por» opcional)
            candidatas = [f[0][3] for f in infos[t]["fks"].values() if f[0][2] == "usuarios" and i[f[0][3]]["nonulo"]]
            col = candidatas[0] if len(candidatas) == 1 else None
        return Via(col, "usuarios", "id", i[col]["nonulo"]) if col else None

    # Una tabla es «hija» si tiene una clave foránea OBLIGATORIA hacia una tabla con despacho; si no, «usuario» (datos personales) si hay una persona a quien atribuirla.
    # Se repite hasta que no cambie nada: los padres se resuelven antes que las hijas, en cadenas de varios niveles.
    pendientes = [t for t in tablas if t not in clases]
    cambiado = True
    while pendientes and cambiado:
        cambiado = False
        for t in list(pendientes):
            con_despacho = {k for k, c in clases.items() if c.nombre in ("propio", "usuario", "hija")}
            vias = _vias_candidatas(conn, t, infos[t], con_despacho)
            uv = via_usuario(t)
            espera = any(f[0][2] in pendientes and f[0][2] != t and infos[t]["columnas"][f[0][3]]["nonulo"] for f in infos[t]["fks"].values() if len(f) == 1)
            if any(v.obligatoria for v in vias):
                clases[t] = Clase("hija", "hereda el despacho de " + ", ".join(v.padre for v in vias[:2]) + (" (o de la persona)" if uv else ""), vias + ([uv] if uv else []))
            elif espera:
                continue                                                           # su padre obligatorio aún no está resuelto
            elif uv is not None:
                clases[t] = Clase("usuario", "datos personales: despacho en que se crearon" + (" (cruza con " + vias[0].padre + ")" if vias else ""), vias + [uv])
            elif vias:
                clases[t] = Clase("hija", "hereda el despacho de " + ", ".join(v.padre for v in vias[:2]) + " (clave opcional)", vias)
            else:
                refs = _vias_candidatas(conn, t, infos[t], {k for k, c in clases.items() if c.nombre == "referencia" and k not in ("usuarios", "tenants", "usuarios_tenants")})
                if not refs:
                    continue
                clases[t] = Clase("referencia", f"hija de {refs[0].padre} (referencia)")
            pendientes.remove(t)
            cambiado = True
    for t in pendientes:
        clases[t] = Clase("revisar", "sin tenant_id, ni padre con despacho, ni usuario: decidir a mano")
    return clases


FICHERO_MODELO = Path(__file__).resolve().parent / "tenant_modelo.json"


def escribir_modelo(conn, ruta: Path = FICHERO_MODELO) -> dict:
    """Guarda la clasificación del esquema ACTUAL de `conn` (que debe ser el limpio de init_db, sin columnas añadidas por rellenar())."""
    modelo = {t: c.como_dict() for t, c in sorted(clasificar(conn).items())}
    ruta.write_text(json.dumps(modelo, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return modelo


def cargar_modelo() -> dict[str, Clase]:
    """El modelo confirmado en el repositorio (app/bd/tenant_modelo.json): no depende de que `rellenar()` haya añadido ya las columnas."""
    return {t: Clase.desde_dict(d) for t, d in json.loads(FICHERO_MODELO.read_text(encoding="utf-8")).items()}


def orden_de_relleno(clases: dict[str, Clase]) -> list[str]:
    """Primero las tablas cuyo despacho no depende de otra; después las que lo heredan, padres antes que hijas."""
    tablas = [t for t, c in clases.items() if c.nombre in ("propio", "usuario", "hija")]
    hecho, orden = set(), []
    while len(orden) < len(tablas):
        avance = False
        for t in tablas:
            if t in hecho:
                continue
            pendiente = [v.padre for v in clases[t].via if v.padre in clases and clases[v.padre].nombre in ("propio", "usuario", "hija") and v.padre not in hecho and v.padre != t]
            if not pendiente:
                hecho.add(t)
                orden.append(t)
                avance = True
        if not avance:
            raise RuntimeError("ciclo en la herencia del despacho: " + ", ".join(sorted(set(tablas) - hecho)))
    return orden


def _expresion(t: str, v: Via) -> str:
    return f'(SELECT p.tenant_id FROM "{v.padre}" p WHERE p."{v.clave}" = "{t}"."{v.columna}")'


def sql_relleno(t: str, clase: Clase, por_defecto: int | None = None) -> str | None:
    """UPDATE que rellena `tenant_id` donde falta. Con `por_defecto` (el despacho «Plataforma»), lo que no se deduce de la persona ni del padre acaba ahí; sin él, queda sin despacho."""
    if not clase.via:
        if por_defecto is None:
            return None
        return f'UPDATE "{t}" SET tenant_id = {int(por_defecto)} WHERE tenant_id IS NULL'
    if clase.nombre == "propio":
        cuerpo = _expresion(t, clase.via[0])
    else:
        cuerpo = "COALESCE(" + ", ".join(_expresion(t, v) for v in clase.via) + ")" if len(clase.via) > 1 else _expresion(t, clase.via[0])
    if por_defecto is not None:
        return f'UPDATE "{t}" SET tenant_id = COALESCE({cuerpo}, {int(por_defecto)}) WHERE tenant_id IS NULL'
    return f'UPDATE "{t}" SET tenant_id = {cuerpo} WHERE tenant_id IS NULL AND {cuerpo} IS NOT NULL'


# --- Relleno e informe (sobre una COPIA en SQLite) -----------------------------------------------------------------------------------------------
def rellenar(conn, crear_columnas: bool = False, por_defecto: int | None = None) -> dict[str, int]:
    """Rellena `tenant_id` donde falta, en orden. Con `crear_columnas` añade la columna a las tablas que no la tienen. SOLO PARA COPIAS de SQLite (quita y repone los disparadores): nunca sobre la base viva. Idempotente.
    `por_defecto=TENANT_PLATAFORMA` manda al despacho «Plataforma» lo que no se puede deducir (personas sin despacho, eventos de plataforma)."""
    clases = cargar_modelo()
    cambios = {}
    # Los disparadores de SQLite (historial de cambios, versión de tareas…) saltarían con cada UPDATE y ensuciarían la copia: se quitan durante el relleno y se restauran.
    disparadores = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL").fetchall()
    for nombre, _ in disparadores:
        conn.execute(f'DROP TRIGGER IF EXISTS "{nombre}"')
    try:
        existentes = set(tablas_de_datos(conn))
        for t in orden_de_relleno(clases):
            if t not in existentes:
                continue
            cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')}
            if "tenant_id" not in cols:
                if not crear_columnas:
                    continue
                conn.execute(f'ALTER TABLE "{t}" ADD COLUMN tenant_id INTEGER')
            sql = sql_relleno(t, clases[t], por_defecto)
            if sql:
                cambios[t] = conn.execute(sql).rowcount
    finally:
        for _, sql in disparadores:
            conn.execute(sql)
        conn.commit()
    return cambios


def informe(conn) -> dict:
    """Por tabla: filas, con despacho, sin él y filas cuyos padres discrepan. Solo lee."""
    clases = cargar_modelo()
    existentes = set(tablas_de_datos(conn))
    out = {}
    for t, c in sorted(clases.items()):
        if c.nombre in ("referencia", "local") or t not in existentes:
            continue
        cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')}
        total = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        d = {"clase": c.nombre, "filas": total, "via": [repr(v) for v in c.via]}
        if "tenant_id" in cols:
            d["con_despacho"] = conn.execute(f'SELECT COUNT(*) FROM "{t}" WHERE tenant_id IS NOT NULL').fetchone()[0]
            d["sin_despacho"] = total - d["con_despacho"]
            d["admitidos"] = t in NULOS_ADMITIDOS
        else:
            d["con_despacho"] = d["sin_despacho"] = None
        if len(c.via) > 1 and "tenant_id" in cols:
            comparar = [f'(SELECT p.tenant_id FROM "{v.padre}" p WHERE p."{v.clave}" = "{t}"."{v.columna}")' for v in c.via]
            conflictos = 0
            for i in range(len(comparar)):
                for j in range(i + 1, len(comparar)):
                    conflictos += conn.execute(f'SELECT COUNT(*) FROM "{t}" WHERE {comparar[i]} IS NOT NULL AND {comparar[j]} IS NOT NULL AND {comparar[i]} != {comparar[j]}').fetchone()[0]
            d["padres_en_desacuerdo"] = conflictos
        if "tenant_id" in cols and c.nombre in ("hija", "propio") and c.via:
            v = c.via[0]
            d["distinto_del_padre"] = conn.execute(
                f'SELECT COUNT(*) FROM "{t}" WHERE tenant_id IS NOT NULL AND (SELECT p.tenant_id FROM "{v.padre}" p WHERE p."{v.clave}" = "{t}"."{v.columna}") IS NOT NULL '
                f'AND tenant_id != (SELECT p.tenant_id FROM "{v.padre}" p WHERE p."{v.clave}" = "{t}"."{v.columna}")').fetchone()[0]
        out[t] = d
    return out
