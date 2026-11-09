"""Glosario del portal: qué es cada modelo fiscal y cada palabra rara, en dos líneas y en lenguaje llano.

Está escrito por el equipo de Guilda Work y vale para cualquier despacho: describe el modelo en general (cuándo se presenta y qué suele hacer falta), nunca la situación concreta de una persona. Los plazos exactos
de cada cliente salen de su calendario. Los textos son ordinarios del catálogo de traducciones (es/ca/en/fr)."""
from __future__ import annotations

import re
import unicodedata

from flask_babel import lazy_gettext as _l

# modelo -> (nombre corto, qué es, qué suele hacer falta de ti, cuándo)
MODELOS: dict[str, tuple] = {
    "303": (_l("IVA trimestral"), _l("Resume el IVA que has cobrado a tus clientes menos el IVA que has pagado en tus compras y gastos. Si cobraste más de lo que pagaste, se ingresa la diferencia; si no, sale a compensar o a devolver."),
            _l("Todas tus facturas emitidas y recibidas del trimestre, con el IVA bien visible."), _l("Cada trimestre, durante los 20 primeros días de abril, julio y octubre, y hasta el 30 de enero el último trimestre.")),
    "390": (_l("Resumen anual del IVA"), _l("Recoge en un solo documento lo que declaraste en los cuatro modelos 303 del año. Normalmente no se paga nada."),
            _l("Normalmente nada nuevo: se hace con lo que ya hemos recibido durante el año."), _l("En enero, junto al cuarto trimestre.")),
    "130": (_l("Pago a cuenta del IRPF (autónomos)"), _l("Es un adelanto de tu declaración de la Renta si eres autónomo: se calcula con tus ingresos menos tus gastos del año hasta ahora, y se restan los pagos de trimestres anteriores."),
            _l("Facturas emitidas y recibidas del trimestre, y las retenciones que te hayan practicado."), _l("Cada trimestre, durante los 20 primeros días de abril, julio y octubre, y hasta el 30 de enero el último.")),
    "131": (_l("Pago a cuenta del IRPF (módulos)"), _l("Es el adelanto trimestral del IRPF para autónomos que tributan por módulos: no depende de tus gastos, sino de datos como tus trabajadores o tus metros."),
            _l("Los datos de tu actividad que hayan cambiado (personal, superficie, consumos)."), _l("Cada trimestre, durante los 20 primeros días de abril, julio y octubre, y hasta el 30 de enero el último.")),
    "100": (_l("Declaración de la Renta"), _l("Es tu declaración anual del IRPF: suma tus ingresos del año, resta lo que la ley permite y compara el resultado con lo que ya te retuvieron o pagaste a cuenta."),
            _l("Documentos de tus ingresos, gastos deducibles, hipoteca, hijos o cambios de domicilio, y tus datos bancarios."), _l("Cada año, de abril a finales de junio.")),
    "111": (_l("Retenciones de trabajadores y profesionales"), _l("Es lo que has retenido del sueldo de tus empleados o de las facturas de profesionales y has de ingresar a Hacienda a su nombre."),
            _l("Nóminas del trimestre y las facturas de profesionales que llevan retención."), _l("Cada trimestre, durante los 20 primeros días de abril, julio y octubre, y hasta el 20 de enero el último.")),
    "115": (_l("Retenciones de alquileres"), _l("Si alquilas un local para tu actividad, retienes una parte del alquiler y la ingresas a Hacienda por cuenta de quien te lo alquila."),
            _l("Las facturas del alquiler del trimestre."), _l("Cada trimestre, durante los 20 primeros días de abril, julio y octubre, y hasta el 20 de enero el último.")),
    "190": (_l("Resumen anual de retenciones de trabajo y profesionales"), _l("Resume todo lo declarado en los modelos 111 del año, persona por persona. Normalmente no se paga."),
            _l("Normalmente nada nuevo: se hace con lo ya declarado."), _l("En enero.")),
    "180": (_l("Resumen anual de retenciones de alquileres"), _l("Resume todo lo declarado en los modelos 115 del año. Normalmente no se paga."), _l("Normalmente nada nuevo: se hace con lo ya declarado."), _l("En enero.")),
    "347": (_l("Operaciones con clientes y proveedores"), _l("Informa a Hacienda de los clientes y proveedores con los que has movido más de 3.005,06 € en el año. No se paga nada: es una comparación de datos."),
            _l("Que tus facturas del año estén completas, con el NIF de cada cliente y proveedor."), _l("En febrero.")),
    "349": (_l("Operaciones con la Unión Europea"), _l("Informa de lo que has vendido o comprado a empresas de otros países de la UE. No se paga nada."), _l("Las facturas de operaciones con empresas europeas, con su NIF-IVA."),
            _l("Cada trimestre o cada mes, según el volumen.")),
    "200": (_l("Impuesto de Sociedades"), _l("Es el impuesto anual sobre el beneficio de una sociedad: ingresos menos gastos del ejercicio, con los ajustes que marca la ley."),
            _l("Las cuentas del año cerradas, el extracto de los bancos y los documentos de operaciones especiales."), _l("En julio, para las sociedades cuyo ejercicio coincide con el año natural.")),
    "202": (_l("Pago a cuenta del Impuesto de Sociedades"), _l("Es un adelanto del Impuesto de Sociedades que se paga en abril, octubre y diciembre."), _l("Normalmente nada: lo calculamos con lo ya declarado."), _l("En abril, octubre y diciembre.")),
    "036": (_l("Alta o cambio en el censo"), _l("Sirve para dar de alta, modificar o dar de baja tu actividad en Hacienda: domicilio fiscal, actividad, régimen de IVA…"), _l("Tus datos personales o de la empresa y la descripción de la actividad."),
            _l("Antes de empezar la actividad o en el mes siguiente a un cambio.")),
    "720": (_l("Bienes y cuentas en el extranjero"), _l("Informa de cuentas, valores o inmuebles en otro país cuyo valor supere los 50.000 €. No se paga nada, pero no presentarlo tiene sanciones."), _l("Saldos y valoraciones a 31 de diciembre."), _l("De enero a marzo.")),
}
MODELOS["037"] = MODELOS["036"]

