import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../diseno/componentes.dart';

import '../l10n/app_localizations.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

import '../models/models.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import '../theme/brand_colors.dart';
import '../widgets/app_button.dart';
import 'ia_ajustes_screen.dart';

const Map<String, String> _bcp47PorIdioma = {'es': 'es-ES', 'ca': 'ca-ES', 'en': 'en-US', 'fr': 'fr-FR'};

/// Chat con el Asistente IA (equivalente móvil de app/templates/ia_asistente.html
/// + app/static/ia_asistente.js). Habla con los mismos endpoints REST que ya
/// expone app/rutas_api.py (ver api_client.dart, sección "Asistente IA") --
/// comparte historial, modelo y modo autónomo con la web; la clave de
/// OpenRouter solo se gestiona desde allí (ver IaAjustesScreen).
///
/// Fase V3 del plan "eventual-herding-kitten": envía/confirma en streaming
/// (SSE) contra /ia/mensaje/stream y /ia/confirmar/stream (Fase V1), y
/// añade dictado (speech_to_text) + lectura en voz alta (flutter_tts) con
/// un modo "Live" manoslibres, mismo comportamiento que su equivalente en
/// app/static/ia_asistente.js.
class IaChatScreen extends StatefulWidget {
  final ApiClient api;
  final LocaleService locale;

  const IaChatScreen({super.key, required this.api, required this.locale});

  @override
  State<IaChatScreen> createState() => _IaChatScreenState();
}

class _IaChatScreenState extends State<IaChatScreen> {
  final _controller = TextEditingController();
  final _scroll = ScrollController();

  List<IaMensaje> _mensajes = [];
  IaPendiente? _pendiente;
  bool _cargando = true;
  bool _enviando = false;
  bool _confirmando = false;
  String? _errorCarga;
  String? _errorTurno;
  String? _textoVivo; // respuesta del asistente pintándose en directo (streaming)
  int _idLocal = -1; // ids negativos para las burbujas de usuario optimistas (nunca chocan con ids reales del servidor)

  // --- Voz ---
  late final stt.SpeechToText _speech;
  late final FlutterTts _tts;
  bool _vozDisponible = false;
  bool _escuchando = false;
  bool _liveActivo = false;
  bool _hablando = false;
  String? _localeIdVoz;
  final List<String> _colaTts = [];
  String _ttsBuffer = '';

  @override
  void initState() {
    super.initState();
    _cargarHistorial();
    _inicializarVoz().catchError((_) {}); // la voz es un extra: si el móvil no la tiene o falla al arrancar, el chat sigue
  }

  @override
  void dispose() {
    _controller.dispose();
    _scroll.dispose();
    _speech.cancel();
    _tts.stop();
    super.dispose();
  }

