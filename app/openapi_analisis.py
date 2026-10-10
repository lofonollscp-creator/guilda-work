"""Análisis estático de las vistas de `/api/v1` para derivar su contrato (campos del cuerpo, parámetros de consulta, códigos de
respuesta y qué datos devuelven) leyendo el propio código con `ast`, en vez de mantenerlo a mano en un fichero aparte que se
desincroniza. Lo que el código no dice (tipos exactos, descripciones, ejemplos) lo aporta `openapi_catalogo.py`.

Detecta, dentro de cada vista (y de los controladores que reutiliza vía `__wrapped__`):
- cuerpo JSON: `datos.get("x")`, `datos["x"]` (obligatorio), `"x" in datos`, comprensiones sobre tuplas de nombres;
- cuerpo multipart: `request.files.get/getlist("x")`, `request.form.get("x")`;
- consulta: `request.args.get("x", type=int)`, `getlist`;
- códigos de respuesta: `_ok(.., 201)`, `_err(.., 409)`, `abort(404, ..)`, y los de los ayudantes conocidos;
- si pagina (`_ok_paginado`) y si devuelve un fichero (`Response(...)`)."""
from __future__ import annotations

import ast
import inspect
import textwrap

# Campos que añaden ciertos ayudantes del módulo (se leen dentro de ellos, no en la vista).
CAMPOS_DE_AYUDANTE: dict[str, list[tuple[str, bool]]] = {
    "_campos_cliente_fiscal": [("email", False), ("pais", False), ("idioma", False), ("recordatorios_portal", False)],
    "_error_referencia": [("referencia_externa", False)],
    "_guardar_referencia": [("referencia_externa", False)],
    "_datos_plantilla": [("nombre", True), ("asunto", False), ("cuerpo", True), ("modelo", False)],
    "_validar_cuerpo_webhook": [("url", True), ("eventos", True)],
}
# Códigos HTTP que pueden salir de un ayudante.
CODIGOS_DE_AYUDANTE: dict[str, set[int]] = {
    "_exigir_tenant_api": {403}, "_con_despacho": {403}, "_exigir_gestion_webhooks": {403}, "_webhook_del_despacho_o_404": {403, 404},
    "_visible_o_404": {404}, "_tarea_visible_o_404": {404}, "_nota_o_404": {404}, "_cliente_o_404": {404}, "_vencimiento_o_404": {404},
    "_plantilla_o_404": {404}, "_trabajador_administrable": {404}, "_tenant_admin": {400, 403, 404}, "_error_referencia": {400, 409},
    "_upsert": {400}, "_sin_permiso": {403}, "_mensaje_de_usuario_o_404": {404},
}
_TIPOS_CONSULTA = {"int": "integer", "float": "number", "bool": "boolean", "str": "string"}


def _desenvolver(vista):
    """La función original, saltando los decoradores (`token_required`, `_con_despacho`...)."""
    return inspect.unwrap(vista)


def _arbol(funcion):
    try:
        fuente = textwrap.dedent(inspect.getsource(funcion))
    except (OSError, TypeError):
        return None
    arbol = ast.parse(fuente)
    return next((n for n in ast.walk(arbol) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)


def _constante_str(nodo) -> str | None:
    return nodo.value if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) else None


def _es_llamada(nodo, nombre: str) -> bool:
    return isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == nombre


def _atributos(nodo) -> tuple[str, ...]:
    """request.args.get -> ("request", "args", "get")."""
    partes = []
    while isinstance(nodo, ast.Attribute):
        partes.append(nodo.attr)
        nodo = nodo.value
    if isinstance(nodo, ast.Name):
        partes.append(nodo.id)
    return tuple(reversed(partes))


def _entero(nodo) -> int | None:
    return nodo.value if isinstance(nodo, ast.Constant) and isinstance(nodo.value, int) and not isinstance(nodo.value, bool) else None


