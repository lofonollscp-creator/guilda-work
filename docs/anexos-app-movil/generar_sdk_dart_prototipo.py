"""PROTOTIPO v2 del generador del SDK Dart (modelos + operaciones) desde el OpenAPI vivo. Solo biblioteca estándar."""
import json, re, sys

spec = json.load(open(sys.argv[1]))
SALIDA_MOD, SALIDA_OPS = sys.argv[2], sys.argv[3]
sch = spec["components"]["schemas"]
RESERVADAS = set("class default new in is as do if else for var final const null true false this super switch case return try catch throw void with enum late required static extends implements import export part get set operator external factory typedef abstract assert break continue while yield await async on show hide type covariant dynamic mixin library interface sealed base".split())


def camel(n):
    p = re.split(r"[_\-\.]", n)
    r = p[0] + "".join(x[:1].upper() + x[1:] for x in p[1:])
    if r[:1].isdigit():
        r = "n" + r
    return r + "_" if r in RESERVADAS else r


def pascal(n):
    c = camel(n.rstrip("_"))
    return c[:1].upper() + c[1:]


def resolver(s):
    """Esquema con allOf fusionado."""
    if "allOf" in s:
        props, req = {}, set()
        for parte in s["allOf"]:
            if "$ref" in parte:
                sub = resolver(sch[parte["$ref"].rsplit("/", 1)[1]])
            else:
                sub = resolver(parte)
            props.update(sub.get("properties", {}))
            req |= set(sub.get("required", []))
        return {"type": "object", "properties": props, "required": sorted(req)}
    return s


ENUMS = {}  # (clase, campo) -> (NombreEnum, valores)


def tipo(v, clase, campo):
    """(tipo Dart, fromJson(%s), toJson(%s))"""
    if "$ref" in v:
        n = v["$ref"].rsplit("/", 1)[1]
        r = resolver(sch.get(n, {}))
        if r.get("type") == "object" and "properties" in r:
            return n, f"{n}.fromJson(%s as Map<String, dynamic>)", "%s.toJson()"
        if r.get("type") == "array":
            it = r.get("items", {})
            ti, fj, tj = tipo(it, clase, campo)
            return f"List<{ti}>", f"(%s as List).map((e) => {fj % 'e'}).toList()", f"%s.map((e) => {tj % 'e'}).toList()"
        return "dynamic", "%s", "%s"
    if "enum" in v and v.get("type") == "string":
        nombre = pascal(clase) + pascal(campo)
        ENUMS[(clase, campo)] = (nombre, v["enum"])
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
        ti, fj, tj = tipo(v.get("items", {}), clase, campo)
        return f"List<{ti}>", f"(%s as List).map((e) => {fj % 'e'}).toList()", f"%s.map((e) => {tj % 'e'}).toList()"
    if t == "object" or "additionalProperties" in v:
        return "Map<String, dynamic>", "Map<String, dynamic>.from(%s as Map)", "%s"
    return "dynamic", "%s", "%s"


mod = ["// GENERADO desde openapi.json. No editar a mano.", "// ignore_for_file: unnecessary_question_mark", "", "bool _aBool(Object? v) => v is bool ? v : (v is num ? v != 0 : false);", ""]
cuerpo_clases = []
gen = 0
for nombre, s0 in sorted(sch.items()):
    s = resolver(s0)
    if s.get("type") != "object" or not s.get("properties"):
        continue
    req = set(s.get("required", []))
    campos = []
    for k, v in s["properties"].items():
        t, fj, tj = tipo(v, nombre, k)
        nulo = bool(v.get("nullable")) or k not in req
        campos.append((k, camel(k), t, fj, tj, nulo))
    L = [f"class {nombre} {{"]
    L += [f"  final {t}{'?' if n else ''} {c};" for k, c, t, fj, tj, n in campos]
    L.append(f"  const {nombre}({{" + "".join(f"{'' if n else 'required '}this.{c}, " for k, c, t, fj, tj, n in campos) + "});")
    L.append(f"  factory {nombre}.fromJson(Map<String, dynamic> j) => {nombre}(")
    for k, c, t, fj, tj, n in campos:
        a = f"j['{k}']"
        L.append(f"    {c}: {a} == null ? null : {fj % a}," if n else f"    {c}: {fj % a},")
    L.append("  );")
    L.append("  Map<String, dynamic> toJson() => {")
    for k, c, t, fj, tj, n in campos:
        val = f"{c}!" if n and tj != "%s" else c
        L.append(f"    if ({c} != null) '{k}': {tj % val}," if n else f"    '{k}': {tj % val},")
    L.append("  };")
    L.append(f"  {nombre} copyWith({{" + "".join(f"{t if t=='dynamic' else t+'?'} {c}, " for k, c, t, fj, tj, n in campos) + "}) => " + f"{nombre}(" + "".join(f"{c}: {c} ?? this.{c}, " for k, c, t, fj, tj, n in campos) + ");")
    L.append("  @override bool operator ==(Object o) => o is " + nombre + " && " + (" && ".join(f"o.{c} == {c}" for k, c, t, fj, tj, n in campos) if campos else "true") + ";")
    L.append("  @override int get hashCode => Object.hashAll([" + ", ".join(c for k, c, t, fj, tj, n in campos) + "]);")
    L.append("}\n")
    cuerpo_clases += L
    gen += 1
