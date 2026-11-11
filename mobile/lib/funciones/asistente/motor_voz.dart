import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

/// Lo que el asistente necesita de la voz del móvil: dictar (reconocimiento) y leer en voz alta. Es una interfaz para que la lógica del modo voz
/// (`servicio_voz.dart`: la cola de frases, el bucle de «Live», cuándo volver a escuchar) se pruebe con un motor falso, sin plugins nativos.
abstract interface class MotorVoz {
  /// Prepara la lectura y el reconocimiento. Devuelve si el reconocimiento está disponible (permiso concedido, servicio presente).
  /// [alEstado] avisa de cada cambio del reconocedor; [alError] de un fallo suyo.
  Future<bool> inicializar({required void Function(bool escuchando, bool terminado) alEstado, required void Function() alError});

  /// El identificador del idioma del dispositivo que coincide con [idioma] (`es`, `ca`…), o null si no hay lista o no coincide.
  Future<String?> localeIdPara(String idioma);

  /// El idioma de la lectura en voz alta (`es-ES`).
  Future<void> configurarLectura(String bcp47);

  /// Empieza a escuchar. [alResultado] recibe lo reconocido hasta ahora y si es el resultado final.
  Future<void> escuchar({required String? localeId, required void Function(String palabras, bool esFinal) alResultado});

  Future<void> cancelarEscucha();
  Future<void> pararEscucha();

  /// Lee [texto] y no vuelve hasta que acabe (o hasta que se agote la espera, para que una frase problemática no deje colgado el modo Live).
  Future<void> leer(String texto);
  Future<void> pararLectura();

  /// Cierra todo. Debe poder llamarse aunque [inicializar] no se haya llamado o haya fallado.
  Future<void> liberar();
}

/// El motor real: `speech_to_text` para dictar y `flutter_tts` para leer.
class MotorVozReal implements MotorVoz {
  stt.SpeechToText? _speech;
  FlutterTts? _tts;

  @override
  Future<bool> inicializar({required void Function(bool escuchando, bool terminado) alEstado, required void Function() alError}) async {
    final speech = _speech = stt.SpeechToText();
    final tts = _tts = FlutterTts();
    await tts.awaitSpeakCompletion(true);
    // Sin esto, en iOS el TTS se quedaba mudo (bug real: «no me lee los mensajes»): flutter_tts y speech_to_text compiten por la misma sesión de audio del
    // sistema (AVAudioSession); sin decirle a iOS que la categoría es «reproducir Y grabar» compartiendo instancia, la sesión se quedaba en modo solo-grabación
    // tras usar el micro (o flutter_tts no conseguía activar la reproducción) y speak() no sonaba, aunque awaitSpeakCompletion(true) sí acababa «completando»
    // igualmente (o quedaba colgado hasta el timeout).
    if (!kIsWeb && Platform.isIOS) {
      try {
        await tts.setSharedInstance(true);
        await tts.setIosAudioCategory(
          IosTextToSpeechAudioCategory.playAndRecord,
          [
            IosTextToSpeechAudioCategoryOptions.allowBluetooth,
            IosTextToSpeechAudioCategoryOptions.defaultToSpeaker,
            IosTextToSpeechAudioCategoryOptions.mixWithOthers,
          ],
          IosTextToSpeechAudioMode.defaultMode,
        );
      } catch (_) {
        // Si esto falla no hay nada mejor que hacer que seguir con la configuración por defecto: no bloquea el resto de la voz.
      }
    }
    try {
      return await speech.initialize(
        onStatus: (estado) => alEstado(estado == 'listening', estado == stt.SpeechToText.doneStatus),
        onError: (_) => alError(),
      );
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String?> localeIdPara(String idioma) async {
    try {
      final locales = await _speech!.locales();
      final coincidencia = locales.where((l) => l.localeId.toLowerCase().startsWith(idioma));
      if (coincidencia.isNotEmpty) return coincidencia.first.localeId;
    } catch (_) {
      // Sin lista de locales del dispositivo: se deja que speech_to_text use su idioma por defecto en vez de bloquear la función entera.
    }
    return null;
  }

  @override
  Future<void> configurarLectura(String bcp47) => _tts!.setLanguage(bcp47);

  @override
  Future<void> escuchar({required String? localeId, required void Function(String palabras, bool esFinal) alResultado}) => _speech!.listen(
        onResult: (r) => alResultado(r.recognizedWords, r.finalResult),
        listenOptions: stt.SpeechListenOptions(
          localeId: localeId,
          cancelOnError: true,
          listenMode: stt.ListenMode.confirmation,
          // Sin estos dos, la escucha podía quedarse abierta indefinidamente esperando a que alguien llamara a stop() a mano en vez de finalizar sola tras un
          // silencio: por eso «no acababa de ir bien» el modo Live (se quedaba escuchando para siempre y nunca mandaba el mensaje; bug real encontrado en vivo).
          pauseFor: const Duration(seconds: 3),
          listenFor: const Duration(seconds: 30),
        ),
      );

  @override
  Future<void> cancelarEscucha() => _speech!.cancel();

  @override
  Future<void> pararEscucha() => _speech!.stop();

  @override
  Future<void> leer(String texto) async {
    // awaitSpeakCompletion(true) hace que este await no vuelva hasta que el motor de voz confirme que ha terminado; si esa confirmación no llega nunca (voz no
    // soportada en el idioma, fallo del motor, interrupción del sistema…) se quedaba colgado para siempre y el modo Live dejaba de funcionar sin ningún error
    // visible (bug real encontrado en vivo). El tiempo máximo evita que una frase problemática lo deje colgado.
    await _tts!.speak(texto).timeout(const Duration(seconds: 20), onTimeout: () => 1);
  }

  @override
  Future<void> pararLectura() => _tts!.stop();

  @override
  Future<void> liberar() async {
    // La voz es un extra: si el móvil no la tiene (o aún no arrancó), cerrar el chat no debe fallar.
    if (_speech == null) return;
    await _speech!.cancel().catchError((_) {});
    await _tts?.stop().catchError((_) {});
  }
}