# palabra -> (nombre, explicación)
CONCEPTOS: dict[str, tuple] = {
    "iva-repercutido": (_l("IVA repercutido"), _l("El IVA que cobras en las facturas que haces a tus clientes. No es tuyo: lo ingresas a Hacienda.")),
    "iva-soportado": (_l("IVA soportado"), _l("El IVA que pagas en tus compras y gastos. Si son de tu actividad, lo puedes restar del IVA que has cobrado.")),
    "retencion": (_l("Retención"), _l("Una parte del importe de una factura o nómina que quien paga ingresa directamente a Hacienda a cuenta del IRPF de quien cobra.")),
    "pago-fraccionado": (_l("Pago fraccionado"), _l("Un adelanto trimestral de un impuesto anual, para no pagarlo todo de golpe al final.")),
    "autoliquidacion": (_l("Autoliquidación"), _l("Una declaración en la que calculas tú mismo (o tu gestoría) lo que debes, en vez de que lo haga Hacienda.")),
    "justificante": (_l("Justificante de presentación"), _l("El documento de Hacienda que prueba que un modelo se presentó dentro de plazo. Se guarda en tu carpeta.")),
    "certificado-digital": (_l("Certificado digital"), _l("Tu identidad electrónica para presentar impuestos. Caduca a los pocos años y hay que renovarlo antes de que venza.")),
    "domiciliacion": (_l("Domiciliación"), _l("Dejar que Hacienda cobre el importe de un modelo directamente de tu cuenta, el último día de plazo.")),
    "factura-simplificada": (_l("Factura simplificada (tiquet)"), _l("Un justificante de compra sin los datos del cliente, como los tiquets de tienda. Vale como gasto si cumple unos mínimos.")),
    "abono": (_l("Factura rectificativa (abono)"), _l("Una factura que corrige o anula otra anterior. Resta en lugar de sumar.")),
    "inversion-sujeto-pasivo": (_l("Inversión del sujeto pasivo"), _l("Casos en que no se cobra IVA en la factura y lo ingresa quien la recibe, como en muchas compras a empresas de otros países.")),
    "estimacion-directa": (_l("Estimación directa"), _l("Tributar por tus ingresos y gastos reales, frente a los módulos, donde se calcula con datos estándar.")),
}


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t).lower()) if unicodedata.category(c) != "Mn")


def por_modelo(modelo: str | None) -> dict | None:
    """{modelo, nombre, que_es, que_hace_falta, cuando} del modelo (admite «303», «Modelo 303» o «303 1T»), o None si no está en el glosario."""
    m = re.search(r"\b(\d{3})\b", modelo or "")
    datos = MODELOS.get(m.group(1)) if m else None
    if not datos:
        return None
    return {"modelo": m.group(1), "nombre": datos[0], "que_es": datos[1], "que_hace_falta": datos[2], "cuando": datos[3]}


def todo(busqueda: str = "") -> dict:
    """{modelos: [...], conceptos: [...]} filtrados por una búsqueda sin tildes ni mayúsculas (vacía = todo)."""
    q = _sin_tildes(busqueda).strip()
    modelos = [dict(por_modelo(k), modelo=k) for k in MODELOS if k != "037"]
    conceptos = [{"clave": k, "nombre": v[0], "texto": v[1]} for k, v in CONCEPTOS.items()]
    if q:
        modelos = [m for m in modelos if q in _sin_tildes(f"{m['modelo']} {m['nombre']} {m['que_es']}")]
        conceptos = [c for c in conceptos if q in _sin_tildes(f"{c['nombre']} {c['texto']}")]
    return {"modelos": modelos, "conceptos": conceptos}
