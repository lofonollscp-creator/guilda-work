"""`app/db.py` y `mcp_tools` están divididos por dominios (app/db_*.py, mcp_tools/herramientas_*.py) sin cambiar su comportamiento: el módulo original sigue siendo el único espacio de
nombres, y el código de cada parte lo usa como `_db.nombre` / `_mt.nombre`. Un nombre usado «a pelo» solo fallaría al ejecutarse esa función; este test lo detecta antes."""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _nombres_de_nivel_de_modulo(arbol: ast.Module) -> set[str]:
    r: set[str] = set()

    def objetivos(t):
        if isinstance(t, ast.Name):
            r.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                objetivos(e)

    def recoger(nodos):
        for n in nodos:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                r.add(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    objetivos(t)
            elif isinstance(n, ast.AnnAssign):
                objetivos(n.target)
            elif isinstance(n, ast.ImportFrom):
                r.update(a.asname or a.name for a in n.names)
            elif isinstance(n, ast.If):
                recoger(n.body); recoger(n.orelse)

    recoger(arbol.body)
    return r


def _ligados(fn) -> set[str]:
    l: set[str] = set()
    for x in ast.walk(fn):
        if isinstance(x, ast.arg):
            l.add(x.arg)
        elif isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            l.add(x.id)
        elif isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and x is not fn:
            l.add(x.name)
        elif isinstance(x, (ast.Import, ast.ImportFrom)):
            l.update((a.asname or a.name).split(".")[0] for a in x.names)
        elif isinstance(x, ast.ExceptHandler) and x.name:
            l.add(x.name)
    return l


@pytest.mark.parametrize("principal,partes", [
    (RAIZ / "app" / "db.py", sorted((RAIZ / "app").glob("db_*.py"))),
    (RAIZ / "mcp_tools" / "__init__.py", sorted((RAIZ / "mcp_tools").glob("herramientas_*.py"))),
])
def test_las_partes_usan_el_espacio_de_nombres_del_modulo_original(principal, partes):
    assert partes, "no hay módulos de dominio"
    global_principal = _nombres_de_nivel_de_modulo(ast.parse(principal.read_text(encoding="utf-8")))
    fallos = []
    for parte in partes:
        arbol = ast.parse(parte.read_text(encoding="utf-8"))
        propios = {n.name for n in arbol.body if isinstance(n, ast.FunctionDef)}
        for fn in (n for n in arbol.body if isinstance(n, ast.FunctionDef)):
            ligados = _ligados(fn)
            for x in ast.walk(fn):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id in global_principal and x.id not in ligados:
                    fallos.append(f"{parte.name}:{x.lineno} {fn.name} usa «{x.id}» sin pasar por el módulo original (usa _db.{x.id} / _mt.{x.id})")
    assert not fallos, "\n".join(fallos[:15])


def test_el_modulo_original_reexporta_todo_lo_que_se_movio():
    import mcp_tools
    from app import db
    for modulo, patron in ((db, "db_*.py"), (mcp_tools, None)):
        if patron:
            partes = sorted((RAIZ / "app").glob(patron))
        else:
            partes = sorted((RAIZ / "mcp_tools").glob("herramientas_*.py"))
        for parte in partes:
            for n in ast.parse(parte.read_text(encoding="utf-8")).body:
                if isinstance(n, ast.FunctionDef):
                    assert hasattr(modulo, n.name), f"{parte.name}: {n.name} no está reexportada por {modulo.__name__}"
                    assert getattr(modulo, n.name).__module__.endswith(parte.stem), f"{n.name} debería estar definida en {parte.stem}"
