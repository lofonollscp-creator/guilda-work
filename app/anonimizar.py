"""Protección de datos personales ANTES de que un texto salga hacia un proveedor de IA externo (RGPD art. 5.1.c minimización, 25 protección desde el diseño, 32 seguridad y 44 transferencias).

Funciona por seudonimización reversible, por petición: cada dato personal detectado (nombre de persona, NIF/NIE/CIF, IBAN, tarjeta, teléfono, correo, dirección postal) se sustituye por una etiqueta
estable (`[PERSONA_1]`, `[NIF_1]`…) que es lo único que ve el proveedor; cuando el modelo contesta (o pide ejecutar una herramienta con esas etiquetas) se devuelven los valores reales. Así el asistente sigue
siendo útil —razona sobre «[PERSONA_1]» y las herramientas reciben el dato real— pero el proveedor no recibe quién es nadie.

Detección con Presidio (reconocedores de NIF/NIE, IBAN, tarjeta, correo, teléfono y NER de spaCy para nombres) más reconocedores propios para CIF (con dígito de control), teléfonos españoles y direcciones.
No se enmascaran empresas, ciudades ni fechas: no son datos personales de una persona física y quitarlas empeora las respuestas.

Límites (se dicen a quien administra, ver docs/rgpd.md): el NER de nombres no es perfecto (puede dejar pasar un nombre raro o enmascarar de más); las imágenes y PDF que se mandan a leer (facturas) NO se pueden tratar así.

`GUILDA_IA_ANONIMIZAR`: «1» (por defecto) activa la protección y, si el detector no puede cargar, el envío se BLOQUEA (nunca se manda sin proteger); «0» la desactiva (solo desarrollo y pruebas)."""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import threading

log = logging.getLogger(__name__)
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)       # avisos de reconocedores de otros idiomas que no usamos

MODELO_SPACY = "es_core_news_md"
TROZO_MAX = 6000                      # caracteres por análisis: el NER va por trozos para no disparar tiempo ni memoria
ETIQUETAS = {
    "PERSON": "PERSONA", "ES_NIF": "NIF", "ES_NIE": "NIF", "ES_CIF": "CIF", "IBAN_CODE": "IBAN", "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "TELEFONO", "CREDIT_CARD": "TARJETA", "ES_DIRECCION": "DIRECCION",
}
_PATRON_ETIQUETA = re.compile(r"\[(?:%s)_\d+\]" % "|".join(sorted(set(ETIQUETAS.values()))))
_FORMA_SOCIETARIA = re.compile(r"\b(?:S\.?L\.?[UPL]?\.?|S\.?A\.?U?\.?|S\.?C\.?P?\.?|C\.?B\.?|S\.?Coop\.?|Asociaci[oó]n|Fundaci[oó]n|Ayuntamiento|Hacienda|Agencia Tributaria|Banco|Hotel)(?=\s|$|[.,;)])", re.IGNORECASE)
_BORDES = "\"'{}[],:;()<>"


class ErrorProteccionDatos(Exception):
    """El detector de datos personales no está disponible: no se envía nada al proveedor."""


def activada() -> bool:
    return os.environ.get("GUILDA_IA_ANONIMIZAR", "1") != "0"


# --- Detector (Presidio), cargado una sola vez y bajo demanda ---------------------------------------------------------

_motor = None
_cerrojo = threading.Lock()


def _cif_valido(texto: str) -> bool:
    t = re.sub(r"[\s-]", "", texto).upper()
    if not re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", t):
        return False
    cifras = t[1:8]
    pares = sum(int(c) for c in cifras[1::2])
    impares = sum(sum(divmod(int(c) * 2, 10)) for c in cifras[0::2])
    control = (10 - (pares + impares) % 10) % 10
    return t[8] in (str(control), "JABCDEFGHI"[control])


