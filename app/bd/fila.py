"""Fila de resultado con la misma interfaz que `sqlite3.Row`.

El código de la aplicación lee `fila["columna"]`, `fila[0]`, `dict(fila)`,
`fila.keys()` y desempaqueta `a, b = fila`; PostgreSQL devuelve tuplas, así que se
envuelven. Los nombres se buscan sin distinguir mayúsculas (como `sqlite3.Row`).
"""


class Fila:
    __slots__ = ("_valores", "_indice", "_nombres")

    def __init__(self, nombres, indice, valores):
        self._nombres = nombres
        self._indice = indice
        self._valores = valores

    def __getitem__(self, clave):
        if isinstance(clave, str):
            i = self._indice.get(clave)
            if i is None:
                i = self._indice.get(clave.lower())
                if i is None:
                    raise IndexError("No item with that key")
            return self._valores[i]
        return self._valores[clave]

    def keys(self):
        return list(self._nombres)

    def __len__(self):
        return len(self._valores)

    def __iter__(self):
        return iter(self._valores)

    def __eq__(self, otra):
        if isinstance(otra, Fila):
            return self._nombres == otra._nombres and self._valores == otra._valores
        return NotImplemented

    def __hash__(self):
        return hash((self._nombres, self._valores))

    def __repr__(self):
        return "<Fila " + ", ".join(f"{n}={v!r}" for n, v in zip(self._nombres, self._valores)) + ">"


def fabrica_filas(nombres):
    """Devuelve una función `valores -> Fila` que comparte el índice de nombres entre todas las filas del resultado."""
    nombres = tuple(nombres)
    indice = {}
    for i, n in enumerate(nombres):
        indice.setdefault(n, i)
        indice.setdefault(n.lower(), i)
    return lambda valores: Fila(nombres, indice, tuple(valores))
