"""SDK de Dart (modelos + operaciones tipadas) generado del contrato OpenAPI, para la app móvil (`mobile/lib/api/generado/`).

Promovido del prototipo de `docs/anexos-app-movil/generar_sdk_dart_prototipo.py` (ver `docs/plan-app-movil.md`, §5 y ADR M1). Solo
biblioteca estándar. La salida es determinista (mismo contrato, mismos bytes) para que una prueba de deriva pueda compararla con lo
versionado. Reglas de generación del plan §5.3: enteros/decimales con `num`, booleanos tolerantes (`0/1`), nulos por `nullable` o por
no estar en `required`, enums con `sinReconocer` (un estado nuevo del servidor no rompe a una app antigua) y `allOf` fusionado.

    from app import openapi, sdk_dart
    ficheros = sdk_dart.generar(spec)        # {"modelos.g.dart": "...", "operaciones.g.dart": "..."}
"""
from __future__ import annotations

import re

CABECERA = "// GENERADO desde el OpenAPI de la API (app/sdk_dart.py, scripts/generar_sdk_dart.py). No editar a mano."
FICHERO_MODELOS = "modelos.g.dart"
FICHERO_OPERACIONES = "operaciones.g.dart"

_RESERVADAS = set(
    "class default new in is as do if else for var final const null true false this super switch case return try catch throw void with enum "
    "late required static extends implements import export part get set operator external factory typedef abstract assert break continue "
    "while yield await async on show hide type covariant dynamic mixin library interface sealed base".split())
_METODOS = ("get", "post", "put", "patch", "delete")


def _camel(nombre: str) -> str:
    partes = re.split(r"[_\-\.]", nombre)
    r = partes[0] + "".join(x[:1].upper() + x[1:] for x in partes[1:])
    if r[:1].isdigit():
        r = "n" + r
    return r + "_" if r in _RESERVADAS else r


def _interpolar(m: re.Match) -> str:
    """`{id}` de la ruta como interpolación de Dart: sin llaves si lo que sigue no continúa el identificador."""
    nombre = _camel(m.group(1))
    sig = m.string[m.end():m.end() + 1]
    return "${" + nombre + "}" if sig[:1].isalnum() or sig == "_" else "$" + nombre


def _pascal(nombre: str) -> str:
    c = _camel(nombre.rstrip("_"))
    return c[:1].upper() + c[1:]


