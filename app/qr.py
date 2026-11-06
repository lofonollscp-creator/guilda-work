"""Códigos QR en SVG, sin dependencias: modo bytes, corrección de errores nivel M, versiones 1 a 10 (hasta 213 bytes: de sobra para un enlace).

Lo usa el portal para que el cliente enseñe «subir facturas desde el móvil» como un código que se escanea. Sigue ISO/IEC 18004 (patrones de búsqueda, alineación y sincronía, información de formato y de versión,
Reed-Solomon sobre GF(256) con el polinomio 0x11D, las 8 máscaras con su penalización); los tests lo decodifican con un lector de verdad."""
from __future__ import annotations

# versión: (palabras de datos por bloque en el grupo 1, nº de bloques del grupo 1, palabras por bloque del grupo 2, nº de bloques del grupo 2, palabras de corrección por bloque)  — nivel M
_BLOQUES = {
    1: (16, 1, 0, 0, 10), 2: (28, 1, 0, 0, 16), 3: (44, 1, 0, 0, 26), 4: (32, 2, 0, 0, 18), 5: (43, 2, 0, 0, 24),
    6: (27, 4, 0, 0, 16), 7: (31, 4, 0, 0, 18), 8: (38, 2, 39, 2, 22), 9: (36, 3, 37, 2, 22), 10: (43, 4, 44, 1, 26),
}
_ALINEACION = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}


class DemasiadoLargo(ValueError):
    pass


def _palabras_de_datos(v: int) -> int:
    d1, n1, d2, n2, _ = _BLOQUES[v]
    return d1 * n1 + d2 * n2


def capacidad(v: int) -> int:
    """Bytes que caben en la versión v (menos la cabecera de modo y de longitud)."""
    return (_palabras_de_datos(v) * 8 - 4 - (8 if v < 10 else 16)) // 8


# --- Reed-Solomon sobre GF(256) -----------------------------------------------------------------------------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generador(grado: int) -> list[int]:
    g = [1]
    for i in range(grado):
        siguiente = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            siguiente[j] ^= c
            siguiente[j + 1] ^= _mul(c, _EXP[i])
        g = siguiente
    return g


def _resto(datos: list[int], grado: int) -> list[int]:
    g = _generador(grado)
    resto = list(datos) + [0] * grado
    for i in range(len(datos)):
        c = resto[i]
        if c:
            for j in range(1, len(g)):
                resto[i + j] ^= _mul(g[j], c)
    return resto[len(datos):]


# --- Datos ------------------------------------------------------------------------------------------------------------------------------------------------------

def _codewords(datos: bytes, v: int) -> list[int]:
    bits: list[int] = []

    def poner(valor: int, n: int) -> None:
        bits.extend((valor >> (n - 1 - i)) & 1 for i in range(n))
    poner(0b0100, 4)
    poner(len(datos), 8 if v < 10 else 16)
    for b in datos:
        poner(b, 8)
    total = _palabras_de_datos(v) * 8
    poner(0, min(4, total - len(bits)))
    poner(0, (-len(bits)) % 8)
    palabras = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    relleno = (0xEC, 0x11)
    i = 0
    while len(palabras) < total // 8:
        palabras.append(relleno[i % 2])
        i += 1
    d1, n1, d2, n2, ec = _BLOQUES[v]
    bloques, pos = [], 0
    for n, largo in ((n1, d1), (n2, d2)):
        for _ in range(n):
            bloques.append(palabras[pos:pos + largo])
            pos += largo
    correcciones = [_resto(b, ec) for b in bloques]
    salida: list[int] = []
    for i in range(max(len(b) for b in bloques)):
        for b in bloques:
            if i < len(b):
                salida.append(b[i])
    for i in range(ec):
        for c in correcciones:
            salida.append(c[i])
    return salida


# --- Matriz -----------------------------------------------------------------------------------------------------------------------------------------------------

def _bit(valor: int, i: int) -> bool:
    return (valor >> i) & 1 == 1


