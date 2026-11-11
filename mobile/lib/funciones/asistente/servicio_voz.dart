// ignore_for_file: prefer_initializing_formals -- los parámetros con nombre no pueden ser privados, así que se asignan a los campos privados a mano
import 'dart:async';

import 'package:flutter/foundation.dart';

import 'motor_voz.dart';

const Map<String, String> _bcp47PorIdioma = {'es': 'es-ES', 'ca': 'ca-ES', 'en': 'en-US', 'fr': 'fr-FR'};

/// La voz del asistente: dictar, leer las respuestas y el modo «Live» (manos libres: escucha, envía, lee la respuesta y vuelve a escuchar).
/// No sabe nada del chat; le pregunta lo que necesita con [enviando] y [hayPendiente] y le entrega lo dictado con [alTextoFinal]. Los plugins nativos
/// quedan detrás de [MotorVoz]; esta clase es la lógica de cuándo escuchar y cuándo callarse, que ya dio guerra en dispositivos reales.
class ServicioVoz extends ChangeNotifier {
  final MotorVoz _motor;
  final bool Function() _enviando;
  final bool Function() _hayPendiente;
  final void Function(String texto) _alTextoFinal;
  final Duration _pausaReescucha;
  final Duration _pausaTrasHablar;

  ServicioVoz({
    required MotorVoz motor,
    required bool Function() enviando,
    required bool Function() hayPendiente,
    required void Function(String texto) alTextoFinal,
    Duration pausaReescucha = const Duration(milliseconds: 300),
    Duration pausaTrasHablar = const Duration(milliseconds: 400),
  })  : _motor = motor,
        _enviando = enviando,
        _hayPendiente = hayPendiente,
        _alTextoFinal = alTextoFinal,
        _pausaReescucha = pausaReescucha,
        _pausaTrasHablar = pausaTrasHablar;

  bool disponible = false;
  bool escuchando = false;
  bool liveActivo = false;
  bool hablando = false;

  /// Modo voz: el micrófono en pausa.
  bool silenciado = false;

  /// Modo voz: lo último que se oyó.
  String textoVoz = '';

  String? _localeId;
  final List<String> _cola = [];
  String _buffer = '';
  bool _liberado = false;

  bool get colaVacia => _cola.isEmpty;

  @override
  void notifyListeners() {
    if (!_liberado) super.notifyListeners();
  }

  /// Arranca la voz en [idioma] (`es`, `ca`…). Puede fallar o tardar: la voz es un extra y el chat funciona igual sin ella.
  Future<void> inicializar(String idioma) async {
    final ok = await _motor.inicializar(alEstado: _alEstado, alError: _alError);
    if (_liberado || !ok) return;
    final localeId = await _motor.localeIdPara(idioma);
    await _motor.configurarLectura(_bcp47PorIdioma[idioma] ?? 'es-ES');
    if (_liberado) return;
    disponible = true;
    _localeId = localeId;
    notifyListeners();
  }

  void _alEstado(bool escuchandoAhora, bool terminado) {
    if (_liberado) return;
    escuchando = escuchandoAhora;
    notifyListeners();
    // Seguro adicional: si la sesión de escucha terminó sola (p. ej. la persona se quedó callada y saltó pauseFor) sin que el resultado mandara nada, se
    // reintenta sola en vez de quedarse muda esperando a que alguien toque el micro: así «Live» es de verdad manos libres de principio a fin.
    if (terminado && liveActivo && !_enviando() && !hablando && !_hayPendiente()) {
      Future.delayed(_pausaReescucha, empezarEscucha);
    }
  }

  void _alError() {
    if (_liberado) return;
    escuchando = false;
    notifyListeners();
  }

  // --- Leer en voz alta ----------------------------------------------------------

  void hablar(String texto) {
    texto = texto.trim();
    if (!disponible || texto.isEmpty) return;
    _cola.add(texto);
    _procesarCola();
  }

