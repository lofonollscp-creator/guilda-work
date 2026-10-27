import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/funciones/fichaje/fichaje_acciones.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_acciones.dart' show ResultadoAccion;
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/nucleo/servicios.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/services/locale_service.dart';
import 'package:guilda_work_mobile/services/push_service.dart';
import 'package:guilda_work_mobile/services/sync_service.dart';
import 'package:guilda_work_mobile/services/theme_service.dart';
import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:guilda_work_mobile/services/session_service.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';

/// El servidor, sin servidor: lo que usan las pantallas antiguas (Fichaje, Correo, Asistente IA…). Cada prueba rellena lo que necesita.
class ApiFalsa extends ApiClient {
  ApiFalsa() : super(SessionService());
  String estado = 'fuera';
  List<FichajeEvento> eventos = [];
  List<Mensaje> mensajes = [];
  final List<String> pedidos = [];

  @override
  Future<(String, bool)> obtenerEstadoFichaje() async => (estado, true);
  @override
  Future<List<FichajeEvento>> listarMisFichajes({String? desde, String? hasta}) async => eventos;
  @override
  Future<ResumenSemanaFichaje> obtenerResumenSemanaFichaje() async {
    final lunes = DateTime.now().subtract(Duration(days: DateTime.now().weekday - 1));
    String f(int i) => lunes.add(Duration(days: i)).toIso8601String().substring(0, 10);
    final horas = [8.2, 7.5, 6.0, 0.0, 0.0, 0.0, 0.0];
    return ResumenSemanaFichaje(
      segundos: 21.7 * 3600 * 0 + (8.2 + 7.5 + 6.0) * 3600,
      contratados: 40 * 3600,
      diferencia: -(40 - 21.7) * 3600,
      porcentaje: 54,
      enCurso: true,
      dias: [for (var i = 0; i < 7; i++) DiaSemanaFichaje(fecha: f(i), segundos: horas[i] * 3600, hoy: i == DateTime.now().weekday - 1)],
    );
  }

  List<Ausencia> ausencias = [];
  FichajeDatos datosFichaje = FichajeDatos();

  @override
  Future<SaldoAusencias> saldoAusencias({int? anio}) async => SaldoAusencias(anio: anio ?? 2026, total: 23, aprobadas: 8.5, pendientes: 2, disponibles: 12.5);
  @override
  Future<List<Ausencia>> listarMisAusencias({int? anio}) async => ausencias;
  @override
  Future<List<Ausencia>> ausenciasPendientesDelEquipo() async => [];
  @override
  Future<FichajeDatos> obtenerFichajeDatos() async => datosFichaje;
  @override
  Future<List<DestinatarioReciente>> buscarDestinatariosRecientes(String q) async => [DestinatarioReciente(direccion: 'marta@ejemplo.com', nombreMostrado: 'Marta Ruiz')];

  final List<String> acciones = [];
  Mensaje? abierto;
  List<IaConversacion> conversaciones = [];
  @override
  Future<List<IaConversacion>> listarConversacionesIa() async => conversaciones;
  @override
  Future<void> activarConversacionIa(int id) async {}
  List<IaMensaje> chat = [];
  final List<String> enviadosIa = [];

  @override
  Future<List<IaMensaje>> listarMensajesIa() async => chat;
  @override
  Stream<IaEventoStream> enviarMensajeIaStream(String texto) {
    enviadosIa.add(texto);
    return const Stream.empty();
  }

  @override
  Future<Mensaje> obtenerMensaje(int id) async => abierto!;
  @override
  Future<List<CategoriaCorreo>> listarCategoriasCorreo() async => [CategoriaCorreo(id: 1, nombre: 'Clientes', color: '#3b82f6')];
  @override
  Future<void> marcarLeido(int id, bool leido) async => acciones.add('leido:$id:$leido');
  @override
  Future<void> destacarMensaje(int id, bool destacado) async => acciones.add('destacar:$id:$destacado');

  @override
  Future<List<CuentaCorreo>> listarCuentasCorreo() async => [
        CuentaCorreo(id: 1, nombre: 'Despacho', protocolo: 'imap', host: 'h', puerto: 993, usuario: 'a'),
        CuentaCorreo(id: 2, nombre: 'Personal', protocolo: 'imap', host: 'h', puerto: 993, usuario: 'b'),
      ];
  @override
  Future<List<Carpeta>> listarCarpetas(int cuentaId) async => [Carpeta(nombre: 'INBOX', nombreVisible: 'Entrada'), Carpeta(nombre: 'Sent', nombreVisible: 'Enviados')];
  @override
  Future<List<Mensaje>> listarMensajes({required int cuentaId, String carpeta = 'INBOX', bool? noLeidos, String? q}) async {
    pedidos.add('$cuentaId:$carpeta:${noLeidos ?? '-'}:${q ?? '-'}');
    return mensajes;
  }
}

