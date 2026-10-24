import 'dart:convert';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart' show TargetPlatform, defaultTargetPlatform, kIsWeb;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import 'api_client.dart';

/// Notificaciones push (Firebase Cloud Messaging) -- ver app/push.py para
/// el lado servidor. Requiere `google-services.json` en android/app/ (y
/// el plugin de Gradle correspondiente, ver android/app/build.gradle.kts)
/// antes de que esto funcione de verdad; mientras Firebase no esté
/// configurado, `Firebase.initializeApp()` lanza y se captura en
/// `inicializar()`, dejando la app funcionando con normalidad sin push --
/// mismo criterio de "opcional, no bloqueante" que `app/push.py` en el
/// servidor.
class PushService {
  final ApiClient api;
  final FlutterLocalNotificationsPlugin _local = FlutterLocalNotificationsPlugin();
  String? _tokenActual;
  bool _iniciado = false;

  /// Familias de aviso = canales de notificación de Android (los mismos ids que `canal` en el push del servidor,
  /// `app/aviso_destino.py`). Cada una se puede silenciar por separado en los ajustes del sistema.
  static const canales = ['tareas', 'correo', 'fiscal', 'equipo', 'resumenes', 'general'];

  /// Se llama al tocar una notificación (en primer plano vía
  /// flutter_local_notifications, o desde background/terminada vía
  /// FirebaseMessaging.onMessageOpenedApp) con el `data` del mensaje --
  /// quien construya PushService decide a qué pantalla navegar según
  /// datos['tipo'] (ver dashboard_screen.dart).
  void Function(Map<String, dynamic> datos)? onTap;

  PushService(this.api);

  bool get _plataformaSoportada =>
      !kIsWeb && (defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS);

  /// Crea los canales de Android con sus nombres (en el idioma de la app). Si ya existen, Android solo actualiza el nombre.
  Future<void> crearCanales(Map<String, String> nombres) async {
    if (!_plataformaSoportada || defaultTargetPlatform != TargetPlatform.android) return;
    final android = _local.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    for (final id in canales) {
      await android?.createNotificationChannel(AndroidNotificationChannel(id, nombres[id] ?? id, importance: Importance.defaultImportance));
    }
  }

  /// Se llama en cada inicio de sesión (y desde pantallas antiguas). La primera vez prepara Firebase y los avisos; las siguientes solo
  /// vuelven a registrar el dispositivo (al cerrar sesión se dio de baja), sin duplicar los oyentes.
  Future<void> inicializar() async {
    if (!_plataformaSoportada) return; // solo Android/iOS -- FCM no aplica a escritorio/web
    if (_iniciado) {
      final token = _tokenActual;
      if (token != null) await _registrar(token);
      return;
    }
    _iniciado = true;
    try {
      await Firebase.initializeApp();
    } catch (_) {
      _iniciado = false;
      return; // Firebase no configurado en este build todavía
    }

    await _local.initialize(
      const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(),
      ),
      onDidReceiveNotificationResponse: (respuesta) {
        final payload = respuesta.payload;
        if (payload != null) onTap?.call(_decodificar(payload));
      },
    );

    final mensajeria = FirebaseMessaging.instance;
    await mensajeria.requestPermission();

    final token = await mensajeria.getToken();
    if (token != null) await _registrar(token);
    mensajeria.onTokenRefresh.listen(_registrar);

    FirebaseMessaging.onMessage.listen((mensaje) {
      final notif = mensaje.notification;
      if (notif == null) return;
      _local.show(
        mensaje.hashCode,
        notif.title,
        notif.body,
        NotificationDetails(
          android: AndroidNotificationDetails(_canalDe(mensaje.data), _canalDe(mensaje.data)),
          iOS: const DarwinNotificationDetails(),
        ),
        payload: jsonEncode(mensaje.data),
      );
    });

    FirebaseMessaging.onMessageOpenedApp.listen((mensaje) => onTap?.call(mensaje.data));

    // La app estaba cerrada y se abrió tocando un aviso.
    final inicial = await mensajeria.getInitialMessage();
    if (inicial != null) onTap?.call(inicial.data);
  }

  String _canalDe(Map<String, dynamic> datos) {
    final canal = datos['canal']?.toString();
    return canales.contains(canal) ? canal! : 'general';
  }

  Future<void> _registrar(String token) async {
    _tokenActual = token;
    final plataforma = defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';
    await api.registrarDispositivoPush(token, plataforma);
  }

  /// Se llama en logout para que el servidor deje de mandar push a este
  /// dispositivo mientras no haya sesión.
  Future<void> alCerrarSesion() async {
    final token = _tokenActual;
    if (token != null) await api.eliminarDispositivoPush(token);
  }

  Map<String, dynamic> _decodificar(String payload) {
    try {
      return jsonDecode(payload) as Map<String, dynamic>;
    } catch (_) {
      return {};
    }
  }
}
