// ignore_for_file: prefer_initializing_formals -- los parámetros con nombre no pueden ser privados, así que se asignan a los campos privados a mano
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../../l10n/app_localizations.dart';
import '../../models/models.dart';
import '../../services/api_client.dart';
import 'asistente_piezas.dart' show RecordarCifras;
import 'motor_voz.dart';
import 'servicio_voz.dart';

/// La conversación con el asistente: qué se ha dicho, qué está llegando, qué espera confirmación y qué hay a medias (un archivo subido, la voz).
/// No pinta nada ni conoce `BuildContext`: la pantalla (`ia_chat_screen.dart`) se suscribe, y desde la fase 2 el mismo controlador podrá vivir fuera de ella para que
/// la barra del asistente y el chat compartan conversación. Los textos traducidos y el desplazamiento los pide por las funciones que recibe.
class AsistenteControlador extends ChangeNotifier {
  final ApiClient api;

  /// Los textos traducidos, para lo poco que el controlador dice por sí mismo (la pregunta por defecto de un archivo, la frase de confirmación en voz alta).
  final AppLocalizations Function() _textos;

  /// El idioma de la voz, leído cuando arranca (puede cambiar mientras el chat está abierto).
  final String Function() _idiomaVoz;

  /// La pantalla lo usa para llevar el desplazamiento al final cuando algo nuevo se pinta.
  final VoidCallback? alAvanzar;

  /// Lo dictado y ya final: la pantalla lo copia en el campo de texto.
  final void Function(String texto)? alDictar;

  /// Se llamó a [enviar] con éxito: la pantalla vacía el campo de texto.
  final VoidCallback? alEnviar;

  late final ServicioVoz voz;

  AsistenteControlador({
    required this.api,
    required AppLocalizations Function() textos,
    required MotorVoz motor,
    required String Function() idiomaVoz,
    String? contextoIa,
    this.alAvanzar,
    this.alDictar,
    this.alEnviar,
    Duration pausaReescucha = const Duration(milliseconds: 300),
    Duration pausaTrasHablar = const Duration(milliseconds: 400),
  })  : _textos = textos,
        _idiomaVoz = idiomaVoz,
        _contextoIa = contextoIa {
    voz = ServicioVoz(
      motor: motor,
      enviando: () => _enviando,
      hayPendiente: () => _pendiente != null,
      alTextoFinal: _alDictadoFinal,
      pausaReescucha: pausaReescucha,
      pausaTrasHablar: pausaTrasHablar,
    )..addListener(notifyListeners);
  }

  // --- Estado --------------------------------------------------------------------

  List<IaMensaje> _mensajes = [];
  IaPendiente? _pendiente;
  bool _cargando = true;
  bool _enviando = false;
  bool _confirmando = false;
  Object? _errorCarga;
  Object? _errorTurno;
  IaAdjunto? _adjunto;
  bool _subiendo = false;
  bool _contextoEnviado = false;
  bool _contextoVisible = true;
  bool _detenido = false;
  bool _recordarCifras = true;
  int _inicioTurno = 0;
  List<IaConversacion> _conversaciones = [];
  String? _textoVivo;
  int _idLocal = -1; // ids negativos para los mensajes optimistas: nunca chocan con los reales del servidor
  String? _contextoIa;
  bool _liberado = false;
  Future<void> _turno = Future.value();
  int _idTurno = 0; // cada turno lleva su número: un turno parado no puede tocar el que viene después

  List<IaMensaje> get mensajes => _mensajes;

  /// La acción que espera un «sí» o un «no».
  IaPendiente? get pendiente => _pendiente;
  bool get cargando => _cargando;

  /// Hay un turno en curso (la respuesta está llegando).
  bool get enviando => _enviando;
  bool get confirmando => _confirmando;

  /// Por qué no se pudo cargar el historial (`null` si fue bien): un [ApiException] u otro error.
  Object? get errorCarga => _errorCarga;

  /// Por qué falló el último turno: el texto que mandó el servidor ([String]), un [ApiException] u otro error.
  Object? get errorTurno => _errorTurno;

  /// El archivo subido que irá con el próximo mensaje.
  IaAdjunto? get adjunto => _adjunto;
  bool get subiendo => _subiendo;

  /// La respuesta del asistente pintándose en directo, antes de que llegue el mensaje definitivo.
  String? get textoVivo => _textoVivo;

  /// Desde esta posición de [mensajes] es lo que ha ido haciendo el asistente en el turno en curso.
  int get inicioTurno => _inicioTurno;
  List<IaConversacion> get conversaciones => _conversaciones;
  bool get recordarCifras => _recordarCifras;

  /// De qué elemento habla la persona (`tarea #7 «…»`), y si lo ha quitado de la píldora.
  String? get contextoIa => _contextoIa;
  bool get contextoVisible => _contextoVisible;

