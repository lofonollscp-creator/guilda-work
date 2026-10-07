"""Plantillas de proyecto: tres de serie para un despacho (con sus textos traducibles) y las que el
despacho guarda desde un proyecto. Una plantilla es secciones con tareas; `dias` es «días desde hoy»."""
from flask_babel import lazy_gettext as _l

from . import db

DE_SERIE = {
    "s:cierre-trimestral": {
        "nombre": _l("Cierre trimestral"),
        "descripcion": _l("Recoger documentación, contabilizar y presentar los modelos del trimestre."),
        "estructura": [
            {"nombre": _l("Recoger documentación"), "tareas": [
                {"asunto": _l("Pedir extractos bancarios"), "dias": 2},
                {"asunto": _l("Pedir facturas emitidas y recibidas"), "dias": 3},
            ]},
            {"nombre": _l("Contabilizar"), "tareas": [
                {"asunto": _l("Contabilizar facturas y bancos"), "dias": 8},
                {"asunto": _l("Cuadrar IVA soportado y repercutido"), "dias": 10},
            ]},
            {"nombre": _l("Presentar"), "tareas": [
                {"asunto": _l("Preparar los modelos del trimestre"), "dias": 14},
                {"asunto": _l("Revisar con el cliente y presentar"), "dias": 17},
            ]},
            {"nombre": _l("Cerrar"), "tareas": [{"asunto": _l("Enviar justificantes al cliente"), "dias": 18}]},
        ],
    },
    "s:alta-cliente": {
        "nombre": _l("Alta de cliente nuevo"),
        "descripcion": _l("Datos, autorizaciones y primeros pasos con un cliente que empieza."),
        "estructura": [
            {"nombre": _l("Datos y documentos"), "tareas": [
                {"asunto": _l("Pedir DNI/CIF y escrituras"), "dias": 2},
                {"asunto": _l("Firmar la hoja de encargo"), "dias": 5},
            ]},
            {"nombre": _l("Accesos y autorizaciones"), "tareas": [
                {"asunto": _l("Tramitar apoderamiento en la Agencia Tributaria"), "dias": 7},
                {"asunto": _l("Solicitar acceso a la banca online"), "dias": 7},
            ]},
            {"nombre": _l("Puesta en marcha"), "tareas": [{"asunto": _l("Crear el cliente y su calendario fiscal"), "dias": 10}]},
        ],
    },
    "s:renta": {
        "nombre": _l("Declaración de la renta"),
        "descripcion": _l("Campaña de renta de un cliente, de los datos al envío."),
        "estructura": [
            {"nombre": _l("Datos"), "tareas": [
                {"asunto": _l("Pedir datos fiscales y certificados"), "dias": 3},
                {"asunto": _l("Pedir justificantes de deducciones"), "dias": 5},
            ]},
            {"nombre": _l("Borrador"), "tareas": [{"asunto": _l("Preparar el borrador"), "dias": 10}]},
            {"nombre": _l("Presentación"), "tareas": [
                {"asunto": _l("Revisar el borrador con el cliente"), "dias": 14},
                {"asunto": _l("Presentar y enviar el justificante"), "dias": 17},
            ]},
        ],
    },
}


def _texto(valor):
    return str(valor)


def _resolver(estructura) -> list[dict]:
    return [
        {"nombre": _texto(s["nombre"]), "tareas": [{"asunto": _texto(t["asunto"]), "dias": t.get("dias")} for t in s.get("tareas", [])]}
        for s in estructura
    ]


def catalogo(usuario_id: int) -> list[dict]:
    """De serie primero y luego las del despacho. Cada una: clave, nombre, descripcion, estructura, propia (borrable)."""
    resultado = [
        {"clave": k, "nombre": _texto(v["nombre"]), "descripcion": _texto(v["descripcion"]), "estructura": _resolver(v["estructura"]), "propia": False}
        for k, v in DE_SERIE.items()
    ]
    for p in db.listar_plantillas_proyecto(usuario_id):
        resultado.append({"clave": f"u:{p['id']}", "nombre": p["nombre"], "descripcion": "", "estructura": p["estructura"], "propia": True, "id": p["id"]})
    return resultado


def estructura_de(usuario_id: int, clave: str):
    for p in catalogo(usuario_id):
        if p["clave"] == clave:
            return p["estructura"]
    return None
