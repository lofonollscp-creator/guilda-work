"""Capa fina de la presentación directa en la AEAT (especificaciones de servicios, versión 30; `docs/integracion-aeat-presentacion.md`): arma la petición, comprueba el fichero e interpreta las respuestas.

**No abre ninguna conexión ni toca ninguna clave.** La conexión TLS con el certificado del presentador la hará quien se decida en el paso 2 del plan (agente local o servicio aislado); este módulo es lo que tienen en común.
El contenido de `F01` es el fichero plano que ya genera el exportador de cada modelo (una línea, ASCII, sin CRLF).

Una respuesta que no se entiende NUNCA se toma por fallo: se devuelve `dudosa` y quien llama debe consultar lo presentado antes de reenviar (la AEAT no permite anular lo grabado)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

MODELOS_PRESENTACION = ("005", "030", "036", "100", "111", "115", "117", "123", "124", "126", "128", "130", "131", "151", "200", "202", "210", "211", "213", "216", "222", "232", "237", "242", "303", "308", "309",
                        "319", "322", "353", "390", "490", "576", "604", "695", "696", "714", "780", "781", "792", "793", "VEG", "20A", "22A")
IDIOMAS = ("ES", "EN", "VA", "GL", "CA")
URL_PRESENTACION = {"produccion": "https://www1.agenciatributaria.gob.es/wlpl/PFTW-PICW/PresBasicaDos", "pruebas": "https://prewww1.aeat.es/wlpl/PFTW-PICW/PresBasicaDos"}
URL_CONSULTA = "https://www1.agenciatributaria.gob.es/wlpl/SCEJ-MANT/ConsultaExt"
URL_VALIDACION = "https://prewww2.aeat.es/wlpl/PFTW-PICW/ServValiDos"          # solo existe en el entorno de pruebas

# Caracteres de datos admitidos (tabla de la especificación, ISO-8859-1, por código decimal). Las etiquetas del diseño de registro (<T30301000>…) van aparte.
_CODIGOS = [32, 34, 35, 38, 39, 40, 41, 43, 44, 45, 46, 47, 58, 59, 64, 95, 170, 183, 186, 223, 198, 230, 197, 229, 195, 227, 213, 245, 216, 248, 199, 231, 209, 241,
            *range(48, 58), *range(65, 91), *range(97, 123),
            225, 233, 237, 243, 250, 193, 201, 205, 211, 218, 228, 235, 239, 246, 252, 196, 203, 207, 214, 220, 224, 232, 236, 242, 249, 192, 200, 204, 210, 217,
            226, 234, 238, 244, 251, 194, 202, 206, 212, 219]
CARACTERES_VALIDOS = frozenset(bytes(_CODIGOS).decode("latin-1"))
_ETIQUETA = re.compile(r"</?[A-Za-z0-9]+>")


class PeticionInvalida(ValueError):
    """La petición no cumple la especificación: no se envía nada."""


def comprobar_fichero(f01: str) -> None:
    if not isinstance(f01, str) or not f01.strip():
        raise PeticionInvalida("El fichero de la declaración está vacío.")
    if any(c in f01 for c in "\r\n\t"):
        raise PeticionInvalida("El fichero lleva saltos de línea o tabuladores: la AEAT no los admite.")
    malos = sorted({c for c in _ETIQUETA.sub("", f01) if c not in CARACTERES_VALIDOS})
    if malos:
        raise PeticionInvalida("El fichero lleva caracteres que la AEAT no admite: " + " ".join(repr(c) for c in malos[:8]))


def huella_fichero(f01: str) -> str:
    """SHA-256 del fichero que se revisó y confirmó: la orden de presentar va ligada a esta huella."""
    return hashlib.sha256(f01.encode("utf-8")).hexdigest()


def construir_peticion(modelo: str, ejercicio: int | str, periodo: str, f01: str, *, nif_presentador: str, nombre_presentador: str, nrc: str = "", idioma: str = "ES") -> dict:
    """El objeto JSON del §1.2 de la especificación. `nrc` solo para declaraciones a ingresar (tipo I); en cualquier otro caso, vacío."""
    modelo = str(modelo).strip().upper()
    if modelo not in MODELOS_PRESENTACION:
        raise PeticionInvalida(f"El modelo {modelo} no está entre los que admite el servicio de presentación.")
    if not re.fullmatch(r"\d{4}", str(ejercicio)):
        raise PeticionInvalida("El ejercicio debe tener cuatro cifras.")
    if not re.fullmatch(r"[0-9A-Z]{2}", str(periodo)):
        raise PeticionInvalida("El periodo debe tener dos caracteres (p. ej. 2T, 01, 0A).")
    if idioma not in IDIOMAS:
        raise PeticionInvalida("Idioma del justificante no válido.")
    nif = re.sub(r"[\s.\-]", "", str(nif_presentador or "")).upper()
    if not re.fullmatch(r"[0-9A-Z]{9}", nif):
        raise PeticionInvalida("El NIF del presentador no es válido.")
    if not str(nombre_presentador or "").strip():
        raise PeticionInvalida("Falta el nombre del presentador (el del titular del certificado).")
    nrc = str(nrc or "").strip().upper()
    if nrc and not re.fullmatch(r"[0-9A-Z]{22}", nrc):
        raise PeticionInvalida("El NRC debe tener 22 caracteres.")
    comprobar_fichero(f01)
    return {"MODELO": modelo, "EJERCICIO": str(ejercicio), "PERIODO": str(periodo), "NRC": nrc, "IDI": idioma, "F01": f01, "FIR": "FirmaBasica", "FIRNIF": nif, "FIRNOMBRE": str(nombre_presentador).strip()[:100]}


def cuerpo_json(peticion: dict) -> bytes:
    """Lo que viaja por la red: JSON en UTF-8 (la cabecera ha de ser `application/json;charset=UTF-8`)."""
    return json.dumps(peticion, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@dataclass
class Resultado:
    estado: str                                    # aceptada · rechazada · dudosa
    csv: str = ""
    fecha: str = ""
    hora: str = ""
    expediente: str = ""
    justificante: str = ""
    nrc_pago: str = ""
    importe_a_ingresar: str = ""
    forma_pago: str = ""
    tipo_representacion: str = ""
    nif_declarante: str = ""
    nif_presentador: str = ""
    url_pdf: str = ""
    avisos: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    motivo: str = ""                               # por qué es dudosa
    bruto: str = ""                                # la respuesta tal cual llegó, para guardarla íntegra


def _minusculas(objeto):
    """Claves en minúsculas y sin espacios (la propia especificación trae `"CodigoSeguroVerificacion "` con un espacio de más en su ejemplo)."""
    if isinstance(objeto, dict):
        return {str(k).strip().lower(): _minusculas(v) for k, v in objeto.items()}
    if isinstance(objeto, list):
        return [_minusculas(v) for v in objeto]
    return objeto


def _lista(valor) -> list[str]:
    if isinstance(valor, list):
        return [str(v) for v in valor]
    return [p.strip() for p in str(valor or "").split(",") if p.strip()]


def interpretar_presentacion(texto: str | bytes | None) -> Resultado:
    """Respuesta del servicio de presentación → `Resultado`. Solo es `aceptada` si trae CSV de 16 caracteres y la URL del PDF, que la especificación garantiza en toda respuesta correcta."""
    bruto = texto.decode("utf-8", "replace") if isinstance(texto, bytes) else str(texto or "")
    try:
        datos = _minusculas(json.loads(bruto))
        cuerpo = datos["respuesta"]
        if not isinstance(cuerpo, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return Resultado("dudosa", motivo="La respuesta de la AEAT no se entiende: hay que consultar lo presentado antes de reenviar.", bruto=bruto)
    if cuerpo.get("errores"):
        return Resultado("rechazada", errores=_lista(cuerpo["errores"]), bruto=bruto)
    ok = cuerpo.get("correcta")
    if not isinstance(ok, dict):
        return Resultado("dudosa", motivo="La respuesta no trae ni errores ni datos de aceptación.", bruto=bruto)
    csv = str(ok.get("codigoseguroverificacion") or "").strip()
    r = Resultado("aceptada", csv=csv, fecha=str(ok.get("fecha") or ""), hora=str(ok.get("hora") or ""), expediente=str(ok.get("expediente") or ""), justificante=str(ok.get("justificante") or "").strip(),
                  nrc_pago=str(ok.get("nrcpago") or ""), importe_a_ingresar=str(ok.get("importeaingresar") or ""), forma_pago=str(ok.get("formapago") or ""),
                  tipo_representacion=str(ok.get("tiporepresentacion") or ""), nif_declarante=str(ok.get("nifdeclarante") or ""), nif_presentador=str(ok.get("nifpresentador") or ""),
                  url_pdf=str(ok.get("urlpdf") or ""), avisos=_lista(ok.get("avisos")), advertencias=_lista(ok.get("advertencias")), bruto=bruto)
    if len(csv) != 16 or not r.url_pdf:
        return Resultado("dudosa", motivo="La respuesta parece una aceptación pero le falta el CSV o la URL del justificante.", avisos=r.avisos, advertencias=r.advertencias, bruto=bruto)
    if r.justificante and not re.fullmatch(r"\d{13}", r.justificante):
        r.advertencias.append("El número de justificante no tiene 13 cifras: revísalo en el PDF.")
    return r


def interpretar_validacion(texto: str | bytes | None) -> dict:
    """Respuesta de `ServValiDos` → `{avisos, errores, pdf_base64}`. Los avisos no impiden presentar; los errores sí. Si no se entiende, cuenta como error: validar no tiene efectos y se puede repetir."""
    bruto = texto.decode("utf-8", "replace") if isinstance(texto, bytes) else str(texto or "")
    try:
        cuerpo = _minusculas(json.loads(bruto))["respuesta"]
        if not isinstance(cuerpo, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return {"avisos": [], "errores": ["La respuesta de validación no se entiende."], "pdf_base64": ""}
    pdf = cuerpo.get("pdf")
    return {"avisos": _lista(cuerpo.get("avisos")), "errores": _lista(cuerpo.get("errores")), "pdf_base64": str(pdf[0]) if isinstance(pdf, list) and pdf else ""}