  /// El turno en curso, para esperarlo (las pruebas).
  Future<void> get turno => _turno;

  /// Con la conversación vacía y nada en marcha, la pantalla enseña la de inicio.
  bool get enBlanco => _mensajes.isEmpty && !_enviando;

  String get ultimaRespuesta {
    for (final m in _mensajes.reversed) {
      if (m.rol == 'assistant' && (m.contenido ?? '').isNotEmpty) return m.contenido!;
    }
    return '';
  }

  /// En el panel de la tableta, al abrir otra tarea el asistente vuelve a recibir de cuál hablas.
  set contextoIa(String? nuevo) {
    if (nuevo == _contextoIa) return;
    _contextoIa = nuevo;
    _contextoEnviado = false;
    _contextoVisible = true;
    _avisar();
  }

  void ocultarContexto() {
    _contextoVisible = false;
    _avisar();
  }

  void _avisar() {
    if (!_liberado) notifyListeners();
  }

  // --- Arranque ------------------------------------------------------------------

  /// Carga lo de antes y, si se pidió algo al abrir, lo envía. La voz arranca aparte: es un extra y si falla el chat sigue.
  Future<void> iniciar({String? consultaInicial}) async {
    unawaited(RecordarCifras.leer().then((v) {
      _recordarCifras = v;
      _avisar();
    }));
    unawaited(cargarConversaciones());
    unawaited(voz.inicializar(_idiomaVoz()).catchError((_) {}));
    await cargarHistorial();
    final consulta = consultaInicial?.trim() ?? '';
    if (!_liberado && consulta.isNotEmpty && _errorCarga == null) enviar(consulta);
  }

  Future<void> recargarRecordarCifras() async {
    final v = await RecordarCifras.leer();
    _recordarCifras = v;
    _avisar();
  }

  /// Las conversaciones anteriores, para «Continúa» (un extra: si falla, simplemente no se enseñan).
  Future<void> cargarConversaciones() async {
    try {
      final lista = await api.listarConversacionesIa();
      _conversaciones = lista;
      _avisar();
    } catch (_) {
      // sin conversaciones anteriores a la vista
    }
  }

  /// Retoma una conversación anterior. Devuelve el texto del error si falló (la pantalla lo enseña), o `null`.
  Future<String?> retomar(IaConversacion c) async {
    try {
      await api.activarConversacionIa(c.id);
      await cargarHistorial();
      unawaited(cargarConversaciones());
      return null;
    } on ApiException catch (e) {
      return e.mensaje;
    }
  }

  Future<void> cargarHistorial() async {
    _cargando = true;
    _errorCarga = null;
    _avisar();
    try {
      final mensajes = await api.listarMensajesIa();
      _mensajes = mensajes;
      _pendiente = pendienteDesdeHistorial(mensajes);
    } on ApiException catch (e) {
      _errorCarga = e;
    } finally {
      _cargando = false;
      _avisar();
    }
  }

  // --- Enviar y confirmar --------------------------------------------------------

  /// Envía [texto] al asistente (con el archivo adjunto, si lo hay, y con el contexto la primera vez). Devuelve `false` si no había nada que enviar o ya hay un envío en
  /// marcha. El turno sigue en segundo plano; [turno] permite esperarlo.
  bool enviar(String texto) {
    texto = texto.trim();
    final adjunto = _adjunto;
    // Con un archivo y sin nada escrito, se le pide lo obvio: que lo lea.
    if (texto.isEmpty && adjunto != null) texto = _textos().iaAdjuntoPregunta;
    if (texto.isEmpty || _enviando || _subiendo) return false;
    // Así lo reconoce el asistente (y la web): el archivo va nombrado en la primera línea.
    if (adjunto != null) texto = '[Adjunto #${adjunto.id}: ${adjunto.nombre}]\n$texto';
    // Con el primer mensaje va, en una línea que aquí no se pinta, de qué elemento hablas.
    final contexto = _contextoVisible ? _contextoIa : null;
    if (contexto != null && !_contextoEnviado) {
      texto = '[Contexto: $contexto]\n$texto';
      _contextoEnviado = true;
    }
    alEnviar?.call();
    _adjunto = null;
    _idLocal -= 1;
    _mensajes = [..._mensajes, IaMensaje(id: _idLocal, rol: 'user', contenido: texto, creadoEn: DateTime.now().toIso8601String())];
    _avisar();
    alAvanzar?.call();
    _turno = _procesarStream(api.enviarMensajeIaStream(texto));
    return true;
  }

  /// Responde a la acción pendiente: `true` la ejecuta, `false` la rechaza.
  Future<void> confirmar(bool aceptar) async {
    _confirmando = true;
    _avisar();
    try {
      _turno = _procesarStream(api.confirmarIaStream(aceptar));
      await _turno;
    } finally {
      _confirmando = false;
      _avisar();
    }
  }