def _construir_motor():
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    class _Cif(PatternRecognizer):
        def validate_result(self, pattern_text: str):
            return _cif_valido(pattern_text)

    nlp = NlpEngineProvider(nlp_configuration={"nlp_engine_name": "spacy", "models": [{"lang_code": "es", "model_name": MODELO_SPACY}]}).create_engine()
    registro = RecognizerRegistry(supported_languages=["es"])
    registro.load_predefined_recognizers(languages=["es"], nlp_engine=nlp)
    registro.add_recognizer(_Cif(supported_entity="ES_CIF", supported_language="es", patterns=[Pattern("cif", r"\b[ABCDEFGHJNPQRSUVWabcdefghjnpqrsuvw][ -]?\d{7}[ -]?[0-9A-Ja-j]\b", 0.6)]))
    registro.add_recognizer(PatternRecognizer(supported_entity="PHONE_NUMBER", supported_language="es", name="TelefonoEspanol", patterns=[
        Pattern("es_movil_fijo", r"(?<!\d)(?:(?:\+|00)34[ .-]?)?[6-9]\d{2}(?:[ .-]?\d{3}){2}(?!\d)", 0.75),
        Pattern("es_pares", r"(?<!\d)(?:(?:\+|00)34[ .-]?)?[6-9]\d{2}(?:[ .-]?\d{2}){3}(?!\d)", 0.7),
        Pattern("es_fijo_2_3_2_2", r"(?<!\d)(?:(?:\+|00)34[ .-]?)?9\d[ .-]\d{3}[ .-]\d{2}[ .-]\d{2}(?!\d)", 0.7),
    ]))
    registro.add_recognizer(PatternRecognizer(supported_entity="ES_DIRECCION", supported_language="es", name="DireccionPostal", patterns=[Pattern(
        "via", r"\b(?:[Cc]alle|C/|[Aa]vda\.?|[Aa]venida|[Pp]laza|[Pp]za\.?|[Pp]aseo|[Pp]g\.?|[Cc]amino|[Cc]arrer|[Pp]asseig|[Rr]ambla|[Rr]onda|[Tt]ravesía|[Cc]arretera)\s+[^\d,\n\[\]]{2,45}?,?\s*(?:n[ºo°.]\s*)?\d{1,4}(?:\s*[-,]?\s*(?:\d{1,2}[ºª]?|[A-Za-z]\b))*", 0.7)]))
    return AnalyzerEngine(nlp_engine=nlp, registry=registro, supported_languages=["es"])


def _obtener_motor():
    global _motor
    if _motor is None:
        with _cerrojo:
            if _motor is None:
                try:
                    _motor = _construir_motor()
                except Exception as e:  # noqa: BLE001 -- sin detector no se manda nada
                    log.exception("No se pudo cargar el detector de datos personales")
                    raise ErrorProteccionDatos("El detector de datos personales no está disponible; no se envía nada al modelo de IA.") from e
    return _motor


def precargar() -> None:
    """Carga el detector (≈1 s y unos 300 MB): se llama al arrancar para no pagarlo en la primera consulta."""
    if activada():
        _obtener_motor()


def _trozos(texto: str):
    inicio = 0
    while inicio < len(texto):
        fin = min(len(texto), inicio + TROZO_MAX)
        if fin < len(texto):
            corte = max(texto.rfind("\n", inicio, fin), texto.rfind(" ", inicio, fin))
            fin = corte + 1 if corte > inicio else fin
        yield inicio, texto[inicio:fin]
        inicio = fin


@functools.lru_cache(maxsize=4096)
def _detectar(texto: str) -> tuple[tuple[int, int, str], ...]:
    """Tramos (inicio, fin, etiqueta) de datos personales en `texto`, sin solapes. En caché: los mensajes de una conversación no cambian."""
    motor = _obtener_motor()
    hallados: list[tuple[int, int, str, float]] = []
    for desplazamiento, trozo in _trozos(texto):
        for r in motor.analyze(text=trozo, language="es", entities=list(ETIQUETAS), score_threshold=0.4):
            ini, fin = r.start, r.end
            while ini < fin and trozo[ini] in _BORDES + " ":
                ini += 1
            while fin > ini and trozo[fin - 1] in _BORDES + " .":
                fin -= 1
            if r.entity_type == "PERSON" and _FORMA_SOCIETARIA.search(trozo[ini:fin]):
                continue                                          # «Construcciones Vidal SL»: una sociedad no es una persona física
            if fin - ini >= 2:
                hallados.append((desplazamiento + ini, desplazamiento + fin, ETIQUETAS[r.entity_type], r.score))
    hallados.sort(key=lambda h: (-(h[1] - h[0]), -h[3]))          # primero lo más largo: un IBAN gana a un número suelto dentro de él
    elegidos: list[tuple[int, int, str]] = []
    for ini, fin, etiqueta, _ in hallados:
        if all(fin <= a or ini >= b for a, b, _ in elegidos):
            elegidos.append((ini, fin, etiqueta))
    return tuple(sorted(elegidos))


def _clave(etiqueta: str, valor: str) -> str:
    v = valor.strip().casefold()
    return etiqueta + ":" + (re.sub(r"[\s.-]", "", v) if etiqueta in ("NIF", "CIF", "IBAN", "TELEFONO", "TARJETA") else re.sub(r"\s+", " ", v))