  Future<void> _procesarCola() async {
    if (hablando || _cola.isEmpty) return;
    hablando = true;
    notifyListeners();
    while (_cola.isNotEmpty) {
      final texto = _cola.removeAt(0);
      try {
        await _motor.leer(texto);
      } catch (_) {
        // Sigue con la siguiente frase aunque esta fallara.
      }
    }
    hablando = false;
    notifyListeners();
    if (_liberado || !liveActivo || _enviando()) return;
    // Pequeña pausa antes de volver a escuchar: en iOS, pasar la sesión de audio de «reproducción» (TTS) a «grabación» (STT) sin dar tiempo a que se libere
    // el altavoz hacía que la escucha siguiente arrancara en mal estado o no captara nada (bug real encontrado en vivo, típico de alternar TTS/STT en iOS).
    await Future.delayed(_pausaTrasHablar);
    if (!_liberado && liveActivo && !_enviando() && !hablando) empezarEscucha();
  }

  /// Trocea el texto que va llegando por frases completas (acaban en `.`, `!`, `?` o salto de línea) para empezar a leer antes de que termine el turno.
  /// El trozo final, incompleto, se queda en el búfer hasta la siguiente llamada o hasta [vaciarBufer].
  void trocearParaLeer(String fragmento) {
    _buffer += fragmento;
    final partes = _buffer.split(RegExp(r'(?<=[.!?\n])\s*'));
    if (partes.length > 1) {
      for (var i = 0; i < partes.length - 1; i++) {
        if (partes[i].trim().isNotEmpty) hablar(partes[i]);
      }
      _buffer = partes.last;
    }
  }

  void vaciarBufer() {
    if (_buffer.trim().isNotEmpty) hablar(_buffer);
    _buffer = '';
  }

  void cancelarVoz() {
    _cola.clear();
    _buffer = '';
    hablando = false;
    unawaited(_motor.pararLectura().catchError((_) {}));
    notifyListeners();
  }

  // --- Dictar --------------------------------------------------------------------

  Future<void> empezarEscucha() async {
    if (_liberado || !disponible || escuchando || _enviando() || hablando || _hayPendiente() || silenciado) return;
    try {
      // Cancela cualquier sesión de escucha anterior que no se hubiera cerrado del todo: arrancar una nueva encima de una a medio cerrar es una causa conocida
      // de que speech_to_text se quede «escuchando» sin captar nada (bug real encontrado en vivo, sobre todo al reiniciar la escucha en bucle en modo Live).
      await _motor.cancelarEscucha();
      await _motor.escuchar(
        localeId: _localeId,
        alResultado: (palabras, esFinal) {
          if (_liberado) return;
          textoVoz = palabras;
          notifyListeners();
          if (esFinal) _alTextoFinal(palabras);
        },
      );
    } catch (_) {
      // El dispositivo denegó el permiso o el reconocedor no arrancó: se deja como si no hubiera voz para este intento, sin reventar el chat.
    }
  }

  void pararEscucha() {
    if (escuchando) unawaited(_motor.pararEscucha().catchError((_) {}));
  }

  void alternarMicrofono() {
    if (escuchando) {
      pararEscucha();
    } else {
      empezarEscucha();
    }
  }

  void alternarLive() {
    liveActivo = !liveActivo;
    notifyListeners();
    if (liveActivo) {
      empezarEscucha();
    } else {
      pararEscucha();
      cancelarVoz();
    }
  }

  /// Modo voz: pausar o reanudar el micrófono sin salir del modo.
  void alternarSilencio() {
    silenciado = !silenciado;
    notifyListeners();
    if (silenciado) {
      pararEscucha();
    } else {
      empezarEscucha();
    }
  }

  @override
  void dispose() {
    if (_liberado) return;
    _liberado = true;
    unawaited(_motor.liberar().catchError((_) {}));
    super.dispose();
  }
}
