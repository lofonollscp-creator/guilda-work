"""«Pedir algo a tu gestoría»: un catálogo de gestiones que el cliente puede iniciar solo, con el formulario justo para que la gestoría tenga todo a la primera (sin ir y venir preguntando).

Cada gestión es un formulario corto (y, si hace falta, unos adjuntos); al enviarlo se abre una conversación con la gestoría con los datos bien ordenados y el asunto «Solicitud: …», así que el cliente la sigue (abierta o cerrada) en
«Mis solicitudes» y la gestoría la recibe como cualquier otro mensaje. El catálogo es el mismo para todos los despachos; las gestiones que no encajen con un cliente se resuelven en la conversación."""
from __future__ import annotations

import re
from datetime import date

from flask_babel import lazy_gettext as _l

from . import portal_conversaciones

PREFIJO = "Solicitud: "
MAX_TEXTO = 600
MAX_LARGO = 1200


def _campo(id_, tipo, etiqueta, obligatorio=True, opciones=None):
    return {"id": id_, "tipo": tipo, "etiqueta": etiqueta, "obligatorio": obligatorio, "opciones": opciones or []}


CATALOGO: dict[str, dict] = {
    "certificado-corriente": {"titulo": _l("Certificado de estar al corriente de pagos"), "descripcion": _l("Para una subvención, un concurso, un banco o un contrato: de Hacienda o de la Seguridad Social."),
        "icono": "icono-shield-check", "adjuntos": False,
        "campos": [_campo("organismo", "opciones", _l("¿De cuál lo necesitas?"), True, [_l("Hacienda (AEAT)"), _l("Seguridad Social"), _l("Los dos")]), _campo("destino", "texto", _l("¿Para qué o para quién es?")), _campo("fecha", "fecha", _l("¿Para cuándo lo necesitas?"), False)]},
    "copia-modelo": {"titulo": _l("Copia de un modelo presentado"), "descripcion": _l("El justificante o el PDF de un impuesto que ya se presentó."),
        "icono": "icono-download", "adjuntos": False,
        "campos": [_campo("modelo", "texto", _l("¿Qué modelo? (por ejemplo, 303)")), _campo("periodo", "texto", _l("¿De qué periodo? (por ejemplo, 2T 2026)")), _campo("nota", "largo", _l("Algo más que quieras decirnos"), False)]},
    "cambio-datos": {"titulo": _l("Cambiar mis datos"), "descripcion": _l("Domicilio, teléfono, cuenta bancaria o actividad. Tu gestoría lo comprueba y lo actualiza."),
        "icono": "icono-pencil", "adjuntos": True,
        "campos": [_campo("que", "opciones", _l("¿Qué cambia?"), True, [_l("Domicilio"), _l("Teléfono"), _l("Cuenta bancaria (IBAN)"), _l("Actividad"), _l("Otro dato")]), _campo("nuevo", "largo", _l("El dato nuevo"), True), _campo("desde", "fecha", _l("¿Desde cuándo?"), False)]},
    "alta-trabajador": {"titulo": _l("Dar de alta a un trabajador"), "descripcion": _l("Contrato y alta en la Seguridad Social de una persona nueva."),
        "icono": "icono-user", "adjuntos": True,
        "campos": [_campo("nombre", "texto", _l("Nombre y apellidos")), _campo("inicio", "fecha", _l("Fecha de inicio")), _campo("contrato", "opciones", _l("Tipo de contrato"), True, [_l("Indefinido"), _l("Temporal"), _l("Prácticas o formación"), _l("No lo sé")]), _campo("jornada", "texto", _l("Jornada y sueldo acordados"), False)]},
    "baja-trabajador": {"titulo": _l("Dar de baja a un trabajador"), "descripcion": _l("Fin de contrato, dimisión o despido: se prepara el finiquito."),
        "icono": "icono-log-out", "adjuntos": True,
        "campos": [_campo("nombre", "texto", _l("Nombre y apellidos")), _campo("fecha", "fecha", _l("Fecha de la baja")), _campo("motivo", "opciones", _l("Motivo"), True, [_l("Fin de contrato"), _l("Dimisión"), _l("Despido"), _l("Otro")])]},
    "consulta-fiscal": {"titulo": _l("Consultar una operación antes de hacerla"), "descripcion": _l("Comprar un vehículo, contratar a alguien, cambiar de forma jurídica… para saber cómo afecta a tus impuestos."),
        "icono": "icono-message-circle", "adjuntos": True,
        "campos": [_campo("operacion", "texto", _l("¿Qué quieres hacer?")), _campo("detalle", "largo", _l("Cuéntanos los detalles (importes, fechas, a quién)")), _campo("fecha", "fecha", _l("¿Para cuándo lo decides?"), False)]},
    "factura-emitir": {"titulo": _l("Que me preparen una factura"), "descripcion": _l("Si tu gestoría emite tus facturas, dinos los datos y las prepara."),
        "icono": "icono-paperclip", "adjuntos": False,
        "campos": [_campo("cliente", "texto", _l("Nombre y NIF del cliente")), _campo("concepto", "largo", _l("Concepto")), _campo("importe", "texto", _l("Importe (indica si lleva IVA)")), _campo("fecha", "fecha", _l("Fecha de la factura"), False)]},
    "justificante-ingresos": {"titulo": _l("Justificante de ingresos"), "descripcion": _l("Para un banco, un alquiler o una ayuda: un resumen de lo que has ingresado."),
        "icono": "icono-bar-chart-3", "adjuntos": False,
        "campos": [_campo("periodo", "texto", _l("¿De qué periodo? (por ejemplo, el último año)")), _campo("destino", "texto", _l("¿Para quién es?"), False)]},
}


