"""Motor de avisos del control fiscal, v2 (especificación de control fiscal, RF-12 y sección 14).

Antes cada cosa avisaba por su cuenta: un push único a los 7 días, un hilo para certificados, otro para traspasos… y un aviso se mandaba y ahí acababa. Este motor da **un sitio único**
para lo que exige actuar sobre una obligación o un traspaso:

- **Alerta con clave única** por objeto, tipo y fecha (`UNIQUE(tenant_id, clave)`): pasar la evaluación cien veces nunca crea dos alertas, y es lo que garantiza «sin duplicados».
- **Acuse sin cerrar el objeto**: quien la recibe dice «lo he visto, lo llevo» (con nota); la alerta deja de insistir y de escalar, pero la obligación sigue abierta y la alerta sigue visible hasta que
  la obligación se resuelve. Acusar no presenta nada.
- **Escalado**: si nadie acusa en `escalar_horas_*` horas, sube a la coordinación de la oficina del cliente y, si pasa el mismo tiempo, a la dirección. Una alerta urgente sin acusar se repite cada
  `reenviar_horas` (hasta `max_reenvios`).
- **Se cierra sola**: cuando la obligación se presenta, se anula o se marca «no aplica», la alerta pasa a «resuelta» con ese motivo.
- **Cada despacho decide**: viene apagado (nada cambia hasta que la dirección lo enciende). Encendido, sustituye al recordatorio único de 7 días y al escalado de traspasos de antes para ese despacho.
- Observabilidad: tiempo hasta el acuse, sin atender, escaladas, fallos de entrega y duplicados (siempre 0 por construcción; se mide igualmente).

Entrega por la campana y el push de siempre (`notificaciones.crear_y_enviar`). Los textos de las alertas se guardan en castellano, como el resto de avisos internos."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import acceso, auditoria, db, obligaciones, traspasos

INTERVALO_SEGUNDOS = 30 * 60
TIPOS = ("obligacion_vencida", "obligacion_proxima", "obligacion_bloqueada", "traspaso_pendiente", "certificado_caducidad", "expediente_vencido")
SEVERIDADES = ("atencion", "urgente")
ESTADOS = ("abierta", "acusada", "resuelta")
POR_DEFECTO = {"activo": False, "dias_antes": [7, 3, 1], "dias_certificados": [30, 15, 7, 1], "escalar_horas_urgente": 24, "escalar_horas_atencion": 72, "reenviar_horas": 24, "max_reenvios": 3}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS avisos_config (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    activo INTEGER NOT NULL DEFAULT 0,
    dias_antes TEXT NOT NULL DEFAULT '7,3,1',
    escalar_horas_urgente INTEGER NOT NULL DEFAULT 24,
    escalar_horas_atencion INTEGER NOT NULL DEFAULT 72,
    reenviar_horas INTEGER NOT NULL DEFAULT 24,
    max_reenvios INTEGER NOT NULL DEFAULT 3
);
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    clave TEXT NOT NULL,
    tipo TEXT NOT NULL,
    severidad TEXT NOT NULL CHECK (severidad IN ('atencion', 'urgente')),
    objeto_tipo TEXT NOT NULL,
    objeto_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER REFERENCES clientes_fiscales(id),
    titulo TEXT NOT NULL,
    detalle TEXT,
    url TEXT,
    destinatario_id INTEGER REFERENCES usuarios(id),
    nivel INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'acusada', 'resuelta')),
    umbral INTEGER,
    creado_en TEXT NOT NULL,
    ultimo_envio_en TEXT,
    envios INTEGER NOT NULL DEFAULT 0,
    fallos INTEGER NOT NULL DEFAULT 0,
    escalada_en TEXT,
    acusada_por INTEGER REFERENCES usuarios(id),
    acusada_en TEXT,
    nota_acuse TEXT,
    resuelta_en TEXT,
    motivo_resolucion TEXT,
    UNIQUE (tenant_id, clave)
);
CREATE INDEX IF NOT EXISTS idx_alertas_estado ON alertas(tenant_id, estado);
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "avisos_config", "dias_certificados", "TEXT NOT NULL DEFAULT '30,15,7,1'")


# --- Configuración -----------------------------------------------------------------------------------------------------------------------------
def config(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM avisos_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    if f is None:
        return dict(POR_DEFECTO)
    return {"activo": bool(f["activo"]), "dias_antes": [int(x) for x in f["dias_antes"].split(",") if x.strip()], "dias_certificados": [int(x) for x in (f["dias_certificados"] or "").split(",") if x.strip()] or [30, 15, 7, 1], "escalar_horas_urgente": f["escalar_horas_urgente"],
            "escalar_horas_atencion": f["escalar_horas_atencion"], "reenviar_horas": f["reenviar_horas"], "max_reenvios": f["max_reenvios"]}


def activo(tenant_id: int) -> bool:
    return config(tenant_id)["activo"]


def _entero(valor, minimo: int, maximo: int, nombre: str) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"«{nombre}» debe ser un número.") from None
    if not minimo <= n <= maximo:
        raise ValueError(f"«{nombre}» debe estar entre {minimo} y {maximo}.")
    return n


def guardar_config(tenant_id: int, usuario_id: int, *, activo: bool, dias_antes, escalar_horas_urgente, escalar_horas_atencion, reenviar_horas, max_reenvios, dias_certificados=None) -> dict:
    if not acceso.es_directivo(usuario_id) or (db.tenant_de_usuario(usuario_id) or {"id": None})["id"] != tenant_id:
        raise ValueError("Solo la dirección del despacho (supervisores) puede cambiar los avisos.")
    if isinstance(dias_antes, str):
        dias_antes = [x for x in dias_antes.replace(";", ",").split(",") if x.strip()]
    dias = sorted({_entero(x, 0, 60, "días antes") for x in (dias_antes or [])}, reverse=True)
    if not dias or len(dias) > 5:
        raise ValueError("Indica entre 1 y 5 plazos de aviso, en días (por ejemplo 7, 3, 1).")
    if dias_certificados is None:
        dias_cert = config(tenant_id)["dias_certificados"]
    else:
        if isinstance(dias_certificados, str):
            dias_certificados = [x for x in dias_certificados.replace(";", ",").split(",") if x.strip()]
        dias_cert = sorted({_entero(x, 0, 365, "días antes (certificados)") for x in dias_certificados}, reverse=True)
        if not dias_cert or len(dias_cert) > 6:
            raise ValueError("Indica entre 1 y 6 plazos de aviso para los certificados, en días (por ejemplo 30, 15, 7, 1).")
    vals = (_entero(escalar_horas_urgente, 1, 720, "escalar urgentes"), _entero(escalar_horas_atencion, 1, 720, "escalar el resto"), _entero(reenviar_horas, 1, 720, "repetir cada"), _entero(max_reenvios, 0, 20, "repeticiones"))
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO avisos_config (tenant_id, activo, dias_antes, escalar_horas_urgente, escalar_horas_atencion, reenviar_horas, max_reenvios, dias_certificados) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(tenant_id) DO UPDATE SET activo = excluded.activo, dias_antes = excluded.dias_antes, dias_certificados = excluded.dias_certificados, escalar_horas_urgente = excluded.escalar_horas_urgente, "
                     "escalar_horas_atencion = excluded.escalar_horas_atencion, reenviar_horas = excluded.reenviar_horas, max_reenvios = excluded.max_reenvios",
                     (tenant_id, int(bool(activo)), ",".join(map(str, dias)), *vals, ",".join(map(str, dias_cert))))
        auditoria.registrar(tenant_id, usuario_id, "avisos.config", "despacho", tenant_id, {"activo": bool(activo), "dias_antes": dias, "dias_certificados": dias_cert, "escalar_urgente_h": vals[0], "escalar_atencion_h": vals[1], "repetir_h": vals[2], "max": vals[3]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return config(tenant_id)


# --- Destinatarios -----------------------------------------------------------------------------------------------------------------------------
def _directivos(tenant_id: int) -> list[int]:
    return [u for u in db.usuarios_de_tenant(tenant_id) if acceso.es_directivo(u)]


def _coordinadores(tenant_id: int, oficina_id) -> list[int]:
    if oficina_id is None:
        return []
    conn = db.get_connection()
    try:
        hoy = date.today().isoformat()
        return [f[0] for f in conn.execute("SELECT DISTINCT usuario_id FROM membresias WHERE tenant_id = ? AND rol = 'coordinador' AND alcance_tipo = 'oficina' AND alcance_id = ? AND revocada_en IS NULL "
                                           "AND vigente_desde <= ? AND (vigente_hasta IS NULL OR vigente_hasta >= ?)", (tenant_id, oficina_id, hoy, hoy))]
    finally:
        conn.close()


# --- Evaluación: de qué hay que avisar --------------------------------------------------------------------------------------------------------
def _candidatas(tenant_id: int, hoy: date, dias_antes: list[int], dias_certificados: list[int] | None = None) -> dict[str, dict]:
    maximo = max(dias_antes)
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT v.id, v.cliente_fiscal_id, v.usuario_id, v.modelo, v.periodo, substr(v.fecha_limite, 1, 10) AS limite, v.bloqueada, v.bloqueo_motivo, c.nombre AS cliente, c.responsable_id, c.oficina_id "
            "FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id WHERE v.tenant_id = ? AND v.papelera_en IS NULL AND c.papelera_en IS NULL AND v.fase IN "
            f"({','.join('?' * len(obligaciones.ACTIVAS))})", (tenant_id, *obligaciones.ACTIVAS)).fetchall()
        traspasos = conn.execute(
            "SELECT t.id, t.cliente_fiscal_id, t.a_usuario_id, c.nombre AS cliente, c.oficina_id, (SELECT MIN(substr(v.fecha_limite, 1, 10)) FROM vencimientos_fiscales v WHERE v.cliente_fiscal_id = t.cliente_fiscal_id "
            "AND v.papelera_en IS NULL AND v.fase IN ('pendiente', 'en_preparacion', 'en_revision', 'aprobada')) AS limite FROM traspasos t JOIN clientes_fiscales c ON c.id = t.cliente_fiscal_id "
            "WHERE t.tenant_id = ? AND t.estado = 'pendiente'", (tenant_id,)).fetchall()
    finally:
        conn.close()
    res: dict[str, dict] = {}
    for f in filas:
        dias = (date.fromisoformat(f["limite"]) - hoy).days
        base = {"objeto_tipo": "obligacion", "objeto_id": f["id"], "cliente_fiscal_id": f["cliente_fiscal_id"], "url": f"/fiscal/vencimientos/{f['id']}/editar", "oficina_id": f["oficina_id"],
                "destinatario": f["responsable_id"] or f["usuario_id"], "dias": dias}
        etiqueta = f"{f['modelo']} {f['periodo']} · {f['cliente']}"
        if dias < 0:
            res[f"obl:{f['id']}:{f['limite']}:vencida"] = base | {"tipo": "obligacion_vencida", "severidad": "urgente", "titulo": "Obligación vencida sin presentar", "detalle": f"{etiqueta}: venció el {f['limite']} (hace {-dias} días)."}
        elif dias <= maximo:
            umbral = min(d for d in dias_antes if dias <= d)
            res[f"obl:{f['id']}:{f['limite']}:proxima"] = base | {"tipo": "obligacion_proxima", "severidad": "urgente" if dias <= 1 else "atencion", "umbral": umbral,
                                                                  "titulo": "Obligación a punto de vencer", "detalle": f"{etiqueta}: vence {'hoy' if dias == 0 else 'mañana' if dias == 1 else f'en {dias} días'} ({f['limite']})."}
        if f["bloqueada"] and 0 <= dias <= 7:
            res[f"obl:{f['id']}:{f['limite']}:bloqueada"] = base | {"tipo": "obligacion_bloqueada", "severidad": "atencion", "titulo": "Obligación bloqueada con el plazo cerca",
                                                                   "detalle": f"{etiqueta}: espera «{f['bloqueo_motivo'] or 'algo'}» y vence el {f['limite']}. El plazo legal no se detiene."}
    for t in traspasos:
        if t["limite"] is None or (date.fromisoformat(t["limite"]) - hoy).days > 7:
            continue
        res[f"trasp:{t['id']}"] = {"tipo": "traspaso_pendiente", "severidad": "urgente", "objeto_tipo": "traspaso", "objeto_id": t["id"], "cliente_fiscal_id": t["cliente_fiscal_id"], "url": "/fiscal/traspasos",
                                   "oficina_id": t["oficina_id"], "destinatario": t["a_usuario_id"], "dias": (date.fromisoformat(t["limite"]) - hoy).days, "titulo": "Traspaso sin aceptar y con plazo cerca",
                                   "detalle": f"{t['cliente']}: hay una obligación el {t['limite']} y el traspaso sigue sin aceptarse. Hasta entonces lo lleva quien lo llevaba."}
    res.update(_candidatas_certificados(tenant_id, dias_certificados or [30, 15, 7, 1]))
    res.update(_candidatas_expedientes(tenant_id, hoy))
    return res


def _candidatas_expedientes(tenant_id: int, hoy: date) -> dict[str, dict]:
    """Expedientes de control abiertos con la fecha objetivo pasada. Esperar al cliente o a un tercero no pausa nada: siguen contando. Se cierran al resolver o cerrar el expediente."""
    from . import control_expedientes
    res: dict[str, dict] = {}
    for x in control_expedientes.vencidos_abiertos(tenant_id, hoy):
        dias = (hoy - date.fromisoformat(x["fecha_objetivo"])).days
        res[f"exp:{x['id']}:{x['fecha_objetivo']}:vencido"] = {
            "tipo": "expediente_vencido", "severidad": "urgente" if x["prioridad"] in ("alta", "urgente") else "atencion", "objeto_tipo": "expediente", "objeto_id": x["id"],
            "cliente_fiscal_id": x["cliente_fiscal_id"], "url": f"/expedientes/{x['id']}", "oficina_id": x["oficina_id"], "destinatario": x["responsable_id"], "dias": -dias,
            "titulo": "Expediente con la fecha objetivo pasada", "detalle": f"{x['titulo']}: la fecha objetivo era el {x['fecha_objetivo']} (hace {dias} días) y sigue abierto."}
    return res


def _candidatas_certificados(tenant_id: int, dias_certificados: list[int]) -> dict[str, dict]:
    """Certificados que caducan dentro del primer plazo (o ya caducados) y siguen en uso. Se cierran solos si se sustituyen, se archivan o su renovación ya está implantada."""
    from . import certificados
    res: dict[str, dict] = {}
    ahora = certificados._ahora()
    zona = certificados._zona_del_despacho(tenant_id)
    maximo = max(dias_certificados)
    conn = db.get_connection()
    try:
        for f in conn.execute("SELECT * FROM certificados WHERE tenant_id = ? AND estado_operativo IN ('inventariado', 'autorizado', 'suspendido') AND not_after IS NOT NULL", (tenant_id,)).fetchall():
            c = certificados._enriquecer(conn, f, ahora, zona)
            dias = c["dias_restantes"]
            if dias is None or dias > maximo or c["renovacion"] in ("implantado", "cerrado"):
                continue
            cli = conn.execute("SELECT responsable_id, oficina_id FROM clientes_fiscales WHERE id = ? AND papelera_en IS NULL", (c["cliente_titular_id"],)).fetchone() if c.get("cliente_titular_id") else None
            nombre = c["nombre_comun"] or c["sujeto"] or f"#{c['id']}"
            caducado = c["temporal"] == "caducado" or dias < 0
            servicios = "Sin servicios registrados: cobertura desconocida." if not c["vinculos_activos"] else f"Da servicio a {c['vinculos_activos']} cliente(s) o servicio(s)."
            renov = "" if c["renovacion"] == "sin_iniciar" else f" Renovación: {c['renovacion'].replace('_', ' ')}."
            res[f"cert:{c['id']}:{c['not_after'][:10]}:caducidad"] = {
                "tipo": "certificado_caducidad", "severidad": "urgente" if caducado or dias <= 7 else "atencion", "umbral": -1 if caducado else min(d for d in dias_certificados if dias <= d),
                "objeto_tipo": "certificado", "objeto_id": c["id"], "cliente_fiscal_id": c.get("cliente_titular_id") if cli else None, "url": f"/certificados/{c['id']}", "oficina_id": cli["oficina_id"] if cli else None,
                "destinatario": c["custodio_id"] or (cli["responsable_id"] if cli else None), "dias": dias,
                "titulo": "Certificado caducado" if caducado else "Certificado a punto de caducar",
                "detalle": (f"{nombre} caducó el {c['not_after'][:10]}. Los servicios que lo usan dejan de funcionar hasta que se sustituya. " if caducado else f"{nombre} caduca {'hoy' if dias == 0 else 'mañana' if dias == 1 else f'en {dias} días'} ({c['not_after'][:10]}). ") + servicios + renov}
    finally:
        conn.close()
    return res


def _enviar(usuario_id: int, titulo: str, cuerpo: str, url: str | None, alerta_id: int) -> bool:
    try:
        from . import notificaciones
        notificaciones.crear_y_enviar(usuario_id, "aviso_fiscal", titulo, cuerpo, url=url or "/fiscal/avisos", datos={"tipo": "aviso_fiscal", "alerta_id": alerta_id})
        return True
    except Exception:  # noqa: BLE001
        return False


def evaluar(tenant_id: int, ahora: datetime | None = None) -> dict:
    """Una pasada completa para un despacho: abre las alertas que faltan, cierra las que ya no aplican, entrega y escala. Idempotente."""
    ahora = ahora or datetime.now()
    hoy = ahora.date()
    cfg = config(tenant_id)
    stats = {"abiertas": 0, "resueltas": 0, "enviadas": 0, "escaladas": 0, "fallos": 0}
    cand = _candidatas(tenant_id, hoy, cfg["dias_antes"] or [7], cfg["dias_certificados"])
    ahora_s = ahora.isoformat(timespec="seconds")
    conn = db.get_connection()
    pendientes_envio: list[tuple] = []
    try:
        existentes = {f["clave"]: f for f in conn.execute("SELECT * FROM alertas WHERE tenant_id = ?", (tenant_id,))}
        # 1) abrir o actualizar
        for clave, c in cand.items():
            f = existentes.get(clave)
            dest = c["destinatario"] or (_coordinadores(tenant_id, c["oficina_id"]) or _directivos(tenant_id) or [None])[0]
            if f is None:
                cur = conn.execute("INSERT INTO alertas (tenant_id, clave, tipo, severidad, objeto_tipo, objeto_id, cliente_fiscal_id, titulo, detalle, url, destinatario_id, umbral, creado_en) "
                                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (tenant_id, clave, c["tipo"], c["severidad"], c["objeto_tipo"], c["objeto_id"], c["cliente_fiscal_id"], c["titulo"], c["detalle"], c["url"], dest, c.get("umbral"), ahora_s))
                stats["abiertas"] += 1
                f = conn.execute("SELECT * FROM alertas WHERE id = ?", (cur.lastrowid,)).fetchone()
                pendientes_envio.append((f["id"], "nuevo"))
            else:
                if f["estado"] == "resuelta":       # el objeto volvió a estar activo: se reabre desde cero
                    conn.execute("UPDATE alertas SET estado = 'abierta', nivel = 0, envios = 0, ultimo_envio_en = NULL, escalada_en = NULL, acusada_por = NULL, acusada_en = NULL, nota_acuse = NULL, "
                                 "resuelta_en = NULL, motivo_resolucion = NULL, creado_en = ?, destinatario_id = ? WHERE id = ?", (ahora_s, dest, f["id"]))
                    pendientes_envio.append((f["id"], "nuevo"))
                    stats["abiertas"] += 1
                if f["estado"] != "acusada" or c["severidad"] != f["severidad"]:
                    conn.execute("UPDATE alertas SET titulo = ?, detalle = ?, severidad = ? WHERE id = ?", (c["titulo"], c["detalle"], c["severidad"], f["id"]))
                if f["estado"] == "abierta" and c.get("umbral") is not None and f["umbral"] != c["umbral"] and f["envios"] > 0:
                    conn.execute("UPDATE alertas SET umbral = ? WHERE id = ?", (c["umbral"], f["id"]))
                    pendientes_envio.append((f["id"], "umbral"))
        # 2) cerrar las que ya no aplican
        for clave, f in existentes.items():
            if f["estado"] != "resuelta" and clave not in cand and f["tipo"] in TIPOS:
                conn.execute("UPDATE alertas SET estado = 'resuelta', resuelta_en = ?, motivo_resolucion = ? WHERE id = ?", (ahora_s, {"obligacion": "La obligación ya no está pendiente de trabajo.", "certificado": "El certificado se ha renovado o ya no está en uso.", "expediente": "El expediente se ha resuelto o cerrado."}.get(f["objeto_tipo"], "El traspaso ya se ha resuelto."), f["id"]))
                stats["resueltas"] += 1
        # 3) repetir las urgentes sin acuse y escalar
        for f in conn.execute("SELECT * FROM alertas WHERE tenant_id = ? AND estado = 'abierta'", (tenant_id,)).fetchall():
            if any(p[0] == f["id"] for p in pendientes_envio):
                continue
            ultimo = datetime.fromisoformat(f["ultimo_envio_en"] or f["creado_en"])
            if f["severidad"] == "urgente" and f["envios"] - 1 < cfg["max_reenvios"] and ahora - ultimo >= timedelta(hours=cfg["reenviar_horas"]) and f["envios"] > 0:
                pendientes_envio.append((f["id"], "repeticion"))
            horas = cfg["escalar_horas_urgente"] if f["severidad"] == "urgente" else cfg["escalar_horas_atencion"]
            base = datetime.fromisoformat(f["escalada_en"] or f["creado_en"])
            if f["nivel"] < 2 and ahora - base >= timedelta(hours=horas):
                pendientes_envio.append((f["id"], "escalado"))
        conn.commit()
    finally:
        conn.close()
    for alerta_id, motivo in pendientes_envio:
        _entregar(tenant_id, alerta_id, motivo, ahora, stats)
    return stats


def _entregar(tenant_id: int, alerta_id: int, motivo: str, ahora: datetime, stats: dict) -> None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT a.*, c.oficina_id FROM alertas a LEFT JOIN clientes_fiscales c ON c.id = a.cliente_fiscal_id WHERE a.id = ?", (alerta_id,)).fetchone()
        if f is None or f["estado"] != "abierta":
            return
        nivel = f["nivel"]
        if motivo == "escalado":
            coord = [u for u in _coordinadores(tenant_id, f["oficina_id"]) if u != f["destinatario_id"]]
            if nivel == 0 and coord:
                nivel, destinatarios = 1, coord
            else:
                nivel, destinatarios = 2, [u for u in _directivos(tenant_id) if u != f["destinatario_id"]] or _directivos(tenant_id)
            titulo, cuerpo = "Sin atender: " + f["titulo"], f"{f['detalle']} Nadie lo ha acusado todavía."
        else:
            destinatarios = [f["destinatario_id"]] if f["destinatario_id"] else _directivos(tenant_id)
            titulo, cuerpo = f["titulo"], f["detalle"] or ""
        ok = [_enviar(u, titulo, cuerpo, f["url"], alerta_id) for u in destinatarios if u]
        ahora_s = ahora.isoformat(timespec="seconds")
        conn.execute("UPDATE alertas SET nivel = ?, envios = envios + 1, ultimo_envio_en = ?, escalada_en = CASE WHEN ? = 'escalado' THEN ? ELSE escalada_en END, fallos = fallos + ?, "
                     "umbral = COALESCE(umbral, NULL) WHERE id = ?", (nivel, ahora_s, motivo, ahora_s, sum(1 for x in ok if not x), alerta_id))
        if motivo == "escalado":
            auditoria.registrar(tenant_id, None, "aviso.escalar", "alerta", alerta_id, {"nivel": nivel, "a": destinatarios}, conn=conn)
            stats["escaladas"] += 1
        conn.commit()
        stats["enviadas"] += len(ok)
        stats["fallos"] += sum(1 for x in ok if not x)
    finally:
        conn.close()


# --- Acuse y consulta --------------------------------------------------------------------------------------------------------------------------
def _puede_ver(tenant_id: int, usuario_id: int, f, visibles) -> bool:
    """Los avisos de certificados los ven quienes gestionan certificados (custodios y supervisores) y su destinatario; el resto, los de los clientes que ve."""
    if f["destinatario_id"] == usuario_id:
        return True
    if f["objeto_tipo"] == "certificado":
        from . import certificados
        return certificados.puede_gestionar(usuario_id, tenant_id)
    return visibles is None or f["cliente_fiscal_id"] is None or f["cliente_fiscal_id"] in visibles


def _puede_acusar_certificado(tenant_id: int, usuario_id: int, f) -> bool:
    if f["objeto_tipo"] != "certificado":
        return False
    from . import certificados
    return certificados.puede_gestionar(usuario_id, tenant_id)


def acusar(tenant_id: int, usuario_id: int, alerta_id: int, nota: str | None = None) -> None:
    """«Lo he visto, lo llevo»: la alerta deja de repetirse y de escalar, pero **no cierra ni presenta la obligación**."""
    nota = (nota or "").strip()[:500]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM alertas WHERE id = ? AND tenant_id = ?", (alerta_id, tenant_id)).fetchone()
        u = db.obtener_usuario(usuario_id)
        if f is None or u is None or u["tenant_id"] != tenant_id or not (acceso.es_directivo(usuario_id) or f["destinatario_id"] == usuario_id or _puede_acusar_certificado(tenant_id, usuario_id, f) or (f["objeto_tipo"] != "certificado" and f["cliente_fiscal_id"] and acceso.puede_modificar_cliente(tenant_id, usuario_id, f["cliente_fiscal_id"]))):
            raise ValueError("No existe ese aviso.")
        if f["estado"] == "resuelta":
            raise ValueError("Este aviso ya está resuelto: no hace falta acusarlo.")
        if f["estado"] == "acusada":
            raise ValueError("Este aviso ya está acusado.")
        conn.execute("UPDATE alertas SET estado = 'acusada', acusada_por = ?, acusada_en = ?, nota_acuse = ? WHERE id = ?", (usuario_id, db.now_iso(), nota or None, alerta_id))
        auditoria.registrar(tenant_id, usuario_id, "aviso.acusar", "alerta", alerta_id, {"objeto": f["objeto_tipo"], "objeto_id": f["objeto_id"], "nota": nota or None}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def publico(a: dict) -> dict:
    """Lo que sale por la API y la IA: sin la clave interna de deduplicación."""
    return {k: v for k, v in a.items() if k not in ("clave", "umbral", "tenant_id")}


def _enriquecer(f) -> dict:
    a = dict(f)
    a["destinatario"] = traspasos._nombre(a["destinatario_id"])
    a["acusada_por_nombre"] = traspasos._nombre(a["acusada_por"])
    cli = db.obtener_cliente_fiscal(a["tenant_id"], a["cliente_fiscal_id"]) if a["cliente_fiscal_id"] else None
    a["cliente"] = cli["nombre"] if cli else None
    a["horas_abierta"] = int((datetime.now() - datetime.fromisoformat(a["creado_en"])).total_seconds() // 3600) if a["estado"] == "abierta" else None
    return a


def listar(tenant_id: int, usuario_id: int, *, estado: str | None = "abierta", mios: bool = False, limite: int = 200) -> list[dict]:
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    cond, p = ["tenant_id = ?"], [tenant_id]
    if estado:
        cond.append("estado = ?"); p.append(estado)
    if mios:
        cond.append("destinatario_id = ?"); p.append(usuario_id)
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT * FROM alertas WHERE {' AND '.join(cond)} ORDER BY (severidad = 'urgente') DESC, creado_en LIMIT ?", [*p, limite]).fetchall()
    finally:
        conn.close()
    return [_enriquecer(f) for f in filas if _puede_ver(tenant_id, usuario_id, f, visibles)]


def obtener(tenant_id: int, alerta_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM alertas WHERE id = ? AND tenant_id = ?", (alerta_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _enriquecer(f) if f else None


def metricas(tenant_id: int, dias: int = 30) -> dict:
    """Lo que dice la especificación que hay que medir de los avisos: tiempo hasta el acuse, trabajo sin atender, escaladas, fallos de entrega y duplicados."""
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        def n(sql, *p): return conn.execute(sql, (tenant_id, *p)).fetchone()[0]
        tiempos = sorted((datetime.fromisoformat(f["acusada_en"][:19]) - datetime.fromisoformat(f["creado_en"])).total_seconds() / 3600
                         for f in conn.execute("SELECT creado_en, acusada_en FROM alertas WHERE tenant_id = ? AND acusada_en IS NOT NULL AND creado_en >= ?", (tenant_id, desde)))
        sin_acusar_24 = n("SELECT COUNT(*) FROM alertas WHERE tenant_id = ? AND estado = 'abierta' AND creado_en <= ?", (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds"))
        return {"dias": dias, "creadas": n("SELECT COUNT(*) FROM alertas WHERE tenant_id = ? AND creado_en >= ?", desde), "abiertas": n("SELECT COUNT(*) FROM alertas WHERE tenant_id = ? AND estado = 'abierta'"),
                "acusadas": n("SELECT COUNT(*) FROM alertas WHERE tenant_id = ? AND estado = 'acusada'"), "resueltas": n("SELECT COUNT(*) FROM alertas WHERE tenant_id = ? AND estado = 'resuelta' AND resuelta_en >= ?", desde),
                "sin_acusar_mas_de_24h": sin_acusar_24, "escaladas": n("SELECT COUNT(*) FROM alertas WHERE tenant_id = ? AND nivel > 0 AND estado != 'resuelta'"),
                "fallos_de_entrega": n("SELECT COALESCE(SUM(fallos), 0) FROM alertas WHERE tenant_id = ?"),
                "duplicados": n("SELECT COUNT(*) FROM (SELECT 1 FROM alertas WHERE tenant_id = ? AND estado != 'resuelta' GROUP BY objeto_tipo, objeto_id, tipo HAVING COUNT(*) > 1)"),
                "horas_hasta_acuse_mediana": round(tiempos[len(tiempos) // 2], 1) if tiempos else None, "muestra_acuses": len(tiempos)}
    finally:
        conn.close()


# --- Hilo --------------------------------------------------------------------------------------------------------------------------------------
def evaluar_todos(ahora: datetime | None = None) -> dict:
    total = {"abiertas": 0, "resueltas": 0, "enviadas": 0, "escaladas": 0, "fallos": 0, "despachos": 0}
    conn = db.get_connection()
    try:
        tenants = [f[0] for f in conn.execute("SELECT tenant_id FROM avisos_config WHERE activo = 1")]
    finally:
        conn.close()
    for t in tenants:
        for k, v in evaluar(t, ahora).items():
            total[k] += v
        total["despachos"] += 1
    return total


def bucle() -> None:
    import time
    from . import salud
    salud.registrar_ok("avisos_fiscales", INTERVALO_SEGUNDOS * 2, "arrancado")
    time.sleep(150)
    while True:
        try:
            r = evaluar_todos()
            salud.registrar_ok("avisos_fiscales", INTERVALO_SEGUNDOS * 2, f"{r['despachos']} despachos, {r['abiertas']} avisos nuevos, {r['escaladas']} escalados")
            if r["fallos"]:
                salud.registrar_error("avisos_fiscales", INTERVALO_SEGUNDOS * 2, f"{r['fallos']} entregas fallidas")
        except Exception as e:  # noqa: BLE001
            salud.registrar_error("avisos_fiscales", INTERVALO_SEGUNDOS * 2, f"{type(e).__name__}: {e}")
        time.sleep(INTERVALO_SEGUNDOS)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM alertas WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM avisos_config WHERE tenant_id = ?", (tenant_id,))
