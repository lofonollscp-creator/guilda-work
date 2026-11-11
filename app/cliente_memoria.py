"""Memoria del cliente (W11): un resumen corto y vivo de lo que conviene recordar de cada cliente («prefiere WhatsApp, cambió de domicilio en marzo, paga siempre tarde»).

Lo que vale es el `texto`, que escribe o confirma una **persona**. La IA solo deja un `borrador` (propuesta de actualización a partir de lo que el cliente ha escrito en el portal y del texto actual) que la persona
acepta, edita o descarta: la IA nunca cambia la memoria sola. El texto entra en el contexto del copiloto de la ficha y del asistente. La consulta a la IA pasa por la misma protección de datos personales que
todas (app/anonimizar.py)."""
from __future__ import annotations

from datetime import datetime

from . import auditoria, db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cliente_memoria (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    texto TEXT NOT NULL DEFAULT '',
    borrador TEXT NOT NULL DEFAULT '',
    borrador_en TEXT,
    actualizado_por INTEGER,
    actualizado_en TEXT,
    PRIMARY KEY (tenant_id, cliente_fiscal_id)
);
"""
MAX_TEXTO = 1200
MAX_MENSAJES_CONTEXTO = 20
SISTEMA = ("Eres el asistente de una gestoría. Te paso lo que un cliente ha escrito en su portal y lo que ya sabemos de él. Devuelve la memoria actualizada del cliente: como mucho 6 viñetas cortas con lo que "
           "conviene recordar para tratarlo bien (cómo prefiere que le contacten, cambios importantes, particularidades de su actividad, hábitos de pago o de entrega de documentos). Conserva lo que ya sabemos si "
           "sigue siendo válido, añade solo lo que se desprenda de los mensajes y no inventes nada. Devuelve solo las viñetas, una por línea, empezando por «- ». Los datos personales aparecen como etiquetas "
           "entre corchetes: déjalas tal cual.")


class ErrorMemoria(ValueError):
    """Mensaje apto para enseñarlo."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _limpio(texto: str | None) -> str:
    lineas = [" ".join(l.split()) for l in (texto or "").splitlines()]
    return "\n".join(l for l in lineas if l)[:MAX_TEXTO]


def obtener(tenant_id: int, cliente_fiscal_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT texto, borrador, borrador_en, actualizado_por, actualizado_en FROM cliente_memoria WHERE tenant_id = ? AND cliente_fiscal_id = ?", (tenant_id, cliente_fiscal_id)).fetchone()
    finally:
        conn.close()
    return dict(f) if f else {"texto": "", "borrador": "", "borrador_en": None, "actualizado_por": None, "actualizado_en": None}


def _guardar(tenant_id: int, cliente_fiscal_id: int, **campos) -> None:
    conn = db.get_connection()
    try:
        existe = conn.execute("SELECT 1 FROM cliente_memoria WHERE tenant_id = ? AND cliente_fiscal_id = ?", (tenant_id, cliente_fiscal_id)).fetchone()
        if not existe:
            conn.execute("INSERT INTO cliente_memoria (tenant_id, cliente_fiscal_id) VALUES (?, ?)", (tenant_id, cliente_fiscal_id))
        conn.execute("UPDATE cliente_memoria SET " + ", ".join(f"{k} = ?" for k in campos) + " WHERE tenant_id = ? AND cliente_fiscal_id = ?", (*campos.values(), tenant_id, cliente_fiscal_id))
        conn.commit()
    finally:
        conn.close()


def _cliente(tenant_id: int, cliente_fiscal_id: int) -> dict:
    c = db.obtener_cliente_fiscal(tenant_id, cliente_fiscal_id)
    if c is None:
        raise ErrorMemoria("Ese cliente no existe.")
    return c


def guardar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, texto: str) -> None:
    """Lo escrito por una persona pasa a ser la memoria (y el borrador pendiente, si lo había, se descarta: ya no corresponde)."""
    _cliente(tenant_id, cliente_fiscal_id)
    _guardar(tenant_id, cliente_fiscal_id, texto=_limpio(texto), borrador="", borrador_en=None, actualizado_por=usuario_id, actualizado_en=_ahora())
    auditoria.registrar(tenant_id, usuario_id, "cliente.memoria_guardada", "cliente_fiscal", cliente_fiscal_id, {})


def contexto_para_ia(tenant_id: int, cliente_fiscal_id: int) -> str:
    """Los mensajes recientes del cliente en el portal, más el texto actual, como contexto de la propuesta."""
    from . import portal_conversaciones
    cliente = _cliente(tenant_id, cliente_fiscal_id)
    partes = []
    mensajes = []
    for h in portal_conversaciones.listar(cliente)[:10]:
        hilo = portal_conversaciones.obtener(cliente, h["id"]) or {}
        for m in hilo.get("mensajes", []):
            if m["de"] == "cliente":
                mensajes.append((m["creado_en"], hilo.get("asunto") or "", m["texto"]))
    for fecha, asunto, texto in sorted(mensajes)[-MAX_MENSAJES_CONTEXTO:]:
        partes.append(f"[{fecha[:10]}] {asunto}: {texto[:400]}")
    actual = obtener(tenant_id, cliente_fiscal_id)["texto"]
    return (f"Lo que ya sabemos del cliente:\n{actual or '(nada todavía)'}\n\nMensajes recientes del cliente:\n" + ("\n".join(partes) or "(ninguno)"))


def proponer_con_ia(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> str:
    """Pide a la IA una actualización y la deja como borrador. Devuelve el borrador. `ia_asistente.ErrorIA` si no hay modelo o falla el proveedor."""
    from . import ia_asistente
    contexto = contexto_para_ia(tenant_id, cliente_fiscal_id)
    texto = _limpio(ia_asistente.completar_texto(usuario_id, SISTEMA, contexto))
    if not texto:
        raise ErrorMemoria("La IA no ha propuesto nada.")
    _guardar(tenant_id, cliente_fiscal_id, borrador=texto, borrador_en=_ahora())
    auditoria.registrar(tenant_id, usuario_id, "cliente.memoria_propuesta", "cliente_fiscal", cliente_fiscal_id, {})
    return texto


def aceptar_borrador(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> None:
    b = obtener(tenant_id, cliente_fiscal_id)["borrador"]
    if not b:
        raise ErrorMemoria("No hay ninguna propuesta que aceptar.")
    guardar(tenant_id, usuario_id, cliente_fiscal_id, b)


def descartar_borrador(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> None:
    _guardar(tenant_id, cliente_fiscal_id, borrador="", borrador_en=None)