for (clase, campo), (nombre, vals) in sorted(ENUMS.items(), key=lambda x: x[1][0]):
    ids = [camel(re.sub(r"[^a-zA-Z0-9_]", "_", str(x))) or "vacio" for x in vals]
    mod.append(f"enum {nombre} {{ " + ", ".join(f"{i}('{x}')" for i, x in zip(ids, vals)) + ", sinReconocer('');")
    mod.append(f"  final String valor; const {nombre}(this.valor);")
    mod.append(f"  static {nombre} desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => {nombre}.sinReconocer);\n}}\n")
mod += cuerpo_clases
open(SALIDA_MOD, "w").write("\n".join(mod))

# ---- operaciones ----
ops = ["// GENERADO desde openapi.json. No editar a mano.", "import 'modelos.dart';", "",
       "abstract class Transporte {", "  Future<dynamic> enviar(String metodo, String ruta, {Map<String, dynamic>? consulta, Object? cuerpo, bool multipart = false, bool binario = false});", "}", "",
       "class Operaciones {", "  final Transporte _t;", "  Operaciones(this._t);", ""]
usados, n_ops, sin_tipo = set(), 0, 0
for ruta, metodos in spec["paths"].items():
    for m, o in metodos.items():
        if m not in ("get", "post", "put", "patch", "delete"):
            continue
        nombre = camel(o["operationId"])
        base = nombre
        k = 2
        while nombre in usados:
            nombre = f"{base}{k}"; k += 1
        usados.add(nombre)
        pars = [p for p in o.get("parameters", []) if "$ref" not in p]
        path_p = [p for p in pars if p["in"] == "path"]
        query_p = [p for p in pars if p["in"] == "query"]
        def tp(p):
            t = p.get("schema", {}).get("type")
            return {"integer": "int", "number": "double", "boolean": "bool"}.get(t, "String")
        args = [f"required {tp(p)} {camel(p['name'])}" for p in path_p] + [f"{tp(p)}? {camel(p['name'])}" for p in query_p]
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
            elif "$ref" in sc and resolver(sch.get(sc["$ref"].rsplit("/", 1)[1], {})).get("properties"):
                n = sc["$ref"].rsplit("/", 1)[1]; ret, conv = n, f"{n}.fromJson(r as Map<String, dynamic>)"
            elif sc.get("type") == "array" and "$ref" in sc.get("items", {}) and resolver(sch.get(sc["items"]["$ref"].rsplit("/", 1)[1], {})).get("properties"):
                n = sc["items"]["$ref"].rsplit("/", 1)[1]; ret, conv = f"List<{n}>", f"(r as List).map((e) => {n}.fromJson(e as Map<String, dynamic>)).toList()"
            else:
                ret, conv = "dynamic", "r"; sin_tipo += 1
        ruta_dart = "'" + re.sub(r"\{([^}]+)\}", lambda mm: "$" + "{" + camel(mm.group(1)) + "}", ruta.replace("/api/v1", "")) + "'"
        cons = "{" + ", ".join(f"if ({camel(p['name'])} != null) '{p['name']}': {camel(p['name'])}" for p in query_p) + "}" if query_p else "null"
        sig = f"  Future<{ret}> {nombre}(" + ("{" + ", ".join(args) + "}" if args else "") + ") "
        llamada = f"_t.enviar('{m.upper()}', {ruta_dart}, consulta: {cons}" + (", cuerpo: cuerpo" if rb else "") + (", multipart: true" if multipart else "") + (", binario: true" if binario else "") + ")"
        if conv is None:
            ops.append(sig + f"async {{ await {llamada}; }}")
        else:
            ops.append(sig + f"async {{ final r = await {llamada}; return {conv}; }}")
        n_ops += 1
ops.append("}")
open(SALIDA_OPS, "w").write("\n".join(ops))
print(f"modelos={gen} enums={len(ENUMS)} operaciones={n_ops} respuesta_sin_tipo={sin_tipo}", file=sys.stderr)