class _Generador:
    def __init__(self, spec: dict):
        self.spec = spec
        self.esquemas = spec.get("components", {}).get("schemas", {})
        self.enums: dict[tuple[str, str], tuple[str, list]] = {}

    # --- esquemas ---
    def _nombre_ref(self, ref: str) -> str:
        return ref.rsplit("/", 1)[1]

    def resolver(self, esquema: dict) -> dict:
        """El esquema con `allOf` fusionado."""
        if "allOf" in esquema:
            props: dict = {}
            req: set = set()
            for parte in esquema["allOf"]:
                sub = self.resolver(self.esquemas[self._nombre_ref(parte["$ref"])] if "$ref" in parte else parte)
                props.update(sub.get("properties", {}))
                req |= set(sub.get("required", []))
            return {"type": "object", "properties": props, "required": sorted(req)}
        return esquema

    def _es_modelo(self, nombre: str) -> bool:
        r = self.resolver(self.esquemas.get(nombre, {}))
        return r.get("type") == "object" and bool(r.get("properties"))

    def tipo(self, v: dict, clase: str, campo: str) -> tuple[str, str, str]:
        """(tipo Dart, expresión fromJson con %s, expresión toJson con %s)"""
        if "$ref" in v:
            n = self._nombre_ref(v["$ref"])
            r = self.resolver(self.esquemas.get(n, {}))
            if r.get("type") == "object" and "properties" in r:
                return n, f"{n}.fromJson(%s as Map<String, dynamic>)", "%s.toJson()"
            if r.get("type") == "array":
                return self._lista(r.get("items", {}), clase, campo)
            return "dynamic", "%s", "%s"
        if "enum" in v and v.get("type") == "string":
            nombre = _pascal(clase) + _pascal(campo)
            self.enums[(clase, campo)] = (nombre, v["enum"])
            return nombre, f"{nombre}.desde(%s as String)", "%s.valor"
        t = v.get("type")
        if t == "integer":
            return "int", "(%s as num).toInt()", "%s"
        if t == "number":
            return "double", "(%s as num).toDouble()", "%s"
        if t == "boolean":
            return "bool", "_aBool(%s)", "%s"
        if t == "string":
            return "String", "%s as String", "%s"
        if t == "array":
            return self._lista(v.get("items", {}), clase, campo)
        if t == "object" or "additionalProperties" in v:
            return "Map<String, dynamic>", "Map<String, dynamic>.from(%s as Map)", "%s"
        return "dynamic", "%s", "%s"

    def _lista(self, items: dict, clase: str, campo: str) -> tuple[str, str, str]:
        ti, fj, tj = self.tipo(items, clase, campo)
        return f"List<{ti}>", f"(%s as List).map((e) => {fj % 'e'}).toList()", f"%s.map((e) => {tj % 'e'}).toList()"

    # --- modelos ---
    def modelos(self) -> tuple[str, int]:
        clases: list[str] = []
        total = 0
        for nombre, s0 in sorted(self.esquemas.items()):
            s = self.resolver(s0)
            if s.get("type") != "object" or not s.get("properties"):
                continue
            req = set(s.get("required", []))
            campos = []
            for k, v in s["properties"].items():
                t, fj, tj = self.tipo(v, nombre, k)
                campos.append((k, _camel(k), t, fj, tj, bool(v.get("nullable")) or k not in req))
            L = [f"class {nombre} {{"]
            L += [f"  final {t}{'?' if n else ''} {c};" for k, c, t, fj, tj, n in campos]
            L.append(f"  const {nombre}({{" + "".join(f"{'' if n else 'required '}this.{c}, " for k, c, t, fj, tj, n in campos) + "});")
            L.append(f"  factory {nombre}.fromJson(Map<String, dynamic> j) => {nombre}(")
            for k, c, t, fj, tj, n in campos:
                a = f"j['{k}']"
                L.append(f"    {c}: {a}," if fj == "%s" else (f"    {c}: {a} == null ? null : {fj % a}," if n else f"    {c}: {fj % a},"))
            L.append("  );")
            L.append("  Map<String, dynamic> toJson() => {")
            for k, c, t, fj, tj, n in campos:
                val = f"{c}!" if n and tj != "%s" else c
                if n and tj == "%s":
                    L.append(f"    '{k}': ?{c},")           # elemento null-aware: no entra en el mapa si es null
                else:
                    L.append(f"    if ({c} != null) '{k}': {tj % val}," if n else f"    '{k}': {tj % val},")
            L.append("  };")
            L.append(f"  {nombre} copyWith({{" + "".join(f"{t if t == 'dynamic' else t + '?'} {c}, " for k, c, t, fj, tj, n in campos)
                     + "}) => " + f"{nombre}(" + "".join(f"{c}: {c} ?? this.{c}, " for k, c, t, fj, tj, n in campos) + ");")
            L.append(f"  @override bool operator ==(Object other) => other is {nombre} && "
                     + (" && ".join(f"other.{c} == {c}" for k, c, t, fj, tj, n in campos) if campos else "true") + ";")
            L.append("  @override int get hashCode => Object.hashAll([" + ", ".join(c for k, c, t, fj, tj, n in campos) + "]);")
            L.append("}\n")
            clases += L
            total += 1
        salida = [CABECERA, "// ignore_for_file: unnecessary_question_mark", "",
                  "bool _aBool(Object? v) => v is bool ? v : (v is num ? v != 0 : false);", ""]
        for (_, _), (nombre, vals) in sorted(self.enums.items(), key=lambda x: x[1][0]):
            ids = [_camel(re.sub(r"[^a-zA-Z0-9_]", "_", str(x))) or "vacio" for x in vals]
            salida.append(f"enum {nombre} {{ " + ", ".join(f"{i}('{x}')" for i, x in zip(ids, vals)) + ", sinReconocer('');")
            salida.append(f"  final String valor; const {nombre}(this.valor);")
            salida.append(f"  static {nombre} desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => {nombre}.sinReconocer);\n}}\n")
        return "\n".join(salida + clases), total

    # --- operaciones ---
    def operaciones(self) -> tuple[str, int, int]:
        ops = [CABECERA, "import 'modelos.g.dart';", "",
               "abstract class Transporte {",
               "  Future<dynamic> enviar(String metodo, String ruta, {Map<String, dynamic>? consulta, Object? cuerpo, "
               "bool multipart = false, bool binario = false});",
               "}", "", "class Operaciones {", "  final Transporte _t;", "  Operaciones(this._t);", ""]
        usados: set[str] = set()
        n_ops = sin_tipo = 0
        for ruta, metodos in self.spec["paths"].items():
            for m, o in metodos.items():
                if m not in _METODOS:
                    continue
                nombre = base = _camel(o["operationId"])
                k = 2
                while nombre in usados:
                    nombre = f"{base}{k}"
                    k += 1
                usados.add(nombre)
                pars = [p for p in o.get("parameters", []) if "$ref" not in p]
                # El contrato no garantiza el orden de los parámetros (sale de conjuntos): el orden estable es el de la ruta / alfabético.
                path_p = sorted((p for p in pars if p["in"] == "path"), key=lambda p: ruta.find("{" + p["name"] + "}"))
                query_p = sorted((p for p in pars if p["in"] == "query"), key=lambda p: p["name"])

                def tp(p):
                    return {"integer": "int", "number": "double", "boolean": "bool"}.get(p.get("schema", {}).get("type"), "String")

                args = [f"required {tp(p)} {_camel(p['name'])}" for p in path_p] + [f"{tp(p)}? {_camel(p['name'])}" for p in query_p]
                rb = o.get("requestBody")
                multipart = bool(rb) and "multipart/form-data" in rb.get("content", {})
                if rb:
                    args.append("Map<String, dynamic>? cuerpo")
                exito = [c for c in o["responses"] if c.startswith("2")]
                cont = o["responses"][exito[0]].get("content", {}) if exito else {}
                binario = bool(cont) and "application/json" not in cont
                if binario:
                    ret, conv = "List<int>", "(r as List).cast<int>()"
                else:
                    sc = cont.get("application/json", {}).get("schema", {}).get("properties", {}).get("data")
                    if sc is None:
                        ret, conv = "void", None
                    elif "$ref" in sc and self._es_modelo(self._nombre_ref(sc["$ref"])):
                        n = self._nombre_ref(sc["$ref"])
                        ret, conv = n, f"{n}.fromJson(r as Map<String, dynamic>)"
                    elif sc.get("type") == "array" and "$ref" in sc.get("items", {}) and self._es_modelo(self._nombre_ref(sc["items"]["$ref"])):
                        n = self._nombre_ref(sc["items"]["$ref"])
                        ret, conv = f"List<{n}>", f"(r as List).map((e) => {n}.fromJson(e as Map<String, dynamic>)).toList()"
                    else:
                        ret, conv = "dynamic", "r"
                        sin_tipo += 1
                ruta_dart = "'" + re.sub(r"\{([^}]+)\}", _interpolar, ruta.replace("/api/v1", "")) + "'"
                cons = ("{" + ", ".join(f"'{p['name']}': ?{_camel(p['name'])}" for p in query_p) + "}"
                        if query_p else "null")
                sig = f"  Future<{ret}> {nombre}(" + ("{" + ", ".join(args) + "}" if args else "") + ") "
                llamada = (f"_t.enviar('{m.upper()}', {ruta_dart}, consulta: {cons}" + (", cuerpo: cuerpo" if rb else "")
                           + (", multipart: true" if multipart else "") + (", binario: true" if binario else "") + ")")
                ops.append(sig + (f"async {{ await {llamada}; }}" if conv is None else f"async {{ final r = await {llamada}; return {conv}; }}"))
                n_ops += 1
        ops.append("}")
        return "\n".join(ops), n_ops, sin_tipo


def generar(spec: dict) -> dict[str, str]:
    """{nombre de fichero: contenido} para `mobile/lib/api/generado/`."""
    g = _Generador(spec)
    modelos, _ = g.modelos()      # primero: rellena los enums que usan los modelos
    operaciones, _, _ = g.operaciones()
    return {FICHERO_MODELOS: modelos + "\n", FICHERO_OPERACIONES: operaciones + "\n"}


def resumen(spec: dict) -> dict:
    g = _Generador(spec)
    _, modelos = g.modelos()
    _, ops, sin_tipo = g.operaciones()
    return {"modelos": modelos, "enums": len(g.enums), "operaciones": ops, "respuesta_sin_tipo": sin_tipo}
