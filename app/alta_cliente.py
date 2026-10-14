"""Alta única de cliente: un solo camino para crear a un cliente de la gestoría, sea desde el núcleo (/clientes/nuevo), desde el alta rápida de
Fiscal, la API o las herramientas MCP/IA.

Un cliente tiene siempre su ficha del núcleo (`clientes`) y, si el despacho lleva su gestión fiscal, una ficha fiscal enlazada
(`clientes_fiscales.cliente_id`, ver app/nucleo.py). Aquí se decide cuál de las dos (o las dos) se crea y se aplican a la vez el perfil fiscal, los
modelos y el paso opcional de EspoCRM, que antes estaba repetido en cada punto de entrada.

El perfil fiscal solo propone modelos (ver app/perfil_fiscal.py): nada de lo que se guarda aquí inventa reglas fiscales."""
from __future__ import annotations

import json
from typing import Iterable

from . import db, espocrm, nucleo, perfil_fiscal, verticales
from .vencimientos_fiscales import MODELOS_POR_PAIS

PAISES = tuple(MODELOS_POR_PAIS)


def gestion_fiscal_disponible(tenant_id: int) -> bool:
    """El despacho tiene activo el módulo de Gestoría (el que da las pantallas fiscales)."""
    return verticales.esta_activo(tenant_id, "gestoria")


def vincular_espocrm(tenant_id: int, cliente_fiscal_id: int, nombre: str) -> None:
    """Enlaza (o crea) la cuenta de EspoCRM del cliente. Opcional y best-effort: sin EspoCRM configurado no hace nada y un fallo nunca rompe el alta."""
    try:
        cuenta_id = espocrm.buscar_cuenta_por_nombre(nombre)
        if cuenta_id is None:
            cuenta = espocrm.crear_cuenta(nombre)
            cuenta_id = cuenta["id"] if cuenta else None
        if cuenta_id:
            db.editar_cliente_fiscal(tenant_id, cliente_fiscal_id, espocrm_cuenta_id=cuenta_id)
    except espocrm.ErrorEspoCRM:
        pass


def _perfil_y_modelos(pais: str, perfil_tipo: str | None, perfil_atributos: Iterable[str], modelos: list[str] | None, generacion_automatica: bool) -> dict:
    """Campos de `clientes_fiscales` que salen del formulario de alta. Con perfil elegido, los modelos son los que propone el perfil."""
    pais = (pais or "ES").strip().upper()
    perfil_atributos = list(perfil_atributos)
    campos: dict = {"pais": pais}
    perfil = perfil_fiscal.perfil_limpio(perfil_tipo, perfil_atributos) if (perfil_tipo or perfil_atributos) else None
    if perfil is not None:
        campos["perfil_fiscal"] = json.dumps(perfil)
        modelos = [m["modelo"] for m in perfil_fiscal.modelos_para_perfil(perfil)] or modelos
    if modelos:
        campos["modelos_fiscales"] = db.serializar_modelos_fiscales(modelos)
    # Un país sin calendario no tiene modelos que generar: la generación automática solo tiene sentido donde hay reglas.
    campos["generacion_automatica"] = 1 if (generacion_automatica and pais in PAISES and modelos) else 0
    return campos


def _descartar(tenant_id: int, cliente_id: int) -> None:
    """Deshace un cliente del núcleo recién creado cuando falla lo que venía después, para no dejar una ficha huérfana que obligue a repetir el alta."""
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM cliente_etiquetas WHERE cliente_id = ?", (cliente_id,))
        conn.execute("DELETE FROM clientes WHERE id = ? AND tenant_id = ?", (cliente_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def _crear_ficha_fiscal(tenant_id: int, cliente_id: int, nombre: str, *, nif, email, notas, idioma, pais, perfil_tipo, perfil_atributos, modelos,
                        generacion_automatica, vincular_crm: bool) -> int:
    fiscal_id = db.crear_cliente_fiscal(tenant_id, nombre, nif=nif, notas=notas, email=email, cliente_id=cliente_id, pais=pais or "ES")
    campos = _perfil_y_modelos(pais, perfil_tipo, perfil_atributos, modelos, generacion_automatica)
    if idioma:
        campos["idioma"] = idioma
    db.editar_cliente_fiscal(tenant_id, fiscal_id, **campos)
    if vincular_crm:
        vincular_espocrm(tenant_id, fiscal_id, nombre)
    return fiscal_id


def crear_cliente_completo(
    tenant_id: int, nombre: str, *, gestion_fiscal: bool = False, tipo: str | None = None, nif: str | None = None, email: str | None = None,
    telefono: str | None = None, direccion: str | None = None, idioma: str | None = None, origen: str | None = None, notas: str | None = None,
    responsable_id: int | None = None, etiquetas: list[str] | None = None, pais: str = "ES", perfil_tipo: str | None = None,
    perfil_atributos: Iterable[str] = (), modelos: list[str] | None = None, generacion_automatica: bool = False, vincular_crm: bool = True,
) -> dict:
    """Crea al cliente y, con `gestion_fiscal`, su ficha fiscal enlazada. Devuelve `{cliente_id, cliente_fiscal_id}` (`None` si no lleva gestión fiscal).
    Los errores de validación del núcleo salen como `ValueError`, igual que `nucleo.crear_cliente`."""
    cliente_id = nucleo.crear_cliente(
        tenant_id, nombre, tipo=tipo, nif=nif, email=email, telefono=telefono, direccion=direccion, idioma=idioma, origen=origen, notas=notas,
        responsable_id=responsable_id, etiquetas=etiquetas,
    )
    if not gestion_fiscal:
        return {"cliente_id": cliente_id, "cliente_fiscal_id": None}
    try:
        fiscal_id = _crear_ficha_fiscal(
            tenant_id, cliente_id, nombre.strip(), nif=nif, email=email, notas=notas, idioma=idioma, pais=pais, perfil_tipo=perfil_tipo,
            perfil_atributos=perfil_atributos, modelos=modelos, generacion_automatica=generacion_automatica, vincular_crm=vincular_crm,
        )
    except Exception:
        _descartar(tenant_id, cliente_id)
        raise
    return {"cliente_id": cliente_id, "cliente_fiscal_id": fiscal_id}


def activar_gestion_fiscal(
    tenant_id: int, cliente_id: int, *, pais: str = "ES", perfil_tipo: str | None = None, perfil_atributos: Iterable[str] = (),
    modelos: list[str] | None = None, generacion_automatica: bool = False, vincular_crm: bool = True,
) -> int:
    """Da de alta la ficha fiscal de un cliente que solo existía en el núcleo, copiando sus datos. Devuelve el id de `clientes_fiscales`."""
    c = nucleo.obtener_cliente(tenant_id, cliente_id)
    if c is None:
        raise ValueError("Cliente no encontrado.")
    if c["cliente_fiscal_id"]:
        raise ValueError("Este cliente ya tiene gestión fiscal.")
    return _crear_ficha_fiscal(
        tenant_id, cliente_id, c["nombre"], nif=c["nif"], email=c["email"], notas=c["notas"], idioma=c["idioma"], pais=pais, perfil_tipo=perfil_tipo,
        perfil_atributos=perfil_atributos, modelos=modelos, generacion_automatica=generacion_automatica, vincular_crm=vincular_crm,
    )
