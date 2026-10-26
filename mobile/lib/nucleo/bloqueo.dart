import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:local_auth/local_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Lo que la app necesita de la biometría del móvil. Es una interfaz para poder sustituirla en las pruebas.
abstract class Biometria {
  /// ¿Tiene el móvil huella, Face ID o al menos un código de bloqueo?
  Future<bool> disponible();

  /// Pide a la persona que se identifique. `false` si cancela o falla; nunca lanza.
  Future<bool> autenticar(String motivo);
}

class BiometriaReal implements Biometria {
  final LocalAuthentication _la = LocalAuthentication();

  @override
  Future<bool> disponible() async {
    try {
      return await _la.isDeviceSupported();
    } catch (_) {
      return false;
    }
  }

  @override
  Future<bool> autenticar(String motivo) async {
    try {
      // Con el código del móvil como alternativa (no solo biometría): quien no tiene huella o cara también queda protegido.
      return await _la.authenticate(localizedReason: motivo, persistAcrossBackgrounding: true);
    } catch (_) {
      return false;
    }
  }
}

final biometriaProvider = Provider<Biometria>((ref) => BiometriaReal());

/// El reloj, sustituible en las pruebas.
final relojProvider = Provider<DateTime Function()>((ref) => DateTime.now);

class EstadoBloqueo {
  /// La persona ha activado el bloqueo (preferencia de este móvil).
  final bool activo;

  /// La app está bloqueada ahora: se enseña la pantalla de desbloqueo encima de todo.
  final bool bloqueada;

  /// La app ha perdido el foco (selector de apps, aviso del sistema): se tapa para que la captura del selector no enseñe datos.
  final bool cubierta;

  /// El móvil puede proteger (huella, Face ID o código de bloqueo).
  final bool disponible;

  /// Ya se le ha ofrecido activarlo (una sola vez; después se encuentra en Ajustes).
  final bool ofertaVista;

  /// Cuántas veces se ha entrado en la app con sesión.
  final int inicios;

  const EstadoBloqueo({this.activo = false, this.bloqueada = false, this.cubierta = false, this.disponible = false, this.ofertaVista = false, this.inicios = 0});

  EstadoBloqueo copiaCon({bool? activo, bool? bloqueada, bool? cubierta, bool? disponible, bool? ofertaVista, int? inicios}) => EstadoBloqueo(
        activo: activo ?? this.activo,
        bloqueada: bloqueada ?? this.bloqueada,
        cubierta: cubierta ?? this.cubierta,
        disponible: disponible ?? this.disponible,
        ofertaVista: ofertaVista ?? this.ofertaVista,
        inicios: inicios ?? this.inicios,
      );

  /// Conviene ofrecérselo ahora: lo puede usar, no lo tiene y ya ha entrado dos veces (no en el primer inicio de sesión).
  bool get debeOfrecer => disponible && !activo && !ofertaVista && inicios >= 2;
}

const _claveActivo = 'bloqueo_biometrico';
const _claveOferta = 'bloqueo_oferta_vista';
const _claveInicios = 'bloqueo_inicios';

/// Bloqueo opcional con la biometría del móvil (A.14 del plan de UX, 0.10 del de la app).
///
///  - Al abrir la app con sesión guardada y al volver tras más de [gracia] en segundo plano, pide desbloquear.
///  - Mientras no tiene el foco (selector de apps), una cubierta tapa los datos.
///  - Activarlo y desactivarlo exige identificarse (quien coge el móvil desbloqueado no puede quitarlo).
///  - Se puede salir de un bloqueo atascado (biometría cambiada o rota) cerrando sesión.
class BloqueoControl extends Notifier<EstadoBloqueo> {
  /// Tiempo en segundo plano que se tolera sin volver a pedir (cambiar un momento a otra app no obliga a identificarse).
  static const gracia = Duration(seconds: 30);

  DateTime? _salio;
  bool _autenticando = false;
  late final Future<void> _cargado = _cargar();

  @override
  EstadoBloqueo build() {
    _cargado.ignore();
    return const EstadoBloqueo();
  }

