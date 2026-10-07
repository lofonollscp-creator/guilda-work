"""Alta rápida de tareas en texto libre: «viernes 10h pedir extractos a Sol @luis !alta #IVA».

Función pura (sin base de datos ni peticiones): recibe el texto, el día de hoy y las personas y
etiquetas (proyectos o secciones) que existen, y devuelve qué ha entendido. Lo que no se puede
resolver con seguridad (una @mención ambigua o inexistente, una #etiqueta que no existe) NO se
adivina: se devuelve en `sin_resolver` y se deja en el texto de la tarea.

Entiende fechas y horas en castellano, catalán, inglés y francés:
  hoy · mañana · pasado mañana · lunes…domingo (el próximo) · en 3 días · en 2 semanas · en 1 mes ·
  15/7 · 15/07/2027 · 2026-10-15 · 15 de julio · 15 jul · julio 15 · 10h · 10:30 · 10h30 · a las 10 · 3pm
Y marcas: «!alta», «!baja», «!normal» (y «!!» para alta); «@nombre»; «#etiqueta»."""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


DIAS_SEMANA = {
    0: ("lunes", "dilluns", "monday", "lundi"), 1: ("martes", "dimarts", "tuesday", "mardi"),
    2: ("miercoles", "dimecres", "wednesday", "mercredi"), 3: ("jueves", "dijous", "thursday", "jeudi"),
    4: ("viernes", "divendres", "friday", "vendredi"), 5: ("sabado", "dissabte", "saturday", "samedi"),
    6: ("domingo", "diumenge", "sunday", "dimanche"),
}
MESES = {
    1: ("enero", "gener", "january", "janvier", "ene", "jan"), 2: ("febrero", "febrer", "february", "fevrier", "feb"),
    3: ("marzo", "marc", "march", "mars", "mar"), 4: ("abril", "april", "avril", "abr", "apr", "avr"),
    5: ("mayo", "maig", "may", "mai"), 6: ("junio", "juny", "june", "juin", "jun"),
    7: ("julio", "juliol", "july", "juillet", "jul"), 8: ("agosto", "agost", "august", "aout", "ago", "aug"),
    9: ("septiembre", "setembre", "september", "septembre", "sep", "sept"), 10: ("octubre", "october", "octobre", "oct"),
    11: ("noviembre", "novembre", "november", "nov"), 12: ("diciembre", "desembre", "december", "decembre", "dic", "dec", "des"),
}
_DIA_POR_PALABRA = {p: n for n, ps in DIAS_SEMANA.items() for p in ps}
_MES_POR_PALABRA = {p: n for n, ps in MESES.items() for p in ps}
_PRIORIDAD_POR_PALABRA = {
    "alta": "alta", "urgente": "alta", "high": "alta", "haute": "alta", "urgent": "alta", "alt": "alta",
    "baja": "baja", "baixa": "baja", "low": "baja", "basse": "baja",
    "normal": "normal", "media": "normal", "mitja": "normal", "medium": "normal", "moyenne": "normal",
}