  Future<void> _inicializarVoz() async {
    _speech = stt.SpeechToText();
    _tts = FlutterTts();
    await _tts.awaitSpeakCompletion(true);
    // Sin esto, en iOS el TTS se quedaba mudo (bug real: "no me lee los
    // mensajes") -- flutter_tts y speech_to_text compiten por la misma
    // sesión de audio del sistema (AVAudioSession); sin decirle a iOS que
    // la categoría es "reproducir Y grabar" compartiendo instancia, la
    // sesión se quedaba en modo solo-grabación tras usar el micro (o
    // directamente flutter_tts no conseguía activar la reproducción) y
    // speak() no sonaba, aunque awaitSpeakCompletion(true) sí acababa
    // "completando" igualmente (o quedaba colgado hasta el timeout).
    if (!kIsWeb && Platform.isIOS) {
      try {
        await _tts.setSharedInstance(true);
        await _tts.setIosAudioCategory(
          IosTextToSpeechAudioCategory.playAndRecord,
          [
            IosTextToSpeechAudioCategoryOptions.allowBluetooth,
            IosTextToSpeechAudioCategoryOptions.defaultToSpeaker,
            IosTextToSpeechAudioCategoryOptions.mixWithOthers,
          ],
          IosTextToSpeechAudioMode.defaultMode,
        );
      } catch (_) {
        // Si esto falla no hay nada mejor que hacer que seguir con la
        // configuración por defecto -- no bloquea el resto de la voz.
      }
    }
    bool disponible = false;
    try {
      disponible = await _speech.initialize(
        onStatus: (estado) {
          if (!mounted) return;
          setState(() => _escuchando = estado == 'listening');
          // Seguro adicional: si la sesión de escucha terminó sola (p.ej.
          // el usuario se quedó callado y saltó pauseFor) sin que
          // onResult mandara nada, se reintenta sola en vez de quedarse
          // muda esperando a que alguien toque el micro a mano -- así
          // "modo Live" es de verdad manoslibres de principio a fin.
          if (estado == stt.SpeechToText.doneStatus &&
              _liveActivo &&
              !_enviando &&
              !_hablando &&
              _pendiente == null) {
            Future.delayed(const Duration(milliseconds: 300), _empezarEscucha);
          }
        },
        onError: (_) {
          if (mounted) setState(() => _escuchando = false);
        },
      );
    } catch (_) {
      disponible = false;
    }
    if (!mounted || !disponible) return;
    final idioma = widget.locale.locale.languageCode;
    String? localeIdVoz;
    try {
      final locales = await _speech.locales();
      final coincidencia = locales.where((l) => l.localeId.toLowerCase().startsWith(idioma));
      if (coincidencia.isNotEmpty) localeIdVoz = coincidencia.first.localeId;
    } catch (_) {
      // Sin lista de locales del dispositivo: se deja que speech_to_text
      // use su idioma por defecto en vez de bloquear la función entera.
    }
    await _tts.setLanguage(_bcp47PorIdioma[idioma] ?? 'es-ES');
    if (!mounted) return;
    setState(() {
      _vozDisponible = true;
      _localeIdVoz = localeIdVoz;
    });
  }