class AccionesFalsas extends AccionesFichaje {
  final List<String> marcas;
  AccionesFalsas(super.ref, this.marcas);
  @override
  Future<ResultadoAccion<String>> marcar(String tipo, {double? latitud, double? longitud, DateTime? ahora}) async {
    marcas.add(tipo);
    return ResultadoAccion.enviada({'entrada': 'dentro', 'pausa_inicio': 'en_pausa', 'pausa_fin': 'dentro', 'salida': 'fuera'}[tipo]!);
  }
}

class SesionConUsuario extends SesionControl {
  @override
  EstadoSesion build() => EstadoSesion(fase: FaseSesion.conSesion, usuario: Usuario(id: 1, email: 'a@b.c'));
}

class SesionFija extends SesionControl {
  @override
  EstadoSesion build() => const EstadoSesion(fase: FaseSesion.conSesion);
}

FichajeEvento ev(int id, String tipo, String hora) => FichajeEvento(id: id, tipo: tipo, marcaTiempo: '${DateTime.now().toIso8601String().substring(0, 10)}T$hora:00', origen: 'app');

Mensaje msg(int id, String de, String asunto, String texto, {bool leido = true, bool destacado = false}) => Mensaje(
      id: id, cuentaId: 1, carpeta: 'INBOX', asunto: asunto, remitente: de, destinatarios: 'yo@ejemplo.com', fecha: '2026-10-24T09:30', cuerpoTexto: texto,
      leido: leido, destacado: destacado, remitenteConfiable: true, adjuntos: const [],
    );

Widget appDePantalla(Widget home, List<Override> overrides, {bool oscuro = false, GlobalKey? clave}) {
  final app = MaterialApp(
    debugShowCheckedModeBanner: false,
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('es'),
    theme: AppTheme.light,
    darkTheme: AppTheme.dark,
    themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
    home: home,
  );
  return ProviderScope(overrides: overrides, child: clave == null ? app : RepaintBoundary(key: clave, child: app));
}


/// Carpeta donde se guardan las capturas de diseño (`CAPTURAS=<carpeta>`); sin ella no se captura nada.
final String? carpetaCapturas = Platform.environment['CAPTURAS'];

/// Carga las fuentes reales de la app (y la de iconos del SDK) para que las capturas se vean como en el móvil. Se llama en `setUpAll`.
Future<void> cargarFuentesParaCapturas() async {
  if (carpetaCapturas == null) return;
  Directory(carpetaCapturas!).createSync(recursive: true);
  Future<void> fuente(String familia, List<String> rutas) async {
    final f = FontLoader(familia);
    for (final r in rutas) {
      f.addFont(Future.value(ByteData.sublistView(File(r).readAsBytesSync())));
    }
    await f.load();
  }

  await fuente('Manrope', ['assets/fonts/Manrope-Regular.ttf', 'assets/fonts/Manrope-Medium.ttf', 'assets/fonts/Manrope-SemiBold.ttf', 'assets/fonts/Manrope-Bold.ttf']);
  await fuente('Inter', ['assets/fonts/Inter-Regular.ttf', 'assets/fonts/Inter-SemiBold.ttf']);
  await fuente('MaterialIcons', ['${Platform.environment['FLUTTER_ROOT'] ?? '/home/guilda/flutter'}/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf']);
}

Future<void> capturar(WidgetTester t, GlobalKey clave, String nombre) async {
  final limite = t.renderObject<RenderRepaintBoundary>(find.byKey(clave));
  final bytes = await t.runAsync(() async => (await (await limite.toImage(pixelRatio: 2)).toByteData(format: ui.ImageByteFormat.png))!);
  File('$carpetaCapturas/$nombre.png').writeAsBytesSync(bytes!.buffer.asUint8List());
}

/// La voz usa plugins nativos que en un test no existen: se contestan en blanco (las pantallas tienen que seguir funcionando sin voz).
void sinVoz() {
  final m = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  for (final canal in ['flutter_tts', 'plugin.csdcorp.com/speech_to_text']) {
    m.setMockMethodCallHandler(MethodChannel(canal), (_) async => null);
  }
}

IaMensaje iaMsg(int id, String rol, String? contenido, {String? calls, String? callId, String? herramienta, String? fuentes}) =>
    IaMensaje(id: id, rol: rol, contenido: contenido, toolCallsJson: calls, toolCallId: callId, nombreHerramienta: herramienta, creadoEn: '2026-10-26T09:00', fuentesJson: fuentes);


/// Los servicios de la app con el servidor simulado: para las pantallas de Riverpod que sacan de ahí el cliente (el panel del asistente en la tableta).
Servicios serviciosFalsos([ApiClient? api]) {
  final cliente = api ?? ApiFalsa();
  return Servicios(sesion: SessionService(), api: cliente, sync: SyncService(), push: PushService(cliente), tema: ThemeService(), locale: LocaleService());
}