# Todo se busca sobre el texto SIN acentos y en minúsculas (mismas posiciones que el original: NFD no
# cambia la longitud al quitar marcas porque se compone de nuevo; se trabaja sobre una copia alineada).
_PAL = r"[a-z]+"
_RE_PRIORIDAD = re.compile(r"(?<![\w!])(!!|!([a-z]+))(?!\w)")
_RE_MENCION = re.compile(r"(?<![\w@])@([\w.\-]+)")
_RE_ETIQUETA = re.compile(r'(?<![\w#])#(?:"([^"]+)"|([\w\-]+))')
_RE_ISO = re.compile(r"(?<![\d/-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\d/-])")
_RE_NUMERICA = re.compile(r"(?<![\d/.-])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?![\d/.-])|(?<![\d/.-])(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?![\d/.-])")
_RE_DIA_MES = re.compile(rf"(?<!\w)(\d{{1,2}})(?:\s+(?:de|d'|del)\s*|\s+|\s*-\s*)({_PAL})\.?(?:\s+(?:de|del)\s+(\d{{4}}))?(?!\w)")
_RE_MES_DIA = re.compile(rf"(?<!\w)({_PAL})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?!\w)")
_RE_EN_N = re.compile(r"(?<!\w)(?:en|in|dins de|dans)\s+(\d{1,3})\s+(dias?|dies?|days?|jours?|semanas?|setmanes?|weeks?|semaines?|mes(?:es)?|mesos?|months?|mois)(?!\w)")
_RE_PASADO = re.compile(r"(?<!\w)(pasado\s+manana|passat\s+dema|day\s+after\s+tomorrow|apres[\s-]demain)(?!\w)")
_RE_MANANA = re.compile(r"(?<!la )(?<!\w)(manana|dema|tomorrow|demain)(?!\w)")
_RE_HOY = re.compile(r"(?<!\w)(hoy|avui|today|aujourd'hui|aujourdhui)(?!\w)")
_RE_DIA_SEMANA = re.compile(rf"(?<!\w)(?:(?:el|este|proximo|proper|next|prochain|aquest|dia|this)\s+)?({_PAL})(?!\w)")
_RE_HORA = re.compile(
    r"(?<![\d:/.-])(?:(?:a\s+las?|a\s+les|at|a|à|vers)\s+)?(\d{1,2})(?:(?::|h)(\d{2})|\s*h(?!\w)|\s*(am|pm)(?!\w))(?![\d:/])"
)
_RE_HORA_SOLA = re.compile(r"(?<![\d:/.-])(?:a\s+las?|a\s+les|at|à)\s+(\d{1,2})(?![\d:/.-]|\s*(?:de|d'|/))")
_CONECTORES_FINALES = re.compile(r"(?:\s+(?:para\s+el|para|per\s+al|per|for|pour\s+le|pour|el|al|a\s+las|a|de|en|on|le|du))+\s*$")
_CONECTORES_INICIALES = re.compile(r"^\s*(?:para\s+el|para|per\s+al|for|pour\s+le|el|al|on)\s+")


@dataclass
class Interpretacion:
    asunto: str
    fecha: date | None = None
    hora: str | None = None                    # "HH:MM"
    prioridad: str | None = None               # "alta" | "baja" | "normal"
    persona_id: int | None = None
    etiqueta_id: int | None = None             # proyecto o sección, según quién llame
    sin_resolver: list[str] = field(default_factory=list)

    @property
    def vencimiento(self) -> str | None:
        """Valor para `fecha_vencimiento`: «YYYY-MM-DD» o «YYYY-MM-DDTHH:MM» si hay hora."""
        if self.fecha is None:
            return None
        return f"{self.fecha.isoformat()}T{self.hora}" if self.hora else self.fecha.isoformat()


def _proximo_dia_semana(hoy: date, dia: int) -> date:
    """La próxima fecha con ese día de la semana: si hoy ya lo es, la semana siguiente."""
    return hoy + timedelta(days=(dia - hoy.weekday() - 1) % 7 + 1)


def _sumar_meses(origen: date, meses: int) -> date:
    indice = origen.month - 1 + meses
    anio, mes = origen.year + indice // 12, indice % 12 + 1
    return date(anio, mes, min(origen.day, calendar.monthrange(anio, mes)[1]))


def _fecha_sin_anio(hoy: date, dia: int, mes: int) -> date | None:
    """Ese día de este año, o del siguiente si ya ha pasado (sin año se entiende «la próxima vez»)."""
    for anio in range(hoy.year, hoy.year + 9):
        try:
            candidata = date(anio, mes, dia)
        except ValueError:
            continue
        if candidata >= hoy:
            return candidata
    return None


def _anio(texto: str | None, hoy: date) -> int | None:
    if not texto:
        return None
    n = int(texto)
    return n + 2000 if n < 100 else n


def _quitar(texto: str, inicio: int, fin: int) -> str:
    return texto[:inicio] + " " + texto[fin:]


class _Texto:
    """El texto original y su versión sin acentos, alineados carácter a carácter, para buscar sin
    acentos y recortar sobre el original. Cada recorte se aplica a las dos a la vez."""

    def __init__(self, original: str):
        self.original = original
        self.plano = "".join(_sin_acentos(c) if len(_sin_acentos(c)) == 1 else c.lower() for c in original)

    def quitar(self, inicio: int, fin: int) -> None:
        self.original = _quitar(self.original, inicio, fin)
        self.plano = _quitar(self.plano, inicio, fin)


