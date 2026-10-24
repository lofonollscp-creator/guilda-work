/// Un despacho al que pertenece la persona.
class Despacho {
  final String id;
  final String nombre;
  final bool principal;
  const Despacho({required this.id, required this.nombre, this.principal = false});

  factory Despacho.desdeJson(Map<String, dynamic> j) => Despacho(
        id: j['id'].toString(),
        nombre: (j['nombre'] ?? j['id']).toString(),
        principal: j['principal'] == true,
      );
}

/// Qué dice el servidor sobre esta versión de la app (`app` en `/auth/me`).
class InfoApp {
  final String? versionMinima;
  final String? versionRecomendada;
  final String? urlTienda;
  const InfoApp({this.versionMinima, this.versionRecomendada, this.urlTienda});
}

/// Contexto de la sesión que ofrece `/auth/me` ampliado (API 1.5, S-02 del plan
/// de la app móvil): despachos, módulos activos, permisos y versión mínima.
///
/// Es **tolerante**: con un servidor anterior a 1.5 no llega nada de esto y
/// [Capacidades.vacia] deja la app como siempre (todo visible, un solo despacho).
class Capacidades {
  final List<Despacho> despachos;
  final Map<String, bool> modulos;
  final Map<String, bool> permisos;
  final InfoApp app;
  const Capacidades({this.despachos = const [], this.modulos = const {}, this.permisos = const {}, this.app = const InfoApp()});

  static const vacia = Capacidades();

  /// Con varios despachos se enseña el selector; con uno (o ninguno) no.
  bool get variosDespachos => despachos.length > 1;

  /// ¿Está activo el módulo? Si el servidor no informa de módulos, sí.
  bool modulo(String clave) => modulos.isEmpty || (modulos[clave] ?? false);

  bool permiso(String clave) => permisos[clave] ?? false;

  Despacho? despachoPorId(String? id) {
    for (final d in despachos) {
      if (d.id == id) return d;
    }
    return null;
  }

  /// El despacho principal, o el primero si ninguno lo marca.
  Despacho? get despachoPrincipal {
    for (final d in despachos) {
      if (d.principal) return d;
    }
    return despachos.isEmpty ? null : despachos.first;
  }

  factory Capacidades.desdeJson(Map<String, dynamic> j) {
    Map<String, bool> banderas(Object? v) =>
        v is Map ? {for (final e in v.entries) e.key.toString(): e.value == true} : const {};
    final app = j['app'];
    return Capacidades(
      despachos: [
        if (j['despachos'] is List)
          for (final d in j['despachos'] as List)
            if (d is Map) Despacho.desdeJson(Map<String, dynamic>.from(d)),
      ],
      modulos: banderas(j['modulos']),
      permisos: banderas(j['permisos']),
      app: app is Map
          ? InfoApp(
              versionMinima: app['version_minima']?.toString(),
              versionRecomendada: app['version_recomendada']?.toString(),
              urlTienda: app['url_tienda']?.toString(),
            )
          : const InfoApp(),
    );
  }
}
