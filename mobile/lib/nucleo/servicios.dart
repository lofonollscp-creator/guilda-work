import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/cliente.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/sync_service.dart';
import '../services/theme_service.dart';
import 'sesion.dart';
import 'version.dart' as v;

/// Los servicios que ya existían (sesión, cliente antiguo, sync, push, tema,
/// idioma), agrupados para ofrecerlos por Riverpod a las pantallas actuales sin
/// tocarlas: reciben lo mismo que antes por constructor, solo que ahora lo sacan
/// de aquí el enrutador.
class Servicios {
  final SessionService sesion;
  final ApiClient api;
  final SyncService sync;
  final PushService push;
  final ThemeService tema;
  final LocaleService locale;
  const Servicios({required this.sesion, required this.api, required this.sync, required this.push, required this.tema, required this.locale});

  factory Servicios.reales() {
    final sesion = SessionService();
    final api = ApiClient(sesion);
    return Servicios(
      sesion: sesion,
      api: api,
      sync: SyncService(),
      push: PushService(api),
      tema: ThemeService()..cargar(),
      locale: LocaleService()..cargar(),
    );
  }
}

/// Se sobrescribe en `main()` con [Servicios.reales] (y en las pruebas con otros).
final serviciosProvider = Provider<Servicios>((ref) => throw UnimplementedError('serviciosProvider sin sobrescribir'));

/// Lo que el cliente v2 necesita saber en cada petición, sacado del estado vivo.
class _ContextoSesion implements ContextoApi {
  final Ref _ref;
  _ContextoSesion(this._ref);

  @override
  Future<String> servidor() => _ref.read(serviciosProvider).sesion.obtenerServidor();
  @override
  Future<String?> token() => _ref.read(serviciosProvider).sesion.obtenerToken();
  @override
  String? get despacho => _ref.read(estadoSesionProvider).despacho;
  @override
  String get idioma => _ref.read(serviciosProvider).locale.locale.languageCode;
  @override
  String get versionApp => v.versionApp;
  @override
  String get plataforma => v.plataformaApp();
  @override
  Future<void> alSesionExpirada() => _ref.read(estadoSesionProvider.notifier).sesionExpirada();
  @override
  Future<void> alRequerirActualizacion({String? urlTienda}) async =>
      _ref.read(estadoSesionProvider.notifier).requerirActualizacion(urlTienda: urlTienda);
}

/// Cliente v2 de la API. Convive con el `ApiClient` antiguo hasta que cada área migre.
final clienteApiProvider = Provider<ClienteApi>((ref) => ClienteApi(_ContextoSesion(ref)));
