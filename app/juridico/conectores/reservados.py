"""Conectores reservados: el contrato existe, el transporte NO. Están desactivados y no inventan endpoints.

- `CendojLicenciado`: jurisprudencia ordinaria del Poder Judicial. Sin documentación técnica ni contrato de suministro no hay cliente que escribir; hace falta confirmar canal, derechos de indexación,
  envío al modelo, almacenamiento, exportación y costes (ver el apartado «Información que obtener del proveedor» del anexo de flujos).
- `EurLexCellar`: búsqueda SOAP registrada de EUR-Lex y metadatos/archivos de Cellar. Requiere alta y validar el WSDL y las consultas CDM contra el servicio real antes de presentarlo como funcional.
- `Hudoc`, `OnuJuris`: instancias internacionales, fase posterior.
Un conector reservado declara `Capacidades()` vacías y lanza `ConectorNoDisponible`: el motor lo muestra como «pendiente de habilitación»."""
from __future__ import annotations

from .base import Conector


class CendojLicenciado(Conector):
    id = "cendoj-licenciado"
    nombre = "Poder Judicial / CENDOJ (suministro autorizado)"
    coleccion = "jurisprudencia"


class EurLexCellar(Conector):
    id = "eurlex-cellar"
    nombre = "EUR-Lex / Cellar (jurisprudencia de la UE)"
    coleccion = "jurisprudencia"


class Hudoc(Conector):
    id = "hudoc"
    nombre = "TEDH · HUDOC"
    coleccion = "jurisprudencia"


class OnuJuris(Conector):
    id = "onu-juris"
    nombre = "ONU · decisiones de órganos de tratados"
    coleccion = "jurisprudencia"
