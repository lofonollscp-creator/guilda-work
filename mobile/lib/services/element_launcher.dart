import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:url_launcher/url_launcher.dart';

/// Intenta abrir la app nativa de Element X (cliente Matrix oficial) y, si
/// no está instalada, manda a la tienda correspondiente para descargarla --
/// a petición del usuario, en vez de abrir el cliente Matrix propio de
/// Guilda Work (chat_login_screen.dart/matrix_service.dart, que se deja
/// intacto por si se quiere volver a usar).
///
/// OJO con el esquema personalizado: `io.element.elementx://` se deduce del
/// bundle id real de Element X en iOS (`io.element.elementx`, confirmado),
/// pero Element no publica oficialmente ese esquema como API estable -- si
/// en algún dispositivo no abre la app teniéndola instalada, hace falta
/// ajustar este esquema (verificarlo en vivo, no hay forma de confirmarlo
/// sin probarlo en un iPhone/Android con la app instalada).
const _esquemaElementX = 'io.element.elementx://';
const _idAppStoreElementX = '1631335820';
const _paqueteAndroidElementX = 'io.element.android.x';

Future<void> abrirElementX() async {
  final esquema = Uri.parse(_esquemaElementX);
  try {
    final abierta = await launchUrl(esquema, mode: LaunchMode.externalApplication);
    if (abierta) return;
  } catch (_) {
    // Sigue al fallback de tienda -- no hay Element X instalada o el
    // esquema no coincide en este dispositivo.
  }
  await _abrirTienda();
}

Future<void> _abrirTienda() async {
  final Uri tienda;
  if (!kIsWeb && Platform.isIOS) {
    tienda = Uri.parse('https://apps.apple.com/app/id$_idAppStoreElementX');
  } else if (!kIsWeb && Platform.isAndroid) {
    tienda = Uri.parse('https://play.google.com/store/apps/details?id=$_paqueteAndroidElementX');
  } else {
    tienda = Uri.parse('https://element.io/download');
  }
  await launchUrl(tienda, mode: LaunchMode.externalApplication);
}
