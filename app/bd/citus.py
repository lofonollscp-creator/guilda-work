"""Reescritura de consultas para Citus: añade la igualdad de `tenant_id` donde Citus la exige.

Citus solo reparte un join o una subconsulta correlacionada entre tablas distribuidas si van unidas también por la columna de distribución («complex joins are only
supported when all distributed tables are co-located and joined on their distribution columns»). El SQL de la aplicación es el de SQLite, que no tiene `tenant_id` en la mayoría de
esas tablas, así que la condición se añade AQUÍ, al enviar la consulta a PostgreSQL, y el código fuente no cambia. Es una condición redundante (las claves foráneas compuestas
garantizan que ambas filas son del mismo despacho): solo ayuda al planificador.

  * JOIN entre dos grupos de tablas distribuidas sin `a.tenant_id = b.tenant_id` en el ON  →  se añade al ON.
  * subconsulta correlacionada con una tabla distribuida de la consulta exterior              →  se añade a su WHERE.
  * FROM a, b (coma) sin esa igualdad                                                          →  se añade al WHERE.
  * INSERT ... SELECT hacia una tabla distribuida sin `tenant_id` en la lista de columnas      →  se añade `tenant_id` (el de la tabla de origen).

Si la consulta no se puede analizar, o no hace falta tocarla, se deja tal cual. Necesita `pglast`.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

FICHERO_MODELO = Path(__file__).resolve().parent / "tenant_modelo.json"
# Número que ocupa el lugar del despacho en las consultas con filtro de despacho; ConexionPG lo sustituye por el de la conexión.
SENTINELA = "9223372036854775001"
# Vistas que exponen `tenant_id` (esquema_pg/mt/04_vistas.sql): para el planificador cuentan como tablas distribuidas.
VISTAS_CON_TENANT = frozenset({"tareas_participantes_todos"})


@lru_cache(maxsize=1)
def _modelo() -> dict:
    return json.loads(FICHERO_MODELO.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def distribuidas() -> frozenset:
    modelo = json.loads(FICHERO_MODELO.read_text(encoding="utf-8"))
    return frozenset(t for t, v in modelo.items() if v["clase"] in ("propio", "hija", "usuario")) | VISTAS_CON_TENANT


def _nodos(n):
    """Todos los nodos del árbol (en profundidad)."""
    from pglast import ast
    if isinstance(n, ast.Node):
        yield n
        for campo in type(n).__slots__:
            yield from _nodos(getattr(n, campo, None))
    elif isinstance(n, (list, tuple)):
        for x in n:
            yield from _nodos(x)


def _colref(a: str, c: str = "tenant_id"):
    from pglast import ast
    return ast.ColumnRef(fields=(ast.String(sval=a), ast.String(sval=c)))


def _igual(a: str, b: str):
    from pglast import ast, enums
    return ast.A_Expr(kind=enums.A_Expr_Kind.AEXPR_OP, name=(ast.String(sval="="),), lexpr=_colref(a), rexpr=_colref(b))


def _y(a, b):
    from pglast import ast, enums
    return b if a is None else ast.BoolExpr(boolop=enums.BoolExprType.AND_EXPR, args=(a, b))


def _alias(rv) -> str:
    return rv.alias.aliasname if rv.alias is not None else rv.relname


def _tablas(n) -> dict:
    """alias -> tabla de los RangeVar de un árbol FROM (sin entrar en subconsultas ni en sublinks)."""
    from pglast import ast
    res = {}
    if isinstance(n, ast.RangeVar):
        res[_alias(n)] = n.relname
    elif isinstance(n, ast.JoinExpr):
        res.update(_tablas(n.larg))
        res.update(_tablas(n.rarg))
    elif isinstance(n, (list, tuple)):
        for x in n:
            res.update(_tablas(x))
    return res


def _enlaces(quals) -> set:
    """Pares {a, b} de alias unidos por `a.tenant_id = b.tenant_id` en una condición."""
    from pglast import ast
    res = set()
    for n in _nodos(quals):
        if isinstance(n, ast.A_Expr) and n.name and getattr(n.name[0], "sval", None) == "=" and isinstance(n.lexpr, ast.ColumnRef) and isinstance(n.rexpr, ast.ColumnRef):
            l, r = [getattr(x, "sval", None) for x in n.lexpr.fields], [getattr(x, "sval", None) for x in n.rexpr.fields]
            if len(l) == 2 and len(r) == 2 and l[1] == r[1] == "tenant_id":
                res.add(frozenset((l[0], r[0])))
    return res


def _referidos(quals) -> list:
    """Alias que aparecen calificados (a.col) en una condición, en orden de aparición."""
    from pglast import ast
    visto = []
    for n in _nodos(quals):
        if isinstance(n, ast.ColumnRef) and len(n.fields) == 2:
            a = getattr(n.fields[0], "sval", None)
            if a and a not in visto:
                visto.append(a)
    return visto


class _Reescritor:
    def __init__(self):
        self.cambios = 0
        self.dist = distribuidas()

    def d(self, tablas: dict) -> list:
        return [a for a, t in tablas.items() if t in self.dist]

    # --- sentencias -----------------------------------------------------------------------------------------------
    def sentencia(self, st, externos: list) -> None:
        from pglast import ast
        if isinstance(st, ast.SelectStmt):
            self.select(st, externos)
        elif isinstance(st, ast.InsertStmt):
            if st.withClause:
                for cte in st.withClause.ctes:
                    self.sentencia(cte.ctequery, externos)
            if isinstance(st.selectStmt, ast.SelectStmt) and st.selectStmt.fromClause and st.relation.relname in self.dist:
                columnas = [c.name for c in (st.cols or ())]
                origen = self.d(_tablas(st.selectStmt.fromClause))
                if "tenant_id" not in columnas and origen and columnas:
                    st.cols = tuple(st.cols) + (ast.ResTarget(name="tenant_id"),)
                    st.selectStmt.targetList = tuple(st.selectStmt.targetList) + (ast.ResTarget(val=_colref(origen[0])),)
                    self.cambios += 1
            if st.selectStmt is not None:
                self.sentencia(st.selectStmt, externos)
        elif isinstance(st, (ast.UpdateStmt, ast.DeleteStmt)):
            tablas = {_alias(st.relation): st.relation.relname}
            adicional = st.fromClause if isinstance(st, ast.UpdateStmt) else st.usingClause
            if adicional:
                tablas.update(_tablas(adicional))
                for j in _nodos(adicional):
                    if isinstance(j, ast.JoinExpr):
                        self.join(j)
            for x in (st.withClause.ctes if st.withClause else ()):
                self.sentencia(x.ctequery, externos)
            raiz = [st.targetList] if isinstance(st, ast.UpdateStmt) else []
            for x in raiz + [st.whereClause]:
                self.sublinks(x, [tablas] + externos)

    def select(self, sel, externos: list) -> None:
        from pglast import ast, enums
        if sel.op != enums.SetOperation.SETOP_NONE:
            self.select(sel.larg, externos)
            self.select(sel.rarg, externos)
            return
        for cte in (sel.withClause.ctes if sel.withClause else ()):
            self.sentencia(cte.ctequery, externos)
        tablas = _tablas(sel.fromClause)
        for elemento in sel.fromClause or ():
            for n in _nodos(elemento):
                if isinstance(n, ast.JoinExpr):
                    self.join(n)
                elif isinstance(n, ast.RangeSubselect):
                    self.sentencia(n.subquery, externos if n.lateral else [])
        # FROM a, b: las tablas distribuidas de elementos distintos deben ir unidas en el WHERE
        grupos = [self.d(_tablas(e)) for e in (sel.fromClause or ())]
        grupos = [g for g in grupos if g]
        if len(grupos) > 1:
            unidos = _enlaces(sel.whereClause)
            ref = _referidos(sel.whereClause)
            for i in range(1, len(grupos)):
                anterior = [a for g in grupos[:i] for a in g]
                if not any(frozenset((x, y)) in unidos for x in anterior for y in grupos[i]):
                    a = next((x for x in ref if x in anterior), anterior[0])
                    b = next((x for x in ref if x in grupos[i]), grupos[i][0])
                    sel.whereClause = _y(sel.whereClause, _igual(a, b))
                    self.cambios += 1
        for x in (sel.targetList, sel.whereClause, sel.havingClause):
            self.sublinks(x, [tablas] + externos)

    # --- filtro de despacho ---------------------------------------------------------------------------------------------------
    def filtrar(self, st) -> None:
        """Añade `tenant_id = <despacho>` a CADA consulta del árbol (la de más arriba, las subconsultas, las CTE, las tablas derivadas), una vez por grupo de tablas unidas: si todas las
        tablas distribuidas llevan el mismo despacho constante, Citus resuelve la sentencia entera en UN solo shard, sea cual sea su forma (OR con subconsultas, vistas con UNION…). La RLS
        ya garantiza lo mismo, pero con `current_setting()` el planificador no puede descartar shards."""
        from pglast import ast, enums
        for n in _nodos(st):
            if isinstance(n, ast.SelectStmt) and n.op == enums.SetOperation.SETOP_NONE:
                for alias in self._grupos(n.fromClause, n.whereClause):
                    n.whereClause = _y(n.whereClause, self._constante(alias))
                    self.cambios += 1
            elif isinstance(n, (ast.UpdateStmt, ast.DeleteStmt)) and n.relation.relname in self.dist:
                n.whereClause = _y(n.whereClause, self._constante(_alias(n.relation)))
                self.cambios += 1

    def _constante(self, alias: str):
        from pglast import ast
        from pglast import enums
        return ast.A_Expr(kind=enums.A_Expr_Kind.AEXPR_OP, name=(ast.String(sval="="),), lexpr=_colref(alias), rexpr=ast.A_Const(val=ast.Float(fval=SENTINELA)))

    def _grupos(self, from_clause, donde) -> list:
        """Un alias por cada grupo de tablas distribuidas unidas entre sí por tenant_id (el primero de cada grupo)."""
        from pglast import ast
        alias = []
        for e in from_clause or ():
            alias += self.d(_tablas(e))
        unidos = _enlaces(donde)
        for e in from_clause or ():
            for j in _nodos(e):
                if isinstance(j, ast.JoinExpr):
                    unidos |= _enlaces(j.quals)
        grupos: list = []
        for a in alias:
            for g in grupos:
                if any(frozenset((a, b)) in unidos for b in g):
                    g.append(a)
                    break
            else:
                grupos.append([a])
        return [g[0] for g in grupos]

    def insertar_despacho(self, st) -> list | None:
        """INSERT ... VALUES en una tabla distribuida sin `tenant_id` entre sus columnas: añade `tenant_id` con el número SENTINELA (el despacho se sustituye al ejecutar). Devuelve las
        formas de deducir el despacho cuando la conexión no tiene uno (trabajos en segundo plano): [(columna, tabla padre, clave del padre, nº de parámetro)]; None si no aplica."""
        from pglast import ast
        if not isinstance(st, ast.InsertStmt) or st.relation.relname not in self.dist or not st.cols or not isinstance(st.selectStmt, ast.SelectStmt):
            return None
        columnas = [c.name for c in st.cols]
        filas = st.selectStmt.valuesLists
        if "tenant_id" in columnas or not filas:
            return None
        vias = []
        modelo = _modelo().get(st.relation.relname)
        for v in (modelo["via"] if modelo else []):
            if v["columna"] in columnas and isinstance(filas[0][columnas.index(v["columna"])], ast.ParamRef):
                vias.append((v["columna"], v["padre"], v["clave"], filas[0][columnas.index(v["columna"])].number))
        st.cols = tuple(st.cols) + (ast.ResTarget(name="tenant_id"),)
        st.selectStmt.valuesLists = tuple(tuple(fila) + (ast.A_Const(val=ast.Float(fval=SENTINELA)),) for fila in filas)
        self.cambios += 1
        return vias

    # --- joins ---------------------------------------------------------------------------------------------------------------
    def join(self, j) -> None:
        izq, der = self.d(_tablas(j.larg)), self.d(_tablas(j.rarg))
        if not izq or not der or j.quals is None or j.usingClause or j.isNatural:
            return
        unidos = _enlaces(j.quals)
        if any(frozenset((a, b)) in unidos for a in izq for b in der):
            return
        ref = _referidos(j.quals)
        a = next((x for x in ref if x in izq), izq[0])
        b = next((x for x in ref if x in der), der[0])
        j.quals = _y(j.quals, _igual(a, b))
        self.cambios += 1

    # --- subconsultas correlacionadas ---------------------------------------------------------------------------------------
    def sublinks(self, raiz, ambitos: list) -> None:
        """Procesa las subconsultas (sublinks) que cuelgan de `raiz`; `ambitos` = alias->tabla de la consulta exterior y de las que la rodean, la más cercana primero."""
        from pglast import ast
        if raiz is None:
            return
        pendientes = [raiz]
        while pendientes:
            n = pendientes.pop()
            if isinstance(n, ast.SubLink):
                if n.testexpr is not None:
                    pendientes.append(n.testexpr)
                self.subconsulta(n.subselect, ambitos, self.alias_de_la_prueba(n, ambitos))
                continue
            if isinstance(n, ast.Node):
                pendientes.extend(getattr(n, c, None) for c in type(n).__slots__)
            elif isinstance(n, (list, tuple)):
                pendientes.extend(n)

    def alias_de_la_prueba(self, sublink, ambitos: list):
        """`x IN (SELECT ...)`: la tabla exterior a la que pertenece `x` (calificada, o la única distribuida de la consulta exterior); None si no se puede saber."""
        from pglast import enums
        if sublink.testexpr is None or sublink.subLinkType not in (enums.SubLinkType.ANY_SUBLINK, enums.SubLinkType.ALL_SUBLINK) or not ambitos:
            return None
        exteriores = {a: t for ambito in reversed(ambitos) for a, t in ambito.items() if t in self.dist}
        calificadas = [a for a in _referidos(sublink.testexpr) if a in exteriores]
        if calificadas:
            return calificadas[0]
        cercano = [a for a, t in ambitos[0].items() if t in self.dist]
        return cercano[0] if len(cercano) == 1 else None

    def subconsulta(self, sub, ambitos: list, alias_prueba=None) -> None:
        from pglast import ast, enums
        if not isinstance(sub, ast.SelectStmt):
            return
        self.select(sub, ambitos)
        if sub.op != enums.SetOperation.SETOP_NONE:
            return
        propias = self.d(_tablas(sub.fromClause))
        exteriores = {a: t for ambito in reversed(ambitos) for a, t in ambito.items() if t in self.dist}          # los más cercanos ganan
        if not propias or not exteriores:
            return
        ref = [a for a in _referidos([sub.whereClause, sub.targetList, sub.havingClause]) if a in exteriores and a not in propias]
        if alias_prueba and alias_prueba not in propias and alias_prueba not in ref:
            ref.append(alias_prueba)
        if not ref:
            return                                                                                                  # no está correlacionada con una tabla distribuida
        unidos = _enlaces(sub.whereClause)
        for j in _nodos(sub.fromClause):
            if isinstance(j, ast.JoinExpr):
                unidos |= _enlaces(j.quals)
        for p in propias:
            if not any(frozenset((p, o)) in unidos for o in ref):
                sub.whereClause = _y(sub.whereClause, _igual(p, ref[0]))
                self.cambios += 1


def reescribir(sql: str, con_filtro: bool = False) -> str | None:
    """`sql` (con marcadores `$1`, `$2`…) con las igualdades de tenant_id que Citus necesita, o None si no hace falta tocarla o no se puede analizar. Con `con_filtro`, además el filtro de
    despacho (`tenant_id = SENTINELA`) en la consulta de más arriba."""
    try:
        from pglast import parse_sql
        from pglast.stream import RawStream
        arbol = parse_sql(sql)
        r = _Reescritor()
        for raw in arbol:
            r.sentencia(raw.stmt, [])
            if con_filtro:
                r.filtrar(raw.stmt)
        return RawStream()(arbol) if r.cambios else None
    except Exception:                                                                                               # noqa: BLE001 -- sin pglast o con SQL que no es de PostgreSQL: se deja como está
        return None


_MARCA = re.compile(r"\?|:[A-Za-z_]\w*")


def reescribir_sqlite(sql: str) -> str | None:
    return _reescribir_sqlite(sql, False)


def reescribir_sqlite_con_despacho(sql: str) -> str | None:
    """Como `reescribir_sqlite` pero con el filtro de despacho (el número SENTINELA marca dónde va el de la conexión)."""
    return _reescribir_sqlite(sql, True)


@lru_cache(maxsize=8192)
def _reescribir_sqlite(sql: str, con_filtro: bool) -> str | None:
    """Igual que `reescribir`, pero sobre el SQL de la aplicación (con `?` o `:nombre`): los marcadores se ven como `$n` mientras se analiza y se restituyen después."""
    marcas: list = []
    pos, partes = 0, []
    from .traduccion import _recorrer
    for trozo, es_codigo in _recorrer(sql, False):
        if es_codigo:
            def sustituir(m):
                token = m.group(0)
                if token.startswith(":") and sql[max(0, m.start() - 1):m.start()] == ":":
                    return token                                                                                    # un cast `::tipo`
                marcas.append(token)
                return f"${len(marcas)}"
            trozo = _MARCA.sub(lambda m: sustituir(m), trozo)
        partes.append(trozo)
    nuevo = reescribir("".join(partes), con_filtro)
    if nuevo is None:
        return None
    if len(re.findall(r"\$\d+", nuevo)) != len(marcas):
        return None
    return re.sub(r"\$(\d+)", lambda m: marcas[int(m.group(1)) - 1], nuevo)


@lru_cache(maxsize=4096)
def reescribir_insert(sql: str):
    """Para un INSERT ... VALUES de la aplicación (con `?`): (SQL con `tenant_id` = SENTINELA, formas de deducir el despacho) o None si no aplica."""
    try:
        from pglast import parse_sql
        from pglast.stream import RawStream
        from .traduccion import _recorrer
        marcas: list = []
        partes = []
        for trozo, es_codigo in _recorrer(sql, False):
            if es_codigo:
                if re.search(r"(?<![:\w]):[A-Za-z_]\w*", trozo):
                    return None                                                                                 # parámetros con nombre: no se reescribe
                trozo = re.sub(r"\?", lambda m: (marcas.append("?"), f"${len(marcas)}")[1], trozo)
            partes.append(trozo)
        arbol = parse_sql("".join(partes))
        r = _Reescritor()
        vias = r.insertar_despacho(arbol[0].stmt) if len(arbol) == 1 else None
        if vias is None or not r.cambios:
            return None
        nuevo = RawStream()(arbol)
        if len(re.findall(r"\$\d+", nuevo)) != len(marcas):
            return None
        return re.sub(r"\$(\d+)", lambda m: marcas[int(m.group(1)) - 1], nuevo), tuple(vias)
    except Exception:                                                                                           # noqa: BLE001
        return None
