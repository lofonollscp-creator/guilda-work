import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/api_client.dart';
import 'capacidades.dart';
import 'servicios.dart';
import 'version.dart';

enum FaseSesion {
  /// Comprobando si hay una sesión guardada y válida.
  arrancando,
  sinSesion,
  conSesion,
}

/// Todo lo que la app necesita saber de «quién soy y dónde estoy».
class EstadoSesion {
  final FaseSesion fase;
  final Usuario? usuario;
  final Capacidades capacidades;

  /// Despacho activo (`X-Despacho`). null si solo hay uno o el servidor no informa.
  final String? despacho;

  /// El servidor ya no admite esta versión de la app (426 o `version_minima`).
  final bool actualizar;
  final String? urlTienda;

  /// El arranque no pudo completarse por falta de red (se ofrece reintentar).
  final bool sinConexion;

  const EstadoSesion({
    this.fase = FaseSesion.arrancando,
    this.usuario,
    this.capacidades = Capacidades.vacia,
    this.despacho,
    this.actualizar = false,
    this.urlTienda,
    this.sinConexion = false,
  });

  EstadoSesion copiaCon({
    FaseSesion? fase,
    Usuario? usuario,
    Capacidades? capacidades,
    String? despacho,
    bool borrarDespacho = false,
    bool? actualizar,
    String? urlTienda,
    bool? sinConexion,
  }) =>
      EstadoSesion(
        fase: fase ?? this.fase,
        usuario: usuario ?? this.usuario,
        capacidades: capacidades ?? this.capacidades,
        despacho: borrarDespacho ? null : (despacho ?? this.despacho),
        actualizar: actualizar ?? this.actualizar,
        urlTienda: urlTienda ?? this.urlTienda,
        sinConexion: sinConexion ?? this.sinConexion,
      );
}

const _claveDespacho = 'despacho_activo';

/// Sesión, despacho activo y capacidades. Es lo único que decide a qué
/// pantalla va la app (ver `rutas.dart`): sin sesión → login; con sesión → la
/// barra inferior; versión no admitida → «Actualiza la app».
class SesionControl extends Notifier<EstadoSesion> {
  @override
  EstadoSesion build() {
    Future.microtask(arrancar);
    return const EstadoSesion();
  }

  Servicios get _s => ref.read(serviciosProvider);

  /// Ver si hay token y si sigue valiendo; carga usuario y capacidades.
  Future<void> arrancar() async {
    state = state.copiaCon(fase: FaseSesion.arrancando, sinConexion: false);
    final token = await _s.sesion.obtenerToken();
    if (token == null) {
      state = state.copiaCon(fase: FaseSesion.sinSesion);
      return;
    }
    _fijarContextoAntiguo();
    try {
      await _cargarSesion(await _despachoGuardado());
    } on ApiException catch (e) {
      if (e.esDeConexion) {
        // Sin red no se pierde la sesión: se ofrece reintentar.
        state = state.copiaCon(sinConexion: true);
      } else {
        await _s.sesion.borrarToken();
        state = state.copiaCon(fase: FaseSesion.sinSesion);
      }
    } catch (_) {
      await _s.sesion.borrarToken();
      state = state.copiaCon(fase: FaseSesion.sinSesion);
    }
  }

  /// Tras login o registro (el token ya está guardado).
  Future<void> iniciada(Usuario usuario) async {
    _fijarContextoAntiguo();
    state = state.copiaCon(fase: FaseSesion.conSesion, usuario: usuario, sinConexion: false);
    try {
      await _cargarSesion(await _despachoGuardado());
    } catch (_) {
      // El usuario ya está; las capacidades se piden otra vez en el siguiente arranque.
    }
  }

  Future<void> cerrar() async {
    ref.read(clienteApiProvider).vaciarCache();
    _s.api.despacho = null;
    state = const EstadoSesion(fase: FaseSesion.sinSesion);
  }

  /// Una petición con token volvió con 401.
  Future<void> sesionExpirada() async {
    await _s.sesion.borrarToken();
    await cerrar();
  }

  void requerirActualizacion({String? urlTienda}) {
    if (!state.actualizar || (urlTienda != null && state.urlTienda == null)) {
      state = state.copiaCon(actualizar: true, urlTienda: urlTienda);
    }
  }

  /// Cambia de despacho: guarda la elección, corta lo que iba en vuelo y vacía
  /// la caché para no mezclar datos de dos despachos. El enrutador se rehace al
  /// cambiar `despacho`, con lo que todas las pantallas se recargan desde cero.
  Future<void> cambiarDespacho(String id) async {
    if (state.capacidades.despachoPorId(id) == null || id == state.despacho) return;
    final cliente = ref.read(clienteApiProvider);
    cliente.cancelarPendientes();
    cliente.vaciarCache();
    _s.api.despacho = id;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_claveDespacho, id);
    state = state.copiaCon(despacho: id);
  }

  // --- internos ---

  void _fijarContextoAntiguo() {
    _s.api
      ..versionApp = versionApp
      ..plataforma = plataformaApp()
      ..idioma = _s.locale.locale.languageCode
      ..onActualizarApp = (url) {
        requerirActualizacion(urlTienda: url);
      }
      ..onSesionExpirada = () => sesionExpirada();
  }

  Future<String?> _despachoGuardado() async => (await SharedPreferences.getInstance()).getString(_claveDespacho);

  Future<void> _cargarSesion(String? despachoGuardado) async {
    // Con el despacho guardado primero; si ya no existe, se corrige tras leer /auth/me.
    _s.api.despacho = despachoGuardado;
    final cliente = ref.read(clienteApiProvider);
    final crudo = await cliente.enviar('GET', '/auth/me') as Map<String, dynamic>;
    final cap = Capacidades.desdeJson(crudo);
    final usuario = Usuario.fromJson(crudo);
    final elegido = cap.despachoPorId(despachoGuardado)?.id ?? cap.despachoPrincipal?.id;
    _s.api.despacho = elegido;
    final min = cap.app.versionMinima;
    state = state.copiaCon(
      fase: FaseSesion.conSesion,
      usuario: usuario,
      capacidades: cap,
      despacho: elegido,
      borrarDespacho: elegido == null,
      sinConexion: false,
      actualizar: state.actualizar || (min != null && compararVersiones(versionApp, min) < 0),
      urlTienda: cap.app.urlTienda,
    );
  }
}

final estadoSesionProvider = NotifierProvider<SesionControl, EstadoSesion>(SesionControl.new);