def _buscar_persona(palabra: str, personas) -> tuple[int | None, bool]:
    """(id, ambigua). Coincide por el principio del nombre, de cualquier palabra del nombre o de la parte
    local del email; si hay un único candidato (o uno solo que coincida con la primera palabra), es ese."""
    buscada = _sin_acentos(palabra)
    candidatos = []
    for pid, nombre, email in personas:
        palabras = _sin_acentos(nombre or "").replace(".", " ").split()
        local = _sin_acentos((email or "").split("@")[0])
        if any(p.startswith(buscada) for p in palabras) or local.startswith(buscada):
            primera = bool(palabras) and palabras[0].startswith(buscada) or local.startswith(buscada)
            candidatos.append((pid, primera, any(p == buscada for p in palabras) or local == buscada))
    if len(candidatos) == 1:
        return candidatos[0][0], False
    exactos = [c for c in candidatos if c[2]]
    if len(exactos) == 1:
        return exactos[0][0], False
    primeros = [c for c in candidatos if c[1]]
    if len(primeros) == 1 and not exactos:
        return primeros[0][0], False
    return None, bool(candidatos)


def _buscar_etiqueta(palabra: str, etiquetas) -> int | None:
    buscada = re.sub(r"[^a-z0-9]", "", _sin_acentos(palabra))
    if not buscada:
        return None
    exactos, prefijos = [], []
    for eid, nombre in etiquetas:
        completo = re.sub(r"[^a-z0-9]", "", _sin_acentos(nombre))
        palabras = [re.sub(r"[^a-z0-9]", "", p) for p in _sin_acentos(nombre).split()]
        if completo == buscada:
            exactos.append(eid)
        elif completo.startswith(buscada) or any(p.startswith(buscada) for p in palabras if p):
            prefijos.append(eid)
    for grupo in (exactos, prefijos):
        if len(grupo) == 1:
            return grupo[0]
        if len(grupo) > 1:
            return None
    return None


