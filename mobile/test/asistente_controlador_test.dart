import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/funciones/asistente/asistente_controlador.dart';
import 'package:guilda_work_mobile/funciones/asistente/motor_voz.dart';
import 'package:guilda_work_mobile/funciones/asistente/servicio_voz.dart';
import 'package:guilda_work_mobile/l10n/app_localizations_es.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'ayudas/pantallas.dart';

/// Un motor de voz que no toca ningún plugin: anota lo que se le pide y deja que la prueba haga de reconocedor.
class MotorFalso implements MotorVoz {
  bool reconocimientoDisponible = true;
  String? localeEncontrado = 'es-ES';
  final llamadas = <String>[];
  final leidas = <String>[];
  String? lecturaConfigurada;
  void Function(bool, bool)? alEstado;
  void Function()? alError;
  void Function(String, bool)? alResultado;
  bool liberado = false;

  /// Si es `true`, cada lectura se queda esperando hasta que la prueba la termine con [acabarLectura].
  bool lecturaManual = false;
  final _lecturas = <Completer<void>>[];

  void acabarLectura() => _lecturas.removeAt(0).complete();

  @override
  Future<bool> inicializar({required void Function(bool, bool) alEstado, required void Function() alError}) async {
    llamadas.add('inicializar');
    this.alEstado = alEstado;
    this.alError = alError;
    return reconocimientoDisponible;
  }

  @override
  Future<String?> localeIdPara(String idioma) async => localeEncontrado;

  @override
  Future<void> configurarLectura(String bcp47) async => lecturaConfigurada = bcp47;

  @override
  Future<void> escuchar({required String? localeId, required void Function(String, bool) alResultado}) async {
    llamadas.add('escuchar:$localeId');
    this.alResultado = alResultado;
  }

  @override
  Future<void> cancelarEscucha() async => llamadas.add('cancelarEscucha');

  @override
  Future<void> pararEscucha() async => llamadas.add('pararEscucha');

  @override
  Future<void> leer(String texto) async {
    leidas.add(texto);
    if (lecturaManual) {
      final c = Completer<void>();
      _lecturas.add(c);
      await c.future;
    }
  }

  @override
  Future<void> pararLectura() async => llamadas.add('pararLectura');

  @override
  Future<void> liberar() async => liberado = true;

  int escuchas() => llamadas.where((l) => l.startsWith('escuchar:')).length;
}

IaEventoStream _delta(String s) => IaEventoStream(tipo: 'delta', texto: s);
IaEventoStream _mensaje(IaMensaje m) => IaEventoStream(tipo: 'mensaje', mensaje: m);
IaEventoStream _fin() => IaEventoStream(tipo: 'fin');

final _t = AppLocalizationsEs();