  Biometria get _bio => ref.read(biometriaProvider);
  DateTime _ahora() => ref.read(relojProvider)();

  Future<void> _cargar() async {
    final prefs = await SharedPreferences.getInstance();
    final disponible = await _bio.disponible();
    if (!ref.mounted) return;
    // Si el móvil dejó de tener cualquier protección, el bloqueo no puede funcionar: se apaga para no dejar a la persona fuera.
    final activo = (prefs.getBool(_claveActivo) ?? false) && disponible;
    state = state.copiaCon(activo: activo, disponible: disponible, ofertaVista: prefs.getBool(_claveOferta) ?? false, inicios: prefs.getInt(_claveInicios) ?? 0);
  }

  /// Se entra en la app con sesión. `arranqueEnFrio`: se abrió con la sesión ya guardada (hay que desbloquear); si acaba de escribir la contraseña, no.
  Future<void> alEntrarConSesion({required bool arranqueEnFrio}) async {
    await _cargado;
    final prefs = await SharedPreferences.getInstance();
    final inicios = state.inicios + 1;
    await prefs.setInt(_claveInicios, inicios);
    if (!ref.mounted) return;
    state = state.copiaCon(inicios: inicios, bloqueada: arranqueEnFrio && state.activo);
  }

  Future<void> alCerrarSesion() async {
    state = state.copiaCon(bloqueada: false, cubierta: false);
  }

  /// Cambios del ciclo de vida de la app: tapar al perder el foco, anotar cuándo salió y bloquear al volver si pasó mucho tiempo.
  void alCambiarCiclo(AppLifecycleState ciclo) {
    if (!state.activo || _autenticando) return; // la propia ventana del sistema para identificarse también quita el foco
    switch (ciclo) {
      case AppLifecycleState.inactive:
        state = state.copiaCon(cubierta: true);
      case AppLifecycleState.hidden || AppLifecycleState.paused:
        _salio ??= _ahora();
        state = state.copiaCon(cubierta: true);
      case AppLifecycleState.resumed:
        final fuera = _salio == null ? Duration.zero : _ahora().difference(_salio!);
        _salio = null;
        state = state.copiaCon(cubierta: false, bloqueada: state.bloqueada || fuera > gracia);
      case AppLifecycleState.detached:
        break;
    }
  }

  /// Pide identificarse para desbloquear. `true` si lo consigue.
  Future<bool> desbloquear(String motivo) async {
    if (_autenticando) return false;
    _autenticando = true;
    try {
      final ok = await _bio.autenticar(motivo);
      if (ok && ref.mounted) state = state.copiaCon(bloqueada: false, cubierta: false);
      return ok;
    } finally {
      _autenticando = false;
    }
  }

  /// Activa el bloqueo tras comprobar que funciona (identificándose una vez). `true` si queda activo.
  Future<bool> activar(String motivo) async {
    await _cargado;
    if (!state.disponible || _autenticando) return false;
    _autenticando = true;
    try {
      if (!await _bio.autenticar(motivo)) return false;
    } finally {
      _autenticando = false;
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_claveActivo, true);
    await prefs.setBool(_claveOferta, true);
    if (ref.mounted) state = state.copiaCon(activo: true, ofertaVista: true);
    return true;
  }

  /// Desactiva el bloqueo, previa identificación. `true` si queda desactivado.
  Future<bool> desactivar(String motivo) async {
    if (_autenticando) return false;
    _autenticando = true;
    try {
      if (!await _bio.autenticar(motivo)) return false;
    } finally {
      _autenticando = false;
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_claveActivo, false);
    if (ref.mounted) state = state.copiaCon(activo: false, bloqueada: false, cubierta: false);
    return true;
  }

  /// La persona ha visto la oferta y no la quiere: no se repite (queda en Ajustes).
  Future<void> ofertaAtendida() async {
    await _cargado;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_claveOferta, true);
    if (ref.mounted) state = state.copiaCon(ofertaVista: true);
  }
}

final bloqueoProvider = NotifierProvider<BloqueoControl, EstadoBloqueo>(BloqueoControl.new);