def interpretar(texto: str, hoy: date, personas=(), etiquetas=()) -> Interpretacion:
    """`personas`: (id, nombre, email). `etiquetas`: (id, nombre). Devuelve lo entendido y el título que queda."""
    t = _Texto(texto or "")
    r = Interpretacion(asunto="")

    # 1. prioridad
    for m in list(_RE_PRIORIDAD.finditer(t.plano)):
        palabra = "alta" if m.group(1) == "!!" else _PRIORIDAD_POR_PALABRA.get(m.group(2) or "")
        if palabra:
            r.prioridad = r.prioridad or palabra
            t.quitar(m.start(), m.end())
            break

    # 2. @persona (varias menciones: se queda la primera que se resuelva; las demás se dejan en el texto)
    for m in list(_RE_MENCION.finditer(t.plano)):
        original = t.original[m.start():m.end()]
        pid, ambigua = _buscar_persona(m.group(1).rstrip(".-"), personas)
        if pid is not None and r.persona_id is None:
            r.persona_id = pid
            t.quitar(m.start(), m.end())
            break
        r.sin_resolver.append(original)
        break

    # 3. #etiqueta
    for m in list(_RE_ETIQUETA.finditer(t.original)):
        palabra = m.group(1) or m.group(2)
        eid = _buscar_etiqueta(palabra, etiquetas)
        if eid is not None and r.etiqueta_id is None:
            r.etiqueta_id = eid
            t.quitar(m.start(), m.end())
            break
        r.sin_resolver.append(t.original[m.start():m.end()])
        break

    # 4. fecha (se quita la primera expresión de fecha reconocida)
    fecha = None
    hora_antes_de_fecha = None
    for patron, fn in (
        (_RE_ISO, lambda m: _fecha_valida(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
        (_RE_PASADO, lambda m: hoy + timedelta(days=2)),
        (_RE_EN_N, lambda m: _relativa(hoy, int(m.group(1)), m.group(2))),
        (_RE_MANANA, lambda m: hoy + timedelta(days=1)),
        (_RE_HOY, lambda m: hoy),
        (_RE_NUMERICA, lambda m: _numerica(hoy, m)),
        (_RE_DIA_MES, lambda m: _dia_mes(hoy, m)),
        (_RE_MES_DIA, lambda m: _mes_dia(hoy, m)),
        (_RE_DIA_SEMANA, lambda m: _dia_semana(hoy, m)),
    ):
        for m in patron.finditer(t.plano):
            valor = fn(m)
            if valor is not None:
                fecha = valor
                t.quitar(m.start(), m.end())
                break
        if fecha is not None:
            break
    r.fecha = fecha

    # 5. hora
    for patron in (_RE_HORA, _RE_HORA_SOLA):
        m = patron.search(t.plano)
        if m:
            # «5h de trabajo» no es una hora: la «Nh» a secas solo cuenta si hay fecha o va con «a las».
            if patron is _RE_HORA and m.group(2) is None and m.group(3) is None and r.fecha is None and not re.match(r"(a\s|a$|à|at|vers)", m.group(0)):
                continue
            hora = _hora(int(m.group(1)), m.group(2) if patron is _RE_HORA else None, m.group(3) if patron is _RE_HORA else None)
            if hora:
                r.hora = hora
                t.quitar(m.start(), m.end())
                break
    if r.hora and r.fecha is None:
        r.fecha = hoy

    # 6. título: lo que queda, sin conectores sueltos
    restante = re.sub(r"\s+", " ", t.original).strip(" ,;:-–")
    plano = re.sub(r"\s+", " ", t.plano).strip(" ,;:-–")
    if (r.fecha or r.persona_id or r.prioridad or r.etiqueta_id) and restante:
        recorte = _CONECTORES_FINALES.search(plano)
        if recorte:
            restante = restante[:recorte.start()].rstrip(" ,;:-–")
        inicial = _CONECTORES_INICIALES.match(restante.lower())
        if inicial:
            restante = restante[inicial.end():]
    r.asunto = restante.strip(" ,;:-–") or (texto or "").strip()
    return r


def _fecha_valida(anio: int, mes: int, dia: int) -> date | None:
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _relativa(hoy: date, n: int, unidad: str) -> date | None:
    if unidad.startswith(("dia", "die", "day", "jour")):
        return hoy + timedelta(days=n)
    if unidad.startswith(("sem", "set", "week")):
        return hoy + timedelta(weeks=n)
    return _sumar_meses(hoy, n)


def _numerica(hoy: date, m: re.Match) -> date | None:
    if m.group(1) is not None:
        dia, mes, anio = int(m.group(1)), int(m.group(2)), _anio(m.group(3), hoy)
    else:  # dd.mm.aaaa (con puntos solo si lleva año: «10.30» es una hora, no el 10 de marzo)
        dia, mes, anio = int(m.group(4)), int(m.group(5)), _anio(m.group(6), hoy)
    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return None
    return _fecha_valida(anio, mes, dia) if anio else _fecha_sin_anio(hoy, dia, mes)


def _dia_mes(hoy: date, m: re.Match) -> date | None:
    mes = _MES_POR_PALABRA.get(m.group(2))
    dia = int(m.group(1))
    if mes is None or not 1 <= dia <= 31:
        return None
    anio = _anio(m.group(3), hoy)
    return _fecha_valida(anio, mes, dia) if anio else _fecha_sin_anio(hoy, dia, mes)


def _mes_dia(hoy: date, m: re.Match) -> date | None:
    mes = _MES_POR_PALABRA.get(m.group(1))
    dia = int(m.group(2))
    if mes is None or not 1 <= dia <= 31:
        return None
    anio = _anio(m.group(3), hoy)
    return _fecha_valida(anio, mes, dia) if anio else _fecha_sin_anio(hoy, dia, mes)


def _dia_semana(hoy: date, m: re.Match) -> date | None:
    dia = _DIA_POR_PALABRA.get(m.group(1))
    return _proximo_dia_semana(hoy, dia) if dia is not None else None


def _hora(hora: int, minutos: str | None, ampm: str | None) -> str | None:
    if ampm:
        if not 1 <= hora <= 12:
            return None
        hora = hora % 12 + (12 if ampm == "pm" else 0)
    if not 0 <= hora <= 23:
        return None
    m = int(minutos) if minutos else 0
    if not 0 <= m <= 59:
        return None
    return f"{hora:02d}:{m:02d}"