def _resolver_nombres(nodo, entorno: dict) -> list[str]:
    """Una tupla/lista de textos constantes, o `db.ALGO` / `ALGO` que lo sea, resuelto en `entorno`."""
    if isinstance(nodo, (ast.Tuple, ast.List)):
        return [c for c in (_constante_str(e) for e in nodo.elts) if c]
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        modulo = entorno.get(nodo.value.id)
        valor = getattr(modulo, nodo.attr, None)
    elif isinstance(nodo, ast.Name):
        valor = entorno.get(nodo.id)
    else:
        return []
    return [x for x in valor if isinstance(x, str)] if isinstance(valor, (tuple, list)) else []


def _tipo_de_valor(nodo) -> dict:
    """Tipo aproximado de una expresión devuelta dentro de un literal: lo que no se puede saber queda como «cualquiera» (`{}`)."""
    if isinstance(nodo, ast.Constant):
        v = nodo.value
        if isinstance(v, bool):
            return {"type": "boolean"}
        if isinstance(v, int):
            return {"type": "integer"}
        if isinstance(v, float):
            return {"type": "number"}
        if isinstance(v, str):
            return {"type": "string"}
        return {}
    if isinstance(nodo, (ast.List, ast.Tuple, ast.Set, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        elemento = nodo.elt if hasattr(nodo, "elt") else (nodo.elts[0] if getattr(nodo, "elts", None) else None)
        return {"type": "array", "items": _tipo_de_valor(elemento) if elemento is not None else {}}
    if isinstance(nodo, ast.Dict):
        return _esquema_de_dict(nodo)
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
        if nodo.func.id in ("len", "int", "sum"):
            return {"type": "integer"}
        if nodo.func.id in ("str",):
            return {"type": "string"}
        if nodo.func.id in ("bool",):
            return {"type": "boolean"}
        if nodo.func.id in ("list", "sorted"):
            return {"type": "array", "items": {}}
        if nodo.func.id in ("_dicts", "_dict"):
            lista = nodo.func.id == "_dicts"
            for interior in ast.walk(nodo):
                if isinstance(interior, ast.Call) and isinstance(interior.func, ast.Attribute) and isinstance(interior.func.value, ast.Name) and interior.func.value.id == "db":
                    return {"x-getter": interior.func.attr, "x-lista": lista}
            return {"type": "array", "items": {"type": "object"}} if lista else {"type": "object"}
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and isinstance(nodo.func.value, ast.Name) and nodo.func.value.id == "db":
        return {"x-getter": nodo.func.attr, "x-lista": nodo.func.attr.startswith(("listar_", "mensajes_del", "dependencias", "participantes", "actividad"))}
    if isinstance(nodo, ast.Compare):
        return {"type": "boolean"}
    if isinstance(nodo, ast.IfExp):
        return _tipo_de_valor(nodo.body) or {}
    return {}


def _esquema_de_dict(nodo: ast.Dict) -> dict:
    propiedades = {}
    for clave, valor in zip(nodo.keys, nodo.values):
        nombre = _constante_str(clave) if clave is not None else None      # `**otro` (clave None) no se puede conocer
        if nombre:
            propiedades[nombre] = _tipo_de_valor(valor)
    return {"type": "object", "properties": propiedades} if propiedades else {"type": "object"}


_LLAMADAS_PURAS = {"get", "strip", "lower", "upper", "str", "int", "float", "bool", "split", "title", "isdigit", "lstrip", "rstrip"}


def _es_expresion_pura(valor) -> bool:
    """`(datos.get("x") or "").strip()` sí; `datos.get("x") or db.valor_por_defecto(...)` no: con un valor de reserva calculado, el campo no es obligatorio."""
    for n in ast.walk(valor):
        if isinstance(n, ast.Call):
            nombre = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else None)
            if nombre not in _LLAMADAS_PURAS and nombre != "_body":
                return False
    return True


def analizar(vista, hijas: dict | None = None) -> dict:
    """Contrato derivado de una vista. `hijas` = {nombre_ayudante: funcion} de otras vistas cuyos campos hereda (upserts)."""
    funcion = _desenvolver(vista)
    nodo = _arbol(funcion)
    resultado = {"cuerpo": {}, "formulario": {}, "archivos": {}, "consulta": {}, "codigos_ok": set(), "codigos_error": set(), "pagina": False,
                 "binaria": False, "llamadas": set(), "usa_cuerpo_json": False, "usa_formulario": False}
    if nodo is None:
        return resultado
    entorno = dict(getattr(funcion, "__globals__", {}))
    variables_cuerpo: set[str] = set()
    variables_campo: dict[str, str] = {}      # variable -> campo del que sale (para «if not variable: return _err»)

    def es_cuerpo(n) -> bool:
        return (isinstance(n, ast.Name) and n.id in variables_cuerpo) or _es_llamada(n, "_body")

    # 1) variables que contienen el cuerpo
    for n in ast.walk(nodo):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            valor = n.value
            if _es_llamada(valor, "_body"):
                variables_cuerpo.add(n.targets[0].id); resultado["usa_cuerpo_json"] = True
            elif isinstance(valor, ast.Call) and _atributos(valor.func) in (("request", "form", "to_dict"),):
                variables_cuerpo.add(n.targets[0].id); resultado["usa_formulario"] = True
            elif isinstance(valor, ast.IfExp):          # datos = request.form.to_dict() if multipart else _body()
                for rama in (valor.body, valor.orelse):
                    if _es_llamada(rama, "_body") or (isinstance(rama, ast.Call) and _atributos(rama.func) == ("request", "form", "to_dict")):
                        variables_cuerpo.add(n.targets[0].id)
    if any(_es_llamada(n, "_body") for n in ast.walk(nodo)):
        resultado["usa_cuerpo_json"] = True

    def campo(nombre: str, obligatorio: bool = False) -> None:
        previo = resultado["cuerpo"].get(nombre, False)
        resultado["cuerpo"][nombre] = previo or obligatorio

    # 2) campos del cuerpo
    for n in ast.walk(nodo):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and es_cuerpo(n.func.value) and n.args:
            nombre = _constante_str(n.args[0])
            if nombre:
                campo(nombre)
        elif isinstance(n, ast.Subscript) and es_cuerpo(n.value) and isinstance(n.ctx, ast.Load):
            nombre = _constante_str(n.slice)
            if nombre:
                campo(nombre, obligatorio=True)
        elif isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.In) and es_cuerpo(n.comparators[0]):
            nombre = _constante_str(n.left)
            if nombre:
                campo(nombre)
        elif isinstance(n, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
            for gen in n.generators:
                if isinstance(gen.target, ast.Name):
                    for condicion in gen.ifs:
                        if isinstance(condicion, ast.Compare) and isinstance(condicion.left, ast.Name) and condicion.left.id == gen.target.id \
                                and isinstance(condicion.ops[0], ast.In) and es_cuerpo(condicion.comparators[0]):
                            for nombre in _resolver_nombres(gen.iter, entorno):
                                campo(nombre)
        # variable = (datos.get("x") or "").strip()  ->  si luego «if not variable: return _err», x es obligatorio
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            for sub in ast.walk(n.value):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "get" and es_cuerpo(sub.func.value) and sub.args and _constante_str(sub.args[0]):
                    if _es_expresion_pura(n.value):
                        variables_campo[n.targets[0].id] = _constante_str(sub.args[0])
                    break
    for n in ast.walk(nodo):
        if isinstance(n, ast.If):
            test = n.test
            nombre_var = test.operand.id if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name) else None
            devuelve_error = any(isinstance(r, ast.Return) and isinstance(r.value, (ast.Call, ast.Tuple)) and "_err" in ast.dump(r.value) for r in n.body)
            if nombre_var in variables_campo and devuelve_error:
                resultado["cuerpo"][variables_campo[nombre_var]] = True
            elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Call) and isinstance(test.operand.func, ast.Attribute) \
                    and test.operand.func.attr == "get" and es_cuerpo(test.operand.func.value) and test.operand.args and _constante_str(test.operand.args[0]) and devuelve_error:
                resultado["cuerpo"][_constante_str(test.operand.args[0])] = True

    # 3) formulario multipart, archivos y consulta
    for n in ast.walk(nodo):
        if isinstance(n, ast.Call):
            ruta = _atributos(n.func)
            primero = _constante_str(n.args[0]) if n.args else None
            if ruta in (("request", "form", "get"), ("request", "form", "getlist")) and primero:
                resultado["formulario"][primero] = False; resultado["usa_formulario"] = True
            elif ruta in (("request", "files", "get"), ("request", "files", "getlist")) and primero:
                resultado["archivos"][primero] = ruta[-1] == "getlist"; resultado["usa_formulario"] = True
            elif ruta in (("request", "args", "get"), ("request", "args", "getlist")) and primero:
                tipo = "string"
                por_defecto = None
                for k in n.keywords:
                    if k.arg == "type" and isinstance(k.value, ast.Name):
                        tipo = _TIPOS_CONSULTA.get(k.value.id, "string")
                    if k.arg == "default" and isinstance(k.value, ast.Constant):
                        por_defecto = k.value.value
                if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and por_defecto is None:
                    por_defecto = n.args[1].value
                resultado["consulta"][primero] = {"tipo": tipo, "lista": ruta[-1] == "getlist", "defecto": por_defecto}
            elif ruta == ("request", "files", "keys") or ruta == ("request", "files", "items"):
                resultado["usa_formulario"] = True
        if isinstance(n, ast.Attribute) and _atributos(n) in (("request", "files"), ("request", "form")):
            resultado["usa_formulario"] = True

    # 4) códigos de respuesta, ayudantes y datos devueltos
    for n in ast.walk(nodo):
        if not isinstance(n, ast.Call):
            continue
        nombre = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else None)
        if nombre:
            resultado["llamadas"].add(nombre)
        if nombre == "_ok":
            estado = _entero(n.args[1]) if len(n.args) > 1 else next((_entero(k.value) for k in n.keywords if k.arg == "status"), None)
            resultado["codigos_ok"].add(estado or 200)
        elif nombre == "_ok_paginado":
            resultado["pagina"] = True; resultado["codigos_ok"].add(200)
        elif nombre == "_err":
            estado = _entero(n.args[1]) if len(n.args) > 1 else next((_entero(k.value) for k in n.keywords if k.arg == "status"), None)
            resultado["codigos_error"].add(estado or 400)
        elif nombre == "abort" and n.args and _entero(n.args[0]):
            resultado["codigos_error"].add(_entero(n.args[0]))
        elif nombre in ("Response", "_descarga", "_exportar", "make_response"):
            resultado["binaria"] = True
        if nombre in CODIGOS_DE_AYUDANTE:
            resultado["codigos_error"] |= CODIGOS_DE_AYUDANTE[nombre]
        if nombre in CAMPOS_DE_AYUDANTE:
            for c, obligatorio in CAMPOS_DE_AYUDANTE[nombre]:
                campo(c, obligatorio)
    for decorador in getattr(nodo, "decorator_list", []):
        n = decorador.func if isinstance(decorador, ast.Call) else decorador
        if isinstance(n, ast.Name) and n.id in CODIGOS_DE_AYUDANTE:
            resultado["codigos_error"] |= CODIGOS_DE_AYUDANTE[n.id]
    if not resultado["codigos_ok"]:
        resultado["codigos_ok"].add(200)
    # lo que devuelve, si es un literal (`_ok({"id": 3})`, `_ok([{...} for ...])`): el primer `_ok` con un literal con claves
    resultado["literal"] = None
    for n in ast.walk(nodo):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_ok" and n.args:
            valor = n.args[0]
            if isinstance(valor, ast.Dict) and any(k is not None for k in valor.keys):
                resultado["literal"] = _esquema_de_dict(valor); break
            if isinstance(valor, (ast.ListComp,)) and isinstance(valor.elt, ast.Dict):
                resultado["literal"] = {"type": "array", "items": _esquema_de_dict(valor.elt)}; break
            if isinstance(valor, ast.List) and valor.elts and isinstance(valor.elts[0], ast.Dict):
                resultado["literal"] = {"type": "array", "items": _esquema_de_dict(valor.elts[0])}; break
    # 5) lo que heredan los upserts (reutilizan los controladores de crear y editar)
    for hija in (hijas or {}).values():
        sub = analizar(hija)
        for nombre, obligatorio in sub["cuerpo"].items():
            campo(nombre, obligatorio and False)
        resultado["usa_cuerpo_json"] = resultado["usa_cuerpo_json"] or sub["usa_cuerpo_json"]
        resultado["codigos_error"] |= sub["codigos_error"]
    return resultado