  Future<void> _cargarHistorial() async {
    setState(() {
      _cargando = true;
      _errorCarga = null;
    });
    try {
      final mensajes = await widget.api.listarMensajesIa();
      setState(() {
        _mensajes = mensajes;
        _pendiente = _pendienteDesdeHistorial(mensajes);
      });
    } on ApiException catch (e) {
      setState(() => _errorCarga = mensajeDeError(AppLocalizations.of(context), e));
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  void _scrollAlFinal() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  // --- Envío/confirmación en streaming -------------------------------------

  Future<void> _enviarTexto([String? textoDictado]) async {
    final texto = (textoDictado ?? _controller.text).trim();
    if (texto.isEmpty || _enviando) return;
    _controller.clear();
    setState(() {
      _idLocal -= 1;
      _mensajes = [
        ..._mensajes,
        IaMensaje(id: _idLocal, rol: 'user', contenido: texto, creadoEn: DateTime.now().toIso8601String()),
      ];
    });
    _scrollAlFinal();
    await _procesarStream(widget.api.enviarMensajeIaStream(texto));
  }

  Future<void> _confirmarStream(bool aceptar) async {
    setState(() => _confirmando = true);
    try {
      await _procesarStream(widget.api.confirmarIaStream(aceptar));
    } finally {
      if (mounted) setState(() => _confirmando = false);
    }
  }

  Future<void> _procesarStream(Stream<IaEventoStream> stream) async {
    setState(() {
      _enviando = true;
      _errorTurno = null;
      _textoVivo = null;
      _pendiente = null;
    });
    _scrollAlFinal();
    try {
      await for (final evento in stream) {
        if (!mounted) return;
        switch (evento.tipo) {
          case 'delta':
            setState(() => _textoVivo = (_textoVivo ?? '') + (evento.texto ?? ''));
            _scrollAlFinal();
            if (_liveActivo) _trocearParaTts(evento.texto ?? '');
            break;
          case 'mensaje':
            if (evento.mensaje != null) {
              setState(() {
                _mensajes = [..._mensajes, evento.mensaje!];
                _textoVivo = null;
              });
              _scrollAlFinal();
            }
            break;
          case 'pendiente':
            setState(() => _pendiente = evento.pendiente);
            if (_liveActivo && evento.pendiente != null) {
              _flushTts();
              _hablar(AppLocalizations.of(context).iaEjecutarPregunta(evento.pendiente!.herramienta));
            }
            break;
          case 'error':
            setState(() => _errorTurno = evento.error);
            break;
          case 'fin':
            if (_liveActivo) _flushTts();
            break;
        }
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _errorTurno = mensajeDeError(AppLocalizations.of(context), e));
    } catch (_) {
      if (mounted) setState(() => _errorTurno = AppLocalizations.of(context).errRed);
    } finally {
      if (mounted) setState(() => _enviando = false);
      _scrollAlFinal();
      if (_liveActivo && !_hablando && _colaTts.isEmpty) _empezarEscucha();
    }
  }

  Future<void> _vaciar() async {
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(AppLocalizations.of(context).iaMenuVaciar),
        content: Text(AppLocalizations.of(context).iaVaciarConfirmar),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(AppLocalizations.of(context).comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(AppLocalizations.of(context).comunBorrar)),
        ],
      ),
    );
    if (confirmado != true) return;
    if (_liveActivo) _alPulsarLive();
    try {
      await widget.api.vaciarIa();
      setState(() {
        _mensajes = [];
        _pendiente = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  // --- Voz: TTS (lectura en voz alta) --------------------------------------

  void _hablar(String texto) {
    texto = texto.trim();
    if (!_vozDisponible || texto.isEmpty) return;
    _colaTts.add(texto);
    _procesarColaTts();
  }

  Future<void> _procesarColaTts() async {
    if (_hablando || _colaTts.isEmpty) return;
    _hablando = true;
    while (_colaTts.isNotEmpty) {
      final texto = _colaTts.removeAt(0);
      try {
        // awaitSpeakCompletion(true) hace que este await no vuelva hasta
        // que el motor de voz confirme que ha terminado -- si esa
        // confirmación no llega nunca (voz no soportada en el idioma,
        // fallo del motor, interrupción del sistema...) el await se
        // quedaba colgado para siempre y el modo Live dejaba de
        // funcionar sin ningún error visible (bug real encontrado en
        // vivo). El timeout evita que una frase problemática deje Live
        // colgado para siempre.
        await _tts.speak(texto).timeout(const Duration(seconds: 20), onTimeout: () => 1);
      } catch (_) {
        // Sigue con la siguiente frase aunque esta fallara.
      }
    }
    _hablando = false;
    if (!mounted || !_liveActivo || _enviando) return;
    // Pequeña pausa antes de volver a escuchar: en iOS, pasar la sesión de
    // audio de "reproducción" (TTS) a "grabación" (STT) sin dar tiempo a
    // que se libere el altavoz hacía que la escucha siguiente arrancara
    // en mal estado o directamente no captara nada (bug real encontrado
    // en vivo, típico de alternar TTS/STT en iOS).
    await Future.delayed(const Duration(milliseconds: 400));
    if (mounted && _liveActivo && !_enviando && !_hablando) _empezarEscucha();
  }

  // Trocea el texto que va llegando por frases completas (acaban en
  // ./!/?/salto de línea) para poder empezar a leer antes de que termine
  // todo el turno -- el trozo final, incompleto, se queda en _ttsBuffer
  // hasta la siguiente llamada o hasta _flushTts().
  void _trocearParaTts(String fragmento) {
    _ttsBuffer += fragmento;
    final partes = _ttsBuffer.split(RegExp(r'(?<=[.!?\n])\s*'));
    if (partes.length > 1) {
      for (var i = 0; i < partes.length - 1; i++) {
        if (partes[i].trim().isNotEmpty) _hablar(partes[i]);
      }
      _ttsBuffer = partes.last;
    }
  }

  void _flushTts() {
    if (_ttsBuffer.trim().isNotEmpty) _hablar(_ttsBuffer);
    _ttsBuffer = '';
  }

  void _cancelarVoz() {
    _colaTts.clear();
    _ttsBuffer = '';
    _hablando = false;
    _tts.stop();
  }

  // --- Voz: STT (dictado) ---------------------------------------------------

  Future<void> _empezarEscucha() async {
    if (!_vozDisponible || _escuchando || _enviando || _hablando || _pendiente != null) return;
    try {
      // Cancela cualquier sesión de escucha anterior que no se hubiera
      // cerrado del todo -- arrancar una nueva sesión encima de una a
      // medio cerrar es una causa conocida de que speech_to_text se quede
      // "escuchando" sin captar nada (bug real encontrado en vivo, sobre
      // todo al reiniciar la escucha en bucle en modo Live).
      await _speech.cancel();
      await _speech.listen(
        onResult: (resultado) {
          if (!resultado.finalResult) return;
          _controller.text = resultado.recognizedWords;
          if (_liveActivo && resultado.recognizedWords.trim().isNotEmpty) {
            _pararEscucha();
            _enviarTexto(resultado.recognizedWords);
          }
        },
        listenOptions: stt.SpeechListenOptions(
          localeId: _localeIdVoz,
          cancelOnError: true,
          listenMode: stt.ListenMode.confirmation,
          // Sin estos dos, la escucha podía quedarse abierta
          // indefinidamente esperando a que alguien llamara a stop() a
          // mano en vez de finalizar sola tras un silencio -- por eso "no
          // acababa de ir bien" el modo Live: se quedaba escuchando para
          // siempre y nunca llegaba a mandar el mensaje (bug real
          // encontrado en vivo).
          pauseFor: const Duration(seconds: 3),
          listenFor: const Duration(seconds: 30),
        ),
      );
    } catch (_) {
      // El dispositivo denegó el permiso o el reconocedor no arrancó --
      // se deja como si no hubiera voz disponible para este intento, sin
      // reventar el chat.
    }
  }

  void _pararEscucha() {
    if (_escuchando) _speech.stop();
  }

  void _alPulsarMic() {
    if (_escuchando) {
      _pararEscucha();
    } else {
      _empezarEscucha();
    }
  }

  void _alPulsarLive() {
    setState(() => _liveActivo = !_liveActivo);
    if (_liveActivo) {
      _empezarEscucha();
    } else {
      _pararEscucha();
      _cancelarVoz();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(AppLocalizations.of(context).dashboardAsistenteIaTooltip),
        // Antes tres iconos sueltos; ahora un menú con nombre (la acción destructiva, «Vaciar», ya no está a un toque por error).
        actions: [
          PopupMenuButton<String>(
            tooltip: AppLocalizations.of(context).menuMasOpciones,
            onSelected: (v) {
              switch (v) {
                case 'live':
                  _alPulsarLive();
                case 'ajustes':
                  Navigator.of(context).push(MaterialPageRoute(builder: (_) => IaAjustesScreen(api: widget.api)));
                case 'vaciar':
                  _vaciar();
              }
            },
            itemBuilder: (_) {
              final t = AppLocalizations.of(context);
              return [
                if (_vozDisponible) PopupMenuItem(value: 'live', child: ListTile(leading: Icon(_liveActivo ? Icons.headset_mic : Icons.headset_mic_outlined), title: Text(t.iaMenuLive), contentPadding: EdgeInsets.zero)),
                PopupMenuItem(value: 'ajustes', child: ListTile(leading: const Icon(Icons.tune), title: Text(t.iaMenuAjustes), contentPadding: EdgeInsets.zero)),
                PopupMenuItem(value: 'vaciar', enabled: _mensajes.isNotEmpty, child: ListTile(leading: const Icon(Icons.delete_outline), title: Text(t.iaMenuVaciar), contentPadding: EdgeInsets.zero)),
              ];
            },
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(child: _cuerpo(context)),
            if (_pendiente != null) _tarjetaPendiente(context),
            if (_errorTurno != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: Text(_errorTurno!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            _cajaEntrada(context),
          ],
        ),
      ),
    );
  }

  Widget _cuerpo(BuildContext context) {
    if (_cargando) return const Center(child: CircularProgressIndicator());
    if (_errorCarga != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_errorCarga!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _cargarHistorial, child: Text(AppLocalizations.of(context).estadoVacioReintentar)),
            ],
          ),
        ),
      );
    }
    final huboBurbujaViva = _textoVivo != null;
    if (_mensajes.isEmpty && !_enviando) {
      final t = AppLocalizations.of(context);
      final tema = Theme.of(context);
      return ListView(padding: const EdgeInsets.fromLTRB(16, 32, 16, 16), children: [
        Center(
          child: Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(color: tema.colorScheme.primary.withValues(alpha: 0.18), shape: BoxShape.circle),
            child: ExcludeSemantics(child: Icon(Icons.auto_awesome, size: 34, color: tema.colorScheme.onSurface)),
          ),
        ),
        const SizedBox(height: 16),
        Text(t.iaVacioTexto, textAlign: TextAlign.center, style: tema.textTheme.titleMedium),
        const SizedBox(height: 24),
        Text(t.iaSugerenciasTitulo, style: tema.textTheme.labelLarge),
        const SizedBox(height: 8),
        // Las sugerencias son tarjetas de ancho completo: un toque y se envía (no hay que saber qué se le puede pedir).
        for (final sugerencia in [t.iaSugerencia1, t.iaSugerencia2, t.iaSugerencia3, t.iaSugerencia4])
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Material(
              color: tema.colorScheme.surface,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
              clipBehavior: Clip.antiAlias,
              child: ListTile(
                leading: const Icon(Icons.lightbulb_outline),
                title: Text(sugerencia),
                trailing: const Icon(Icons.arrow_upward, size: 18),
                enabled: !(_enviando || _pendiente != null),
                onTap: () {
                  _controller.text = sugerencia;
                  _enviarTexto();
                },
              ),
            ),
          ),
      ]);
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(12),
      itemCount: _mensajes.length + (huboBurbujaViva ? 1 : (_enviando ? 1 : 0)),
      itemBuilder: (context, i) {
        if (i >= _mensajes.length) {
          return huboBurbujaViva ? _burbujaViva(context) : _burbujaPensando(context);
        }
        return _burbuja(context, _mensajes[i]);
      },
    );
  }

  /// La burbuja del asistente: una tarjeta con su icono, a la izquierda; la de quien escribe va rellena con el acento y a la derecha.
  Widget _burbujaAsistente(BuildContext context, Widget contenido) {
    final tema = Theme.of(context);
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.fromLTRB(12, 10, 14, 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.88),
        decoration: BoxDecoration(
          color: tema.colorScheme.surface,
          border: Border.all(color: tema.colorScheme.outlineVariant),
          borderRadius: const BorderRadius.only(topLeft: Radius.circular(4), topRight: Radius.circular(18), bottomLeft: Radius.circular(18), bottomRight: Radius.circular(18)),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(padding: const EdgeInsets.only(top: 2, right: 8), child: ExcludeSemantics(child: Icon(Icons.auto_awesome, size: 18, color: tema.colorScheme.onSurfaceVariant))),
          Flexible(child: contenido),
        ]),
      ),
    );
  }

  Widget _burbujaPensando(BuildContext context) {
    return _burbujaAsistente(
      context,
      Row(mainAxisSize: MainAxisSize.min, children: [
        const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
        const SizedBox(width: 10),
        Text(AppLocalizations.of(context).iaPensando, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
      ]),
    );
  }

  /// La respuesta del asistente pintándose en directo mientras llega en
  /// streaming -- texto plano (sin markdown) hasta que el evento "mensaje"
  /// la sustituya por la burbuja final ya formateada (ver _burbuja).
  Widget _burbujaViva(BuildContext context) => _burbujaAsistente(context, Text(_textoVivo ?? ''));

  Widget _burbuja(BuildContext context, IaMensaje m) {
    final tema = Theme.of(context);
    switch (m.rol) {
      case 'user':
        return Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 4),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
            decoration: BoxDecoration(
              color: tema.colorScheme.primary,
              borderRadius: const BorderRadius.only(topLeft: Radius.circular(18), topRight: Radius.circular(4), bottomLeft: Radius.circular(18), bottomRight: Radius.circular(18)),
            ),
            // El texto va con el color que toca sobre el acento elegido (negro o blanco según contraste), no con el del tema.
            child: Text(m.contenido ?? '', style: TextStyle(color: tema.colorScheme.onPrimary)),
          ),
        );
      case 'tool':
        // Lo que hizo el asistente por detrás, como una píldora discreta (con icono: un fallo no se distingue solo por el color).
        final texto = _textoMensajeTool(AppLocalizations.of(context), m);
        final fallo = (m.contenido ?? '').contains('"error"');
        return Align(
          alignment: Alignment.center,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Pildora(icono: fallo ? Icons.error_outline : Icons.build_circle_outlined, texto: texto, color: fallo ? (tema.brightness == Brightness.dark ? BrandColors.dangerTextDark : BrandColors.dangerTextLight) : null),
          ),
        );
      case 'assistant':
      default:
        if ((m.contenido ?? '').isEmpty) return const SizedBox.shrink();
        return _burbujaAsistente(context, SelectableText.rich(TextSpan(children: _spansMarkdownLite(context, m.contenido ?? ''))));
    }
  }

  Widget _tarjetaPendiente(BuildContext context) {
    final pendiente = _pendiente!;
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final aviso = tema.brightness == Brightness.dark ? BrandColors.warningDark : BrandColors.warningLight;
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      decoration: BoxDecoration(
        color: tema.colorScheme.surface,
        border: Border.all(color: aviso, width: 1.5),
        borderRadius: BorderRadius.circular(16),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            ExcludeSemantics(child: Icon(Icons.help_outline, color: aviso)),
            const SizedBox(width: 8),
            Expanded(child: Text(t.iaEjecutarPregunta(pendiente.herramienta), style: tema.textTheme.titleSmall)),
          ]),
          if (pendiente.argumentos.isNotEmpty) ...[
            const SizedBox(height: 10),
            // Lo que va a hacer, como lista de «campo: valor» (antes, un volcado en letra de máquina).
            for (final e in pendiente.argumentos.entries)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(e.key, style: tema.textTheme.labelSmall),
                  Text('${e.value}', style: tema.textTheme.bodyMedium),
                ]),
              ),
          ],
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _confirmando ? null : () => _confirmarStream(false),
                  child: const Text('No'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: AppButton(
                  texto: t.iaSiHazlo,
                  cargando: _confirmando,
                  onPressed: () => _confirmarStream(true),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _cajaEntrada(BuildContext context) {
    final bloqueado = _pendiente != null;
    final tema = Theme.of(context);
    return Container(
      decoration: BoxDecoration(color: tema.colorScheme.surface, border: Border(top: BorderSide(color: tema.colorScheme.outlineVariant))),
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
      child: Row(
        children: [
          if (_vozDisponible) ...[
            IconButton.outlined(
              icon: Icon(_escuchando ? Icons.mic : Icons.mic_none),
              tooltip: AppLocalizations.of(context).iaDictar,
              style: _escuchando ? IconButton.styleFrom(backgroundColor: tema.colorScheme.error, foregroundColor: Colors.white) : null,
              onPressed: (bloqueado || _enviando) ? null : _alPulsarMic,
            ),
            const SizedBox(width: 8),
          ],
          Expanded(
            child: TextField(
              controller: _controller,
              enabled: !bloqueado && !_enviando,
              minLines: 1,
              maxLines: 4,
              textCapitalization: TextCapitalization.sentences,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _enviarTexto(),
              decoration: InputDecoration(
                hintText: bloqueado ? AppLocalizations.of(context).iaResponderConfirmacion : AppLocalizations.of(context).iaEscribeMensaje,
                filled: true,
                fillColor: tema.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                disabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
              ),
            ),
          ),
          const SizedBox(width: 4),
          IconButton.filled(
            icon: const Icon(Icons.arrow_upward),
            tooltip: AppLocalizations.of(context).comunEnviar,
            onPressed: (bloqueado || _enviando) ? null : () => _enviarTexto(),
          ),
        ],
      ),
    );
  }
}

/// Texto compacto para un mensaje "tool" (misma lógica que textoMensajeTool
/// en app/static/ia_asistente.js): distingue error/rechazo/ejecución normal
/// leyendo el JSON crudo guardado en `contenido`.
String _textoMensajeTool(AppLocalizations t, IaMensaje m) {
  final herramienta = m.nombreHerramienta ?? 'herramienta';
  final contenido = m.contenido;
  if (contenido == null || contenido.isEmpty) return t.iaToolUso(herramienta);
  try {
    final datos = jsonDecode(contenido);
    if (datos is Map && datos['error'] != null) return t.iaToolError(herramienta, '${datos['error']}');
    if (datos is Map && datos['rechazado'] == true) return t.iaToolRechazada(herramienta);
  } catch (_) {
    // contenido no era JSON válido: se deja el texto por defecto
  }
  return t.iaToolUso(herramienta);
}

/// Reconstruye, a partir del historial completo, si hay una acción esperando
/// confirmación ahora mismo -- mismo criterio que
/// ia_asistente._tool_call_id_pendiente en el backend: el último mensaje es
/// "assistant" con tool_calls, y a alguno de esos tool_calls le falta su fila
/// "tool" de respuesta. Hace falta reconstruirlo aquí porque no hay ningún
/// endpoint REST equivalente a pendiente_actual() (solo lo usa la vista
/// server-rendered /ia/ de la web) -- así el móvil también recupera el
/// estado correcto si se cierra la app a media confirmación.
IaPendiente? _pendienteDesdeHistorial(List<IaMensaje> mensajes) {
  if (mensajes.isEmpty) return null;
  final ultimo = mensajes.last;
  if (ultimo.rol != 'assistant' || ultimo.toolCallsJson == null) return null;
  List<dynamic> toolCalls;
  try {
    toolCalls = (jsonDecode(ultimo.toolCallsJson!) as List);
  } catch (_) {
    return null;
  }
  final idsRespondidos = mensajes.where((m) => m.rol == 'tool').map((m) => m.toolCallId).toSet();
  for (final tc in toolCalls) {
    final id = tc['id'] as String;
    if (!idsRespondidos.contains(id)) {
      final funcion = tc['function'] as Map;
      Map<String, dynamic> argumentos = {};
      try {
        final crudos = funcion['arguments'] as String?;
        if (crudos != null && crudos.isNotEmpty) {
          argumentos = (jsonDecode(crudos) as Map).cast<String, dynamic>();
        }
      } catch (_) {
        // argumentos no parseables: se muestra la confirmación sin detalle
      }
      return IaPendiente(toolCallId: id, herramienta: funcion['name'] as String, argumentos: argumentos);
    }
  }
  return null;
}

/// Subconjunto de markdown ya usado por app/static/ia_asistente.js
/// (negrita, cursiva, código en línea, enlaces) traducido a TextSpans --
/// sin tablas por ahora (poco frecuentes en respuestas cortas de móvil;
/// si hiciera falta, se puede añadir un renderer de tabla como en el JS).
List<InlineSpan> _spansMarkdownLite(BuildContext context, String texto) {
  final spans = <InlineSpan>[];
  final patron = RegExp(r'(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?://[^\s)]+\))');
  var ultimo = 0;
  for (final m in patron.allMatches(texto)) {
    if (m.start > ultimo) spans.add(TextSpan(text: texto.substring(ultimo, m.start)));
    final trozo = m.group(0)!;
    if (trozo.startsWith('`')) {
      spans.add(TextSpan(
        text: trozo.substring(1, trozo.length - 1),
        style: const TextStyle(fontFamily: 'monospace', backgroundColor: Color(0x22808080)),
      ));
    } else if (trozo.startsWith('**')) {
      spans.add(TextSpan(text: trozo.substring(2, trozo.length - 2), style: const TextStyle(fontWeight: FontWeight.bold)));
    } else if (trozo.startsWith('[')) {
      final cierre = trozo.indexOf(']');
      final etiqueta = trozo.substring(1, cierre);
      spans.add(TextSpan(
        text: etiqueta,
        style: TextStyle(color: Theme.of(context).colorScheme.primary, decoration: TextDecoration.underline),
      ));
    }
    ultimo = m.end;
  }
  if (ultimo < texto.length) spans.add(TextSpan(text: texto.substring(ultimo)));
  return spans;
}