class _Matriz:
    def __init__(self, v: int):
        self.v, self.n = v, 17 + 4 * v
        self.m = [[False] * self.n for _ in range(self.n)]
        self.fn = [[False] * self.n for _ in range(self.n)]
        self._patrones()

    def _poner(self, x: int, y: int, oscuro: bool) -> None:
        self.m[y][x] = oscuro
        self.fn[y][x] = True

    def _patrones(self) -> None:
        n = self.n
        for i in range(n):
            self._poner(6, i, i % 2 == 0)
            self._poner(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self._poner(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _ALINEACION[self.v]
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._poner(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self.formato(0)                                               # reserva el sitio; se reescribe con la máscara elegida
        if self.v >= 7:
            resto = self.v
            for _ in range(12):
                resto = (resto << 1) ^ ((resto >> 11) * 0x1F25)
            bits = self.v << 12 | resto
            for i in range(18):
                a, b = n - 11 + i % 3, i // 3
                self._poner(a, b, _bit(bits, i))
                self._poner(b, a, _bit(bits, i))

    def formato(self, mascara: int) -> None:
        n = self.n
        datos = (0 << 3) | mascara                                    # nivel M = 00
        resto = datos
        for _ in range(10):
            resto = (resto << 1) ^ ((resto >> 9) * 0x537)
        bits = (datos << 10 | resto) ^ 0x5412
        for i in range(6):
            self._poner(8, i, _bit(bits, i))
        self._poner(8, 7, _bit(bits, 6))
        self._poner(8, 8, _bit(bits, 7))
        self._poner(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self._poner(14 - i, 8, _bit(bits, i))
        for i in range(8):
            self._poner(n - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self._poner(8, n - 15 + i, _bit(bits, i))
        self._poner(8, n - 8, True)

    def colocar(self, palabras: list[int]) -> None:
        n, i = self.n, 0
        for derecha in range(n - 1, 0, -2):
            if derecha == 6:
                derecha = 5
            for vert in range(n):
                for j in range(2):
                    x = derecha - j
                    y = n - 1 - vert if ((derecha + 1) & 2) == 0 else vert
                    if not self.fn[y][x] and i < len(palabras) * 8:
                        self.m[y][x] = _bit(palabras[i >> 3], 7 - (i & 7))
                        i += 1

    def mascara(self, k: int) -> None:
        for y in range(self.n):
            for x in range(self.n):
                if self.fn[y][x]:
                    continue
                invertir = ((x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0, (x // 3 + y // 2) % 2 == 0,
                            x * y % 2 + x * y % 3 == 0, (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0)[k]
                if invertir:
                    self.m[y][x] = not self.m[y][x]

    def penalizacion(self) -> int:
        n, m, total = self.n, self.m, 0
        lineas = [row for row in m] + [[m[y][x] for y in range(n)] for x in range(n)]
        for linea in lineas:                                          # N1 (rachas de 5 o más) y N3 (patrón 1:1:3:1:1 con 4 claros)
            racha = 1
            for i in range(1, n):
                if linea[i] == linea[i - 1]:
                    racha += 1
                else:
                    total += racha - 2 if racha >= 5 else 0
                    racha = 1
            total += racha - 2 if racha >= 5 else 0
            texto = "".join("1" if c else "0" for c in linea)
            total += 40 * (texto.count("10111010000") + texto.count("00001011101"))
        for y in range(n - 1):                                        # N2 (bloques 2x2 del mismo color)
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    total += 3
        oscuros = sum(c for fila in m for c in fila)                  # N4 (equilibrio entre claros y oscuros)
        total += ((abs(oscuros * 20 - n * n * 10) + n * n - 1) // (n * n) - 1) * 10
        return total


def matriz(texto: str) -> list[list[bool]]:
    """La matriz de módulos (True = oscuro) del QR de `texto`, sin zona de silencio."""
    datos = texto.encode("utf-8")
    version = next((v for v in range(1, 11) if len(datos) <= capacidad(v)), None)
    if version is None:
        raise DemasiadoLargo(f"El texto no cabe en un QR (máximo {capacidad(10)} bytes).")
    palabras = _codewords(datos, version)
    mejor, mejor_pen = None, None
    for k in range(8):
        q = _Matriz(version)
        q.colocar(palabras)
        q.mascara(k)
        q.formato(k)
        pen = q.penalizacion()
        if mejor is None or pen < mejor_pen:
            mejor, mejor_pen = q, pen
    return mejor.m


def svg(texto: str, etiqueta: str = "") -> str:
    """El QR como SVG en blanco y negro (siempre, también en tema oscuro: un lector necesita contraste fijo), con zona de silencio de 4 módulos."""
    from html import escape
    m = matriz(texto)
    n, borde = len(m), 4
    trazos = []
    for y, fila in enumerate(m):
        x = 0
        while x < n:
            if fila[x]:
                fin = x
                while fin < n and fila[fin]:
                    fin += 1
                trazos.append(f"M{x + borde} {y + borde}h{fin - x}v1h-{fin - x}z")
                x = fin
            else:
                x += 1
    lado = n + 2 * borde
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}" width="{lado * 6}" height="{lado * 6}" shape-rendering="crispEdges" role="img" aria-label="{escape(etiqueta, quote=True)}">'
            f'<rect width="{lado}" height="{lado}" fill="#fff"/><path d="{"".join(trazos)}" fill="#000"/></svg>')
