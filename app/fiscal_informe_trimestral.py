"""Informe trimestral en PDF para el cliente: qué facturas han computado, el IVA y las retenciones del periodo, cómo va el 303 y qué falta por su parte. Es informativo: no presenta nada ni sustituye
a los modelos de la AEAT (se dice en el propio documento). Todo el contenido sale de `fiscal_nucleo.informe_trimestral`; aquí solo se maqueta."""
from __future__ import annotations

from flask_babel import gettext as _

from . import informes
from .fiscal_resumen_pdf import _eur, frase_resultado


def generar(datos: dict, *, titular: str, nif: str | None, gestoria: str, estados: dict[str, str]) -> bytes:
    t = datos["totales"]
    ejercicio, periodo = datos["ejercicio"], datos["periodo"]
    bloques: list[tuple] = []
    bloques.append(("claves", [(_("Titular"), f"{titular} · {nif or '—'}"), (_("Periodo"), f"{periodo} {ejercicio} ({datos['desde']} → {datos['hasta']})"),
                               (_("Fecha límite del 303"), datos["fecha_limite"] or "—")]))
    bloques.append(("seccion", _("IVA del periodo (modelo 303)")))
    bloques.append(("claves", [(_("IVA repercutido (ventas)"), _eur(t["iva_repercutido"])), (_("IVA soportado (compras)"), _eur(t["iva_soportado"])),
                               (_("Diferencia (a ingresar si es positiva)"), _eur(t["iva_repercutido"] - t["iva_soportado"]))]))
    d = datos["declaracion"]
    if d:
        bloques.append(("parrafo", f"{_('Declaración')}: {estados.get(d['estado'], d['estado'])}. {frase_resultado(d['tipo_declaracion'], d['resultado_centimos'])}"))
    else:
        bloques.append(("parrafo", _("Todavía no hay una declaración calculada para este periodo; las cifras de arriba son las de los apuntes ya aprobados.")))
    if t["retenciones_111"] or t["retenciones_115"] or t["retenciones_soportadas"]:
        bloques.append(("seccion", _("Retenciones de IRPF")))
        filas = []
        if t["retenciones_111"]:
            filas.append((_("Modelo 111 (profesionales y trabajadores)"), _eur(t["retenciones_111"])))
        if t["retenciones_115"]:
            filas.append((_("Modelo 115 (alquileres)"), _eur(t["retenciones_115"])))
        if t["retenciones_soportadas"]:
            filas.append((_("Retenciones que le han practicado a usted"), _eur(t["retenciones_soportadas"])))
        bloques.append(("claves", filas))
    bloques.append(("seccion", _("Lo que falta por su parte")))
    if datos["sin_registrar"] or datos["no_computan"]:
        bloques.append(("parrafo", _("Hay %(n)s facturas del periodo que todavía no cuentan en las cifras. Puede ser que estén pendientes de revisar o de registrar.", n=datos["no_computan"])))
    else:
        bloques.append(("parrafo", _("No hay facturas pendientes: todo lo recibido en el periodo ya cuenta.")))
    if not datos["emitidas"] or not datos["recibidas"]:
        bloques.append(("parrafo", _("Si no tuvo ventas o compras en el periodo, indíquenoslo; si las tuvo, envíenos las facturas que falten.")))
    bloques.append(("seccion", _("Facturas del periodo")))
    etiquetas = {"computa": _("Cuenta"), "por_registrar": _("Por registrar"), "por_revisar": _("Por revisar"), "excluida": _("Excluida")}
    filas = [(f["fecha"], f["numero"] or "—", f["tercero_nombre"] or "—", _("Emitida") if f["tipo"] == "emitida" else _("Recibida"), _eur(f["base"]), _eur(f["cuota_iva"]),
              etiquetas.get(f["m303"], f["m303"])) for f in datos["facturas"]]
    bloques.append(("tabla", [_("Fecha"), _("Número"), _("Tercero"), _("Tipo"), _("Base"), _("IVA"), _("Estado")], filas))
    bloques.append(("espacio",))
    bloques.append(("parrafo", _("Documento informativo, elaborado con los datos de que dispone el despacho en el momento de generarlo. No sustituye a la presentación en la Agencia Tributaria ni a su justificante.")))
    return informes.construir_pdf(_("Informe trimestral %(p)s %(e)s", p=periodo, e=ejercicio), bloques, despacho=gestoria, subtitulo=titular)
