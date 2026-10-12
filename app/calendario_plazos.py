"""Cálculo de plazos: días hábiles, festivos y avisos. Todo son funciones puras (sin base de datos ni Flask), para poder comprobarlas con casos
concretos; ningún cálculo con consecuencias vive en una plantilla ni en JavaScript (PLAN_MAESTRO.md §1.4).

Cada módulo (gestoría, gabinete de abogados, inmobiliaria) define su propio `Calendario`: qué días no cuentan y qué meses son inhábiles.
Los festivos que trae esta versión son **datos de ejemplo sin validar**: los nacionales fijos y la Semana Santa; los autonómicos y locales
los añade cada despacho (tabla `festivos`) y deben contrastarse con el calendario oficial antes de fiarse de un plazo."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

AVISOS_POR_DEFECTO = (7, 3, 1)


def pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo de Meeus/Jones/Butcher para el calendario gregoriano)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def festivos_nacionales(anio: int) -> dict[date, str]:
    """Festivos nacionales de ejemplo (SIN VALIDAR): los fijos y el Viernes Santo. No incluye autonómicos ni locales."""
    fijos = {
        (1, 1): "Año Nuevo", (1, 6): "Epifanía del Señor", (5, 1): "Fiesta del Trabajo", (8, 15): "Asunción de la Virgen",
        (10, 12): "Fiesta Nacional de España", (11, 1): "Todos los Santos", (12, 6): "Día de la Constitución",
        (12, 8): "Inmaculada Concepción", (12, 25): "Navidad",
    }
    res = {date(anio, m, d): nombre for (m, d), nombre in fijos.items()}
    res[pascua(anio) - timedelta(days=2)] = "Viernes Santo"
    return res


@dataclass(frozen=True)
class Calendario:
    """Qué días cuentan para un plazo.
    - `festivos`: fechas que no son hábiles.
    - `sabado_habil` / `domingo_habil`: normalmente falsos.
    - `meses_inhabiles`: meses completos que no cuentan (p. ej. agosto en el ámbito procesal), salvo `excepciones_inhabiles`.
    - `excepciones_inhabiles`: fechas concretas que sí son hábiles aunque caigan en un mes inhábil."""
    festivos: frozenset[date] = frozenset()
    sabado_habil: bool = False
    domingo_habil: bool = False
    meses_inhabiles: frozenset[int] = frozenset()
    excepciones_inhabiles: frozenset[date] = frozenset()
    nombre: str = "general"

    def es_habil(self, d: date) -> bool:
        if d in self.festivos:
            return False
        if d.weekday() == 5 and not self.sabado_habil:
            return False
        if d.weekday() == 6 and not self.domingo_habil:
            return False
        if d.month in self.meses_inhabiles and d not in self.excepciones_inhabiles:
            return False
        return True


def calendario(festivos: Iterable[date] = (), *, meses_inhabiles: Iterable[int] = (), sabado_habil: bool = False, domingo_habil: bool = False,
               excepciones_inhabiles: Iterable[date] = (), nombre: str = "general") -> Calendario:
    return Calendario(frozenset(festivos), sabado_habil, domingo_habil, frozenset(meses_inhabiles), frozenset(excepciones_inhabiles), nombre)


def calendario_general(anios: Iterable[int], festivos_extra: Iterable[date] = ()) -> Calendario:
    """Calendario por defecto (gestoría, inmobiliaria): lunes a viernes, sin los festivos nacionales de ejemplo ni los que añada el despacho."""
    fest: set[date] = set(festivos_extra)
    for a in anios:
        fest |= set(festivos_nacionales(a))
    return calendario(fest, nombre="general")


def calendario_procesal(anios: Iterable[int], festivos_extra: Iterable[date] = ()) -> Calendario:
    """Calendario procesal de ejemplo (SIN VALIDAR): agosto inhábil. Las excepciones por tipo de procedimiento no están modeladas: hay que
    añadirlas a mano (`excepciones_inhabiles`) y comprobar cada plazo con la normativa vigente."""
    fest: set[date] = set(festivos_extra)
    for a in anios:
        fest |= set(festivos_nacionales(a))
    return calendario(fest, meses_inhabiles=(8,), nombre="procesal")


def siguiente_habil(d: date, cal: Calendario) -> date:
    """El propio día si es hábil; si no, el siguiente que lo sea (es lo que pasa con un plazo que vence en inhábil)."""
    while not cal.es_habil(d):
        d += timedelta(days=1)
    return d


def anterior_habil(d: date, cal: Calendario) -> date:
    while not cal.es_habil(d):
        d -= timedelta(days=1)
    return d


def sumar_dias_habiles(inicio: date, n: int, cal: Calendario) -> date:
    """`n` días hábiles después de `inicio` (el día de inicio no cuenta). n = 0 devuelve el primer día hábil desde `inicio`; n < 0 cuenta hacia atrás."""
    if n == 0:
        return siguiente_habil(inicio, cal)
    paso = 1 if n > 0 else -1
    restan, d = abs(n), inicio
    while restan:
        d += timedelta(days=paso)
        if cal.es_habil(d):
            restan -= 1
    return d


def dias_habiles_entre(desde: date, hasta: date, cal: Calendario) -> int:
    """Días hábiles que hay entre dos fechas, sin contar `desde` y contando `hasta` (negativo si `hasta` es anterior)."""
    if desde == hasta:
        return 0
    signo = 1 if hasta > desde else -1
    a, b = (desde, hasta) if signo == 1 else (hasta, desde)
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if cal.es_habil(d):
            n += 1
    return signo * n


def vencimiento(inicio: date, plazo: int, unidad: str, cal: Calendario, *, desplazar_si_inhabil: bool = True) -> date:
    """Fecha en que vence un plazo de `plazo` días (`unidad` = "habiles" | "naturales") o meses (`unidad` = "meses") desde `inicio`.
    Un plazo en días naturales o en meses que acaba en día inhábil se desplaza al siguiente hábil (`desplazar_si_inhabil`)."""
    if unidad == "habiles":
        return sumar_dias_habiles(inicio, plazo, cal)
    if unidad == "naturales":
        fin = inicio + timedelta(days=plazo)
    elif unidad == "meses":
        m = inicio.month - 1 + plazo
        anio, mes = inicio.year + m // 12, m % 12 + 1
        ultimo = (date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)).day
        fin = date(anio, mes, min(inicio.day, ultimo))
    else:
        raise ValueError(f"Unidad de plazo desconocida: {unidad!r} (usa habiles, naturales o meses).")
    return siguiente_habil(fin, cal) if desplazar_si_inhabil else fin


def fechas_de_aviso(limite: date, dias_antes: Iterable[int] = AVISOS_POR_DEFECTO, cal: Calendario | None = None) -> list[date]:
    """Fechas en que avisar de un plazo, de la más lejana a la más cercana. Con calendario, un aviso que cae en día inhábil se adelanta al hábil anterior
    (nadie lee el aviso un domingo). Sin repetidas y siempre anteriores o iguales al límite."""
    avisos: set[date] = set()
    for n in dias_antes:
        if n < 0:
            continue
        f = limite - timedelta(days=n)
        if cal is not None:
            f = anterior_habil(f, cal)
        if f <= limite:
            avisos.add(f)
    return sorted(avisos)


def estado_del_plazo(limite: date, hoy: date, cumplido: bool = False, dias_alerta: int = 3, cal: Calendario | None = None) -> str:
    """cumplido | vencido | hoy | proximo | en_plazo. `proximo` = faltan `dias_alerta` días hábiles o menos (naturales sin calendario)."""
    if cumplido:
        return "cumplido"
    if limite < hoy:
        return "vencido"
    if limite == hoy:
        return "hoy"
    faltan = dias_habiles_entre(hoy, limite, cal) if cal is not None else (limite - hoy).days
    return "proximo" if faltan <= dias_alerta else "en_plazo"