  Future<void> _procesarStream(Stream<IaEventoStream> stream) async {
    final miTurno = ++_idTurno;
    _enviando = true;
    _detenido = false;
    _errorTurno = null;
    _textoVivo = null;
    _pendiente = null;
    _inicioTurno = _mensajes.length;
    _avisar();
    alAvanzar?.call();
    try {
      await for (final evento in stream) {
        if (_liberado) return;
        // Parado, o ya empezó otro turno (se paró y se envió enseguida): lo que llegue de este ya no se pinta, y al salir se cancela la escucha del stream.
        if (_detenido || miTurno != _idTurno) break;
        switch (evento.tipo) {
          case 'delta':
            _textoVivo = (_textoVivo ?? '') + (evento.texto ?? '');
            _avisar();
            alAvanzar?.call();
            if (voz.liveActivo) voz.trocearParaLeer(evento.texto ?? '');
          case 'mensaje':
            if (evento.mensaje != null) {
              _mensajes = [..._mensajes, evento.mensaje!];
              _textoVivo = null;
              _avisar();
              alAvanzar?.call();
            }
          case 'pendiente':
            _pendiente = evento.pendiente;
            _avisar();
            if (voz.liveActivo && evento.pendiente != null) {
              voz.vaciarBufer();
              voz.hablar(_textos().iaEjecutarPregunta(evento.pendiente!.herramienta));
            }
          case 'error':
            _errorTurno = evento.error;
            _avisar();
          case 'fin':
            if (voz.liveActivo) voz.vaciarBufer();
        }
      }
    } on ApiException catch (e) {
      if (!_liberado && miTurno == _idTurno) _errorTurno = e;
    } catch (e) {
      if (!_liberado && miTurno == _idTurno) _errorTurno = e;
    } finally {
      if (!_liberado && miTurno == _idTurno) {
        _enviando = false;
        _avisar();
        alAvanzar?.call();
        if (voz.liveActivo && !voz.hablando && voz.colaVacia) voz.empezarEscucha();
      }
    }
  }

  /// Parar la respuesta: lo que ya se había pintado se queda como mensaje, y lo que falte no se espera.
  void detener() {
    _detenido = true;
    final parcial = _textoVivo;
    if (parcial != null && parcial.trim().isNotEmpty) {
      _idLocal -= 1;
      _mensajes = [..._mensajes, IaMensaje(id: _idLocal, rol: 'assistant', contenido: parcial, creadoEn: DateTime.now().toIso8601String())];
    }
    _textoVivo = null;
    _enviando = false;
    _avisar();
    voz.cancelarVoz();
  }

  /// Borra la conversación entera. Devuelve el texto del error si falló, o `null`.
  Future<String?> vaciar() async {
    if (voz.liveActivo) voz.alternarLive();
    try {
      await api.vaciarIa();
      _mensajes = [];
      _pendiente = null;
      _avisar();
      return null;
    } on ApiException catch (e) {
      return e.mensaje;
    }
  }

  // --- Archivos ------------------------------------------------------------------

  /// Sube un archivo para que vaya con el próximo mensaje. Devuelve el error si falló (un [ApiException] u otro), o `null`.
  Future<Object?> subirAdjunto(Uint8List bytes, String nombre) async {
    _subiendo = true;
    _avisar();
    try {
      _adjunto = await api.subirAdjuntoIa(bytes, nombre);
      return null;
    } catch (e) {
      return e;
    } finally {
      _subiendo = false;
      _avisar();
    }
  }

  void quitarAdjunto() {
    _adjunto = null;
    _avisar();
  }

  // --- Voz -----------------------------------------------------------------------

  void _alDictadoFinal(String texto) {
    alDictar?.call(texto);
    if (voz.liveActivo && texto.trim().isNotEmpty) {
      voz.pararEscucha();
      enviar(texto);
    }
  }

  @override
  void dispose() {
    _liberado = true;
    voz.dispose();
    super.dispose();
  }
}

/// Texto compacto para un mensaje «tool» (misma lógica que `textoMensajeTool` en `app/static/ia_asistente.js`): distingue error, rechazo y ejecución normal
/// leyendo el JSON crudo guardado en `contenido`.
String textoMensajeTool(AppLocalizations t, IaMensaje m) {
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

/// Reconstruye, a partir del historial completo, si hay una acción esperando confirmación ahora mismo: mismo criterio que `ia_asistente._tool_call_id_pendiente`
/// en el servidor (el último mensaje es «assistant» con `tool_calls`, y a alguno de ellos le falta su fila «tool» de respuesta). Hace falta reconstruirlo aquí porque
/// no hay ningún endpoint REST equivalente a `pendiente_actual()` (solo lo usa la vista /ia/ de la web); así el móvil también recupera el estado correcto si se
/// cierra la app a media confirmación.
IaPendiente? pendienteDesdeHistorial(List<IaMensaje> mensajes) {
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