class Seudonimizador:
    """Una instancia por petición al proveedor: las etiquetas son estables dentro de ella (mismo valor → misma etiqueta) y `restaurar` las deshace."""

    def __init__(self):
        self._por_clave: dict[str, str] = {}
        self._valores: dict[str, str] = {}
        self._contadores: dict[str, int] = {}
        self.protegidos: dict[str, int] = {}

    def _etiqueta_para(self, etiqueta: str, valor: str) -> str:
        clave = _clave(etiqueta, valor)
        marca = self._por_clave.get(clave)
        if marca is None:
            self._contadores[etiqueta] = self._contadores.get(etiqueta, 0) + 1
            marca = f"[{etiqueta}_{self._contadores[etiqueta]}]"
            self._por_clave[clave] = marca
            self._valores[marca] = valor
            self.protegidos[etiqueta] = self.protegidos.get(etiqueta, 0) + 1
        return marca

    def conocer(self, etiqueta: str, valor: str) -> None:
        """Dato que ya sabemos que es personal (p. ej. el nombre de quien usa la app) aunque el detector no lo vea en este texto."""
        if valor and valor.strip():
            self._etiqueta_para(etiqueta, valor.strip())

    def _sustituir_conocidos(self, texto: str) -> str:
        for marca, valor in sorted(self._valores.items(), key=lambda x: -len(x[1])):
            if valor in texto:
                texto = texto.replace(valor, marca)
        return texto

    def proteger(self, texto: str | None) -> str | None:
        if not texto or not activada():
            return texto
        texto = self._sustituir_conocidos(texto)
        partes, cursor = [], 0
        for ini, fin, etiqueta in _detectar(texto):
            partes.append(texto[cursor:ini])
            partes.append(self._etiqueta_para(etiqueta, texto[ini:fin]))
            cursor = fin
        partes.append(texto[cursor:])
        return "".join(partes)

    def proteger_json(self, valor):
        """Como `proteger` sobre cadenas dentro de listas y diccionarios (cargas de herramientas), sin tocar la estructura."""
        if isinstance(valor, str):
            return self.proteger(valor)
        if isinstance(valor, list):
            return [self.proteger_json(v) for v in valor]
        if isinstance(valor, dict):
            return {k: self.proteger_json(v) for k, v in valor.items()}
        return valor

    def restaurar(self, texto: str | None) -> str | None:
        if not texto or not self._valores:
            return texto
        return _PATRON_ETIQUETA.sub(lambda m: self._valores.get(m.group(0), m.group(0)), texto)

    def restaurar_json(self, valor):
        if isinstance(valor, str):
            return self.restaurar(valor)
        if isinstance(valor, list):
            return [self.restaurar_json(v) for v in valor]
        if isinstance(valor, dict):
            return {k: self.restaurar_json(v) for k, v in valor.items()}
        return valor

    def restaurar_argumentos(self, argumentos: str | None) -> str | None:
        """Argumentos JSON (texto) de una llamada a herramienta, con los valores reales ya puestos y el JSON sigue siendo válido."""
        if not argumentos or not self._valores:
            return argumentos
        try:
            return json.dumps(self.restaurar_json(json.loads(argumentos)), ensure_ascii=False)
        except ValueError:
            return self.restaurar(argumentos)

    def proteger_mensajes(self, mensajes: list[dict]) -> list[dict]:
        """Copia de la lista de mensajes de `chat/completions` con los datos personales sustituidos (el mensaje de sistema y los nombres de herramientas no se tocan)."""
        if not activada():
            return mensajes
        salida = []
        for m in mensajes:
            n = dict(m)
            if n.get("role") != "system":
                if isinstance(n.get("content"), str):
                    n["content"] = self.proteger(n["content"])
                elif isinstance(n.get("content"), list):
                    n["content"] = [dict(p, text=self.proteger(p["text"])) if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str) else p for p in n["content"]]
                if n.get("tool_calls"):
                    n["tool_calls"] = [dict(tc, function=dict(tc["function"], arguments=self._proteger_argumentos(tc["function"].get("arguments")))) for tc in n["tool_calls"]]
            else:
                n["content"] = self._sustituir_conocidos(n["content"]) if isinstance(n.get("content"), str) else n.get("content")   # solo lo ya conocido: sin NER sobre las instrucciones
            salida.append(n)
        return salida

    def _proteger_argumentos(self, argumentos: str | None) -> str | None:
        if not argumentos:
            return argumentos
        try:
            return json.dumps(self.proteger_json(json.loads(argumentos)), ensure_ascii=False)
        except ValueError:
            return self.proteger(argumentos)

    def resumen(self) -> str:
        return ", ".join(f"{n} {e.lower()}" for e, n in sorted(self.protegidos.items())) or "nada"


class RestauradorEnStream:
    """Deshace las etiquetas en un texto que llega en trozos: un trozo puede acabar en mitad de «[PERSONA_1]», así que se retiene desde el último «[» sin cerrar."""

    def __init__(self, seudonimizador: Seudonimizador):
        self._sp = seudonimizador
        self._pendiente = ""

    def alimentar(self, trozo: str) -> str:
        texto = self._pendiente + trozo
        corte = texto.rfind("[")
        if corte != -1 and "]" not in texto[corte:] and len(texto) - corte <= 24:
            self._pendiente, texto = texto[corte:], texto[:corte]
        else:
            self._pendiente = ""
        return self._sp.restaurar(texto) or ""

    def terminar(self) -> str:
        resto, self._pendiente = self._pendiente, ""
        return self._sp.restaurar(resto) or ""