AsistenteControlador _controlador(ApiFalsa api, MotorFalso motor, {String? contextoIa, void Function(String)? alDictar, void Function()? alEnviar}) => AsistenteControlador(
      api: api,
      textos: () => _t,
      motor: motor,
      idiomaVoz: () => 'es',
      contextoIa: contextoIa,
      alDictar: alDictar,
      alEnviar: alEnviar,
      pausaReescucha: Duration.zero,
      pausaTrasHablar: Duration.zero,
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('enviar', () {
    test('un texto vacío no se envía; uno con contenido sale al instante como mensaje tuyo con id negativo', () async {
      final api = ApiFalsa();
      final c = _controlador(api, MotorFalso());
      await c.cargarHistorial();

      expect(c.enviar('   '), isFalse);
      expect(api.enviadosIa, isEmpty);

      var vaciado = 0;
      final c2 = _controlador(api, MotorFalso(), alEnviar: () => vaciado++);
      expect(c2.enviar('  Hola  '), isTrue);
      expect(api.enviadosIa, ['Hola']);
      expect(c2.mensajes.single.rol, 'user');
      expect(c2.mensajes.single.id, lessThan(0));
      expect(vaciado, 1); // la pantalla vacía el campo
      await c2.turno;
      c.dispose();
      c2.dispose();
    });

    test('mientras hay un turno en curso no se acepta otro envío', () async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      final c = _controlador(api, MotorFalso());
      expect(c.enviar('Uno'), isTrue);
      expect(c.enviando, isTrue);
      expect(c.enviar('Dos'), isFalse);
      expect(api.enviadosIa, ['Uno']);
      await turno.close();
      await c.turno;
      expect(c.enviando, isFalse);
      c.dispose();
    });

    test('el contexto va con el primer mensaje, no con los siguientes, y vuelve si cambia el elemento o si se quita', () async {
      final api = ApiFalsa();
      final c = _controlador(api, MotorFalso(), contextoIa: 'tarea #7 «Presentar el 303»');
      c.enviar('Uno');
      await c.turno;
      c.enviar('Dos');
      await c.turno;
      expect(api.enviadosIa, ['[Contexto: tarea #7 «Presentar el 303»]\nUno', 'Dos']);

      c.contextoIa = 'tarea #9 «Otra»'; // el panel de la tableta cambió de tarea
      c.enviar('Tres');
      await c.turno;
      expect(api.enviadosIa.last, '[Contexto: tarea #9 «Otra»]\nTres');

      c.contextoIa = 'tarea #10 «Más»';
      c.ocultarContexto(); // la persona quitó la píldora: ya no se cuenta
      c.enviar('Cuatro');
      await c.turno;
      expect(api.enviadosIa.last, 'Cuatro');
      c.dispose();
    });

    test('lo que se muestra de ti no cambia, pero lo que se envía lleva el contexto', () async {
      final api = ApiFalsa();
      final c = _controlador(api, MotorFalso(), contextoIa: 'correo, mensaje #3');
      c.enviar('Resume esto');
      await c.turno;
      // La línea técnica va en el mensaje local; la pantalla la quita al pintar (quitarContextoDelTexto).
      expect(c.mensajes.first.contenido, startsWith('[Contexto: correo, mensaje #3]'));
      c.dispose();
    });
  });

  group('archivos', () {
    test('un archivo subido va nombrado en la primera línea; sin texto, se le pide que lo lea; después se olvida', () async {
      final api = ApiFalsa();
      final c = _controlador(api, MotorFalso());
      expect(await c.subirAdjunto(Uint8List(3), 'datos.csv'), isNull);
      expect(c.adjunto?.nombre, 'datos.csv');
      expect(c.subiendo, isFalse);

      expect(c.enviar(''), isTrue);
      expect(api.enviadosIa.single, '[Adjunto #7: datos.csv]\n${_t.iaAdjuntoPregunta}');
      expect(c.adjunto, isNull);
      await c.turno;
      c.dispose();
    });

    test('si la subida falla, se devuelve el error y no queda ningún archivo', () async {
      final api = ApiFalsa()..falloSubidaIa = ApiException('Archivo demasiado grande');
      final c = _controlador(api, MotorFalso());
      final error = await c.subirAdjunto(Uint8List(3), 'enorme.csv');
      expect(error, isA<ApiException>());
      expect(c.adjunto, isNull);
      expect(c.subiendo, isFalse);
      c.dispose();
    });

    test('se puede quitar el archivo antes de enviar', () async {
      final c = _controlador(ApiFalsa(), MotorFalso());
      await c.subirAdjunto(Uint8List(3), 'a.txt');
      c.quitarAdjunto();
      expect(c.adjunto, isNull);
      c.dispose();
    });

    test('no se envía mientras el archivo se está subiendo', () async {
      final api = ApiFalsa();
      final c = _controlador(api, MotorFalso());
      final subida = c.subirAdjunto(Uint8List(3), 'a.txt');
      expect(c.subiendo, isTrue);
      expect(c.enviar('Hola'), isFalse);
      await subida;
      c.dispose();
    });
  });

  group('el turno', () {
    test('los eventos van moviendo el estado: texto vivo, mensaje definitivo, pendiente y fin', () async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      final c = _controlador(api, MotorFalso());
      c.enviar('Hola');

      turno.add(_delta('Ho'));
      await pumpEventQueue();
      turno.add(_delta('la'));
      await pumpEventQueue();
      expect(c.textoVivo, 'Hola');

      turno.add(_mensaje(iaMsg(5, 'assistant', 'Hola.')));
      await pumpEventQueue();
      expect(c.textoVivo, isNull);
      expect(c.mensajes.last.contenido, 'Hola.');

      turno.add(IaEventoStream(tipo: 'pendiente', pendiente: IaPendiente(toolCallId: 'c1', herramienta: 'crear_nota', argumentos: const {})));
      turno.add(_fin());
      await turno.close();
      await c.turno;
      expect(c.pendiente?.herramienta, 'crear_nota');
      expect(c.enviando, isFalse);
      expect(c.ultimaRespuesta, 'Hola.');
      c.dispose();
    });

    test('un turno nuevo empieza sin el error, el texto vivo ni la acción pendiente del anterior', () async {
      var n = 0;
      final api = ApiFalsa()
        ..flujoIa = ((_) => n++ == 0
            ? Stream.fromIterable([IaEventoStream(tipo: 'error', error: 'Falló'), IaEventoStream(tipo: 'pendiente', pendiente: IaPendiente(toolCallId: 'c', herramienta: 'x', argumentos: const {}))])
            : const Stream.empty());
      final c = _controlador(api, MotorFalso());
      c.enviar('Uno');
      await c.turno;
      expect(c.errorTurno, 'Falló');
      expect(c.pendiente, isNotNull);
      c.confirmar(false); // la pendiente se responde: el turno que sigue parte limpio
      await c.turno;
      expect(c.errorTurno, isNull);
      expect(c.pendiente, isNull);
      c.dispose();
    });

    test('un fallo de red se guarda como el error del turno', () async {
      final api = ApiFalsa()..flujoIa = ((_) => Stream<IaEventoStream>.error(ApiException('Sin red', esDeConexion: true)));
      final c = _controlador(api, MotorFalso());
      c.enviar('Hola');
      await c.turno;
      expect(c.errorTurno, isA<ApiException>());
      expect(c.enviando, isFalse);
      c.dispose();
    });

    test('«detener» conserva lo ya pintado como mensaje; lo que llegue después se ignora', () async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      final c = _controlador(api, MotorFalso());
      c.enviar('Cuenta');
      turno.add(_delta('Érase una '));
      await pumpEventQueue();
      c.detener();
      expect(c.enviando, isFalse);
      expect(c.textoVivo, isNull);
      expect(c.mensajes.last.rol, 'assistant');
      expect(c.mensajes.last.contenido, 'Érase una ');

      final cantidad = c.mensajes.length;
      turno.add(_mensaje(iaMsg(9, 'assistant', 'No debería verse')));
      await pumpEventQueue();
      expect(c.mensajes.length, cantidad);
      unawaited(turno.close());
      c.dispose();
    });

    test('si se para y se envía otra cosa enseguida, lo que llega del turno parado no se mezcla con el nuevo', () async {
      final viejo = StreamController<IaEventoStream>();
      final nuevo = StreamController<IaEventoStream>();
      var n = 0;
      final api = ApiFalsa()..flujoIa = ((_) => n++ == 0 ? viejo.stream : nuevo.stream);
      final c = _controlador(api, MotorFalso());

      c.enviar('Primera');
      viejo.add(_delta('respuesta vieja'));
      await pumpEventQueue();
      c.detener();
      c.enviar('Segunda'); // la persona no espera a que el turno viejo se dé cuenta de que lo pararon
      nuevo.add(_delta('respuesta nueva'));
      await pumpEventQueue();

      viejo.add(_delta(' + cola de la vieja')); // llega tarde
      viejo.add(_mensaje(iaMsg(50, 'assistant', 'mensaje viejo')));
      await pumpEventQueue();
      expect(c.textoVivo, 'respuesta nueva'); // sin la cola de la vieja
      expect(c.mensajes.where((m) => m.contenido == 'mensaje viejo'), isEmpty);
      expect(c.enviando, isTrue); // y el turno nuevo sigue en marcha: el viejo no lo cerró al salir

      nuevo.add(_mensaje(iaMsg(51, 'assistant', 'Hecho.')));
      nuevo.add(_fin());
      await nuevo.close();
      await c.turno;
      expect(c.enviando, isFalse);
      unawaited(viejo.close());
      c.dispose();
    });

    test('cerrar el chat con un turno en marcha no revienta ni toca nada después', () async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      final c = _controlador(api, MotorFalso());
      c.enviar('Hola');
      c.dispose();
      turno.add(_delta('tarde'));
      unawaited(turno.close());
      await pumpEventQueue();
      // Sin excepción: notifyListeners tras dispose habría saltado.
    });

    test('al confirmar, el estado «confirmando» dura lo que el turno', () async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoConfirmarIa = (_) => turno.stream;
      final c = _controlador(api, MotorFalso());
      final f = c.confirmar(true);
      expect(c.confirmando, isTrue);
      expect(api.confirmadosIa, [true]);
      turno.add(_fin());
      await turno.close();
      await f;
      expect(c.confirmando, isFalse);
      c.dispose();
    });
  });

  group('historial y conversaciones', () {
    test('una acción que quedó a medias vuelve como pendiente; una ya respondida, no', () {
      final a = iaMsg(2, 'assistant', 'Voy', calls: '[{"id":"c1","function":{"name":"crear_nota","arguments":"{\\"titulo\\":\\"Ideas\\"}"}}]');
      expect(pendienteDesdeHistorial([iaMsg(1, 'user', 'x'), a])?.argumentos['titulo'], 'Ideas');
      expect(pendienteDesdeHistorial([iaMsg(1, 'user', 'x'), a, iaMsg(3, 'tool', '{}', callId: 'c1')]), isNull);
      expect(pendienteDesdeHistorial(const []), isNull);
      expect(pendienteDesdeHistorial([iaMsg(1, 'user', 'x')]), isNull);
    });

    test('un JSON roto en la acción pendiente no rompe: sin detalle o sin pendiente', () {
      expect(pendienteDesdeHistorial([iaMsg(2, 'assistant', 'Voy', calls: '{roto')]), isNull);
      final sinArgumentos = iaMsg(2, 'assistant', 'Voy', calls: '[{"id":"c1","function":{"name":"crear_nota","arguments":"{roto"}}]');
      expect(pendienteDesdeHistorial([sinArgumentos])?.argumentos, isEmpty);
    });

    test('lo que hizo una herramienta se resume según salió: bien, con error o rechazada', () {
      expect(textoMensajeTool(_t, iaMsg(1, 'tool', '{"ok":true}', herramienta: 'crear_tarea')), _t.iaToolUso('crear_tarea'));
      expect(textoMensajeTool(_t, iaMsg(1, 'tool', '{"error":"sin permiso"}', herramienta: 'borrar')), _t.iaToolError('borrar', 'sin permiso'));
      expect(textoMensajeTool(_t, iaMsg(1, 'tool', '{"rechazado":true}', herramienta: 'borrar')), _t.iaToolRechazada('borrar'));
      expect(textoMensajeTool(_t, iaMsg(1, 'tool', 'no es json', herramienta: 'x')), _t.iaToolUso('x'));
      expect(textoMensajeTool(_t, iaMsg(1, 'tool', null)), _t.iaToolUso('herramienta'));
    });

    test('si el historial no carga, se guarda el error; «cargarHistorial» lo reintenta', () async {
      final api = ApiFalsa()..falloCargaIa = ApiException('Servidor caído');
      final c = _controlador(api, MotorFalso());
      await c.cargarHistorial();
      expect(c.errorCarga, isA<ApiException>());
      expect(c.cargando, isFalse);

      api
        ..falloCargaIa = null
        ..chat = [iaMsg(1, 'user', 'Hola')];
      await c.cargarHistorial();
      expect(c.errorCarga, isNull);
      expect(c.mensajes, hasLength(1));
      c.dispose();
    });

    test('la consulta inicial se envía al abrir, pero no si el historial no cargó', () async {
      final bien = ApiFalsa();
      final c = _controlador(bien, MotorFalso());
      await c.iniciar(consultaInicial: ' Resume mi día ');
      expect(bien.enviadosIa, ['Resume mi día']);
      await c.turno;
      c.dispose();

      final mal = ApiFalsa()..falloCargaIa = ApiException('caído');
      final c2 = _controlador(mal, MotorFalso());
      await c2.iniciar(consultaInicial: 'Resume mi día');
      expect(mal.enviadosIa, isEmpty);
      c2.dispose();
    });

    test('vaciar borra el historial y la acción pendiente; si falla, devuelve el texto del error', () async {
      final api = ApiFalsa()..chat = [iaMsg(1, 'user', 'Hola')];
      final c = _controlador(api, MotorFalso());
      await c.cargarHistorial();
      expect(await c.vaciar(), isNull);
      expect(c.mensajes, isEmpty);
      expect(c.enBlanco, isTrue);

      api.falloVaciarIa = ApiException('No se pudo');
      expect(await c.vaciar(), 'No se pudo');
      c.dispose();
    });

    test('retomar una conversación recarga el historial; si falla, devuelve el texto', () async {
      final api = ApiFalsa()..chat = [iaMsg(1, 'user', 'Antiguo')];
      final c = _controlador(api, MotorFalso());
      expect(await c.retomar(IaConversacion(id: 3, titulo: 'X', activa: false)), isNull);
      expect(c.mensajes.single.contenido, 'Antiguo');
      c.dispose();
    });
  });

  group('la voz', () {
    ServicioVoz crear(MotorFalso motor, {bool enviando = false, bool pendiente = false, void Function(String)? alFinal}) => ServicioVoz(
          motor: motor,
          enviando: () => enviando,
          hayPendiente: () => pendiente,
          alTextoFinal: alFinal ?? (_) {},
          pausaReescucha: Duration.zero,
          pausaTrasHablar: Duration.zero,
        );

    test('arranca con el idioma de la persona; sin reconocimiento no hay voz; cerrar antes de que acabe no la activa', () async {
      final motor = MotorFalso();
      final voz = crear(motor);
      await voz.inicializar('ca');
      expect(voz.disponible, isTrue);
      expect(motor.lecturaConfigurada, 'ca-ES');

      final sinPermiso = MotorFalso()..reconocimientoDisponible = false;
      final v2 = crear(sinPermiso);
      await v2.inicializar('es');
      expect(v2.disponible, isFalse);

      final v3 = crear(MotorFalso());
      final f = v3.inicializar('es');
      v3.dispose();
      await f;
      expect(v3.disponible, isFalse);
      voz.dispose();
      v2.dispose();
    });

    test('lee las frases en orden, sin recortes, y no lee nada si no hay voz', () async {
      final motor = MotorFalso();
      final voz = crear(motor);
      voz.hablar('Hola'); // aún sin arrancar: no hay voz
      expect(motor.leidas, isEmpty);

      await voz.inicializar('es');
      voz.hablar('  Uno  ');
      voz.hablar('Dos');
      voz.hablar('   ');
      await pumpEventQueue();
      expect(motor.leidas, ['Uno', 'Dos']);
      expect(voz.hablando, isFalse);
      voz.dispose();
    });

    test('trocea lo que llega por frases completas y guarda el trozo final hasta vaciarlo', () async {
      final motor = MotorFalso();
      final voz = crear(motor);
      await voz.inicializar('es');
      voz.trocearParaLeer('Tienes dos tareas. La prime');
      await pumpEventQueue();
      expect(motor.leidas, ['Tienes dos tareas.']);
      voz.trocearParaLeer('ra vence hoy! Y la se');
      await pumpEventQueue();
      expect(motor.leidas, ['Tienes dos tareas.', 'La primera vence hoy!']);
      voz.vaciarBufer();
      await pumpEventQueue();
      expect(motor.leidas.last, 'Y la se');
      voz.dispose();
    });

    test('«cancelarVoz» vacía lo pendiente de leer y para el motor', () async {
      final motor = MotorFalso()..lecturaManual = true;
      final voz = crear(motor);
      await voz.inicializar('es');
      voz.hablar('Uno');
      voz.hablar('Dos');
      await pumpEventQueue();
      expect(voz.hablando, isTrue);
      voz.cancelarVoz();
      expect(voz.hablando, isFalse);
      expect(voz.colaVacia, isTrue);
      expect(motor.llamadas, contains('pararLectura'));
      voz.dispose();
    });

    test('no se pone a escuchar si está enviando, leyendo, esperando confirmación o en silencio; si no, sí, cancelando antes la sesión anterior', () async {
      for (final (nombre, enviando, pendiente) in [('enviando', true, false), ('pendiente', false, true)]) {
        final motor = MotorFalso();
        final voz = crear(motor, enviando: enviando, pendiente: pendiente);
        await voz.inicializar('es');
        await voz.empezarEscucha();
        expect(motor.escuchas(), 0, reason: nombre);
        voz.dispose();
      }

      final motor = MotorFalso()..lecturaManual = true;
      final voz = crear(motor);
      await voz.inicializar('es');
      voz.hablar('Algo');
      await pumpEventQueue();
      await voz.empezarEscucha(); // leyendo
      expect(motor.escuchas(), 0);
      motor.acabarLectura();
      await pumpEventQueue();

      voz.alternarSilencio();
      await voz.empezarEscucha(); // en silencio
      expect(motor.escuchas(), 0);
      voz.alternarSilencio(); // al reanudar vuelve a escuchar solo
      await pumpEventQueue();
      expect(motor.escuchas(), 1);
      expect(motor.llamadas.indexOf('cancelarEscucha'), lessThan(motor.llamadas.indexWhere((l) => l.startsWith('escuchar:'))));
      expect(motor.llamadas.last, 'escuchar:es-ES');
      voz.dispose();
    });

    test('lo dictado llega al final con el texto reconocido; los resultados parciales solo actualizan lo que se oye', () async {
      final motor = MotorFalso();
      final finales = <String>[];
      final voz = crear(motor, alFinal: finales.add);
      await voz.inicializar('es');
      await voz.empezarEscucha();
      motor.alResultado!('resu', false);
      expect(voz.textoVoz, 'resu');
      expect(finales, isEmpty);
      motor.alResultado!('resume mi día', true);
      expect(finales, ['resume mi día']);
      voz.dispose();
    });

    test('«Live»: si la escucha acaba sola sin resultado y no hay nada en curso, vuelve a escuchar; si hay un envío en curso, no', () async {
      final motor = MotorFalso();
      var enviando = false;
      final voz = ServicioVoz(motor: motor, enviando: () => enviando, hayPendiente: () => false, alTextoFinal: (_) {}, pausaReescucha: Duration.zero, pausaTrasHablar: Duration.zero);
      await voz.inicializar('es');
      voz.alternarLive();
      await pumpEventQueue();
      expect(motor.escuchas(), 1);

      motor.alEstado!(false, true); // «done» sin que llegara nada
      await pumpEventQueue();
      expect(motor.escuchas(), 2);

      enviando = true;
      motor.alEstado!(false, true);
      await pumpEventQueue();
      expect(motor.escuchas(), 2); // no se pisa el turno en curso
      voz.dispose();
    });

    test('«Live»: al acabar de leer la respuesta vuelve a escuchar; al apagarlo, deja de escuchar y de leer', () async {
      final motor = MotorFalso()..lecturaManual = true;
      final voz = crear(motor);
      await voz.inicializar('es');
      voz.alternarLive();
      await pumpEventQueue();
      final antes = motor.escuchas();
      // El reconocedor sigue «escuchando» desde el punto de vista del motor falso hasta que avisa.
      voz.hablar('Te leo la respuesta.');
      await pumpEventQueue();
      expect(voz.hablando, isTrue);
      motor.acabarLectura();
      await pumpEventQueue();
      expect(motor.escuchas(), greaterThan(antes)); // acabó de leer: otra vez a escuchar

      voz.alternarLive();
      expect(voz.liveActivo, isFalse);
      expect(motor.llamadas, contains('pararLectura'));
      voz.dispose();
    });

    test('cerrar el servicio libera el motor y calla las notificaciones', () async {
      final motor = MotorFalso();
      final voz = crear(motor);
      await voz.inicializar('es');
      var avisos = 0;
      voz.addListener(() => avisos++);
      voz.dispose();
      expect(motor.liberado, isTrue);
      motor.alEstado!(true, false); // un aviso tardío del reconocedor no debe fallar
      expect(avisos, 0);
    });
  });

  group('la voz dentro del chat', () {
    test('en «Live», lo dictado se envía solo y la respuesta se lee por frases completas', () async {
      final motor = MotorFalso();
      final dictados = <String>[];
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      final c = _controlador(api, motor, alDictar: dictados.add);
      await c.iniciar();
      await pumpEventQueue();
      expect(c.voz.disponible, isTrue);

      c.voz.alternarLive();
      await pumpEventQueue();
      motor.alResultado!('qué tengo hoy', true);
      expect(dictados, ['qué tengo hoy']);
      expect(api.enviadosIa, ['qué tengo hoy']); // en Live se envía sin tocar nada

      turno.add(_delta('Tienes dos tareas. Una '));
      await pumpEventQueue();
      expect(motor.leidas, ['Tienes dos tareas.']);
      turno.add(_delta('vence hoy.'));
      turno.add(_fin());
      await turno.close();
      await c.turno;
      await pumpEventQueue();
      expect(motor.leidas.last, 'Una vence hoy.'); // el final se vacía al acabar el turno
      c.dispose();
    });

    test('fuera de «Live», lo dictado solo rellena el campo: no se envía', () async {
      final motor = MotorFalso();
      final dictados = <String>[];
      final api = ApiFalsa();
      final c = _controlador(api, motor, alDictar: dictados.add);
      await c.iniciar();
      await pumpEventQueue();
      await c.voz.empezarEscucha();
      motor.alResultado!('borrador de mensaje', true);
      expect(dictados, ['borrador de mensaje']);
      expect(api.enviadosIa, isEmpty);
      c.dispose();
    });

    test('en «Live», una acción pendiente se pregunta en voz alta', () async {
      final motor = MotorFalso();
      final api = ApiFalsa()..flujoIa = ((_) => Stream.fromIterable([IaEventoStream(tipo: 'pendiente', pendiente: IaPendiente(toolCallId: 'c', herramienta: 'crear_tarea', argumentos: const {})), _fin()]));
      final c = _controlador(api, motor);
      await c.iniciar();
      await pumpEventQueue();
      c.voz.alternarLive();
      await pumpEventQueue();
      c.enviar('Crea una tarea');
      await c.turno;
      await pumpEventQueue();
      expect(motor.leidas, contains(_t.iaEjecutarPregunta('crear_tarea')));
      // Con una acción esperando un sí o un no, no se queda escuchando: no pisa la pregunta.
      expect(c.pendiente, isNotNull);
      c.dispose();
    });

    test('si la voz no arranca, el chat funciona igual', () async {
      final motor = MotorFalso()..reconocimientoDisponible = false;
      final api = ApiFalsa();
      final c = _controlador(api, motor);
      await c.iniciar();
      expect(c.voz.disponible, isFalse);
      expect(c.enviar('Hola'), isTrue);
      await c.turno;
      c.dispose();
    });
  });
}