def obtener(clave: str) -> dict | None:
    d = CATALOGO.get(clave)
    return dict(d, clave=clave) if d else None


def validar(clave: str, formulario) -> dict[str, str]:
    """{campo: texto limpio} de lo enviado. `ValueError` con un mensaje legible si falta algo obligatorio o algo no vale."""
    g = obtener(clave)
    if g is None:
        raise ValueError("Esa gestión no existe.")
    datos: dict[str, str] = {}
    for c in g["campos"]:
        v = " ".join(str(formulario.get(c["id"], "")).split()) if c["tipo"] != "largo" else "\n".join(l.strip() for l in str(formulario.get(c["id"], "")).strip().splitlines() if l.strip())
        if not v:
            if c["obligatorio"]:
                raise ValueError("Rellena todos los campos obligatorios.")
            continue
        if c["tipo"] == "opciones" and v not in [str(o) for o in c["opciones"]]:
            raise ValueError("Elige una de las opciones.")
        if c["tipo"] == "fecha":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise ValueError("Escribe la fecha completa.")
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError("Escribe una fecha válida.") from None
        if len(v) > (MAX_LARGO if c["tipo"] == "largo" else MAX_TEXTO):
            raise ValueError("Alguno de los textos es demasiado largo.")
        datos[c["id"]] = v
    return datos


def mensaje(clave: str, datos: dict[str, str]) -> str:
    """El texto de la conversación con cada dato en su línea, en el idioma del cliente."""
    g = obtener(clave)
    lineas = []
    for c in g["campos"]:
        if c["id"] in datos:
            v = datos[c["id"]]
            lineas.append(f"{c['etiqueta']}: {v}" if "\n" not in v else f"{c['etiqueta']}:\n{v}")
    return "\n".join(lineas)


def _titulo_es(clave: str) -> str:
    from flask_babel import force_locale
    with force_locale("es"):
        return str(CATALOGO[clave]["titulo"])


def asunto(clave: str) -> str:
    """El asunto de la conversación, siempre en español: así el equipo ve lo mismo venga el cliente en el idioma que venga y «Mis solicitudes» las reconoce."""
    return PREFIJO + _titulo_es(clave)


def titulo_de(asunto_guardado: str) -> str:
    """El nombre de la gestión en el idioma de quien mira (o el asunto tal cual si ya no está en el catálogo)."""
    for clave in CATALOGO:
        if asunto_guardado == PREFIJO + _titulo_es(clave):
            return str(CATALOGO[clave]["titulo"])
    return asunto_guardado[len(PREFIJO):] if asunto_guardado.startswith(PREFIJO) else asunto_guardado


def mis_solicitudes(cliente) -> list[dict]:
    """Las conversaciones que el cliente abrió desde el catálogo, con su estado (abierta = en curso, cerrada = resuelta)."""
    return [dict(h, titulo=titulo_de(str(h["asunto"]))) for h in portal_conversaciones.listar(cliente) if str(h["asunto"]).startswith(PREFIJO)]
