import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../screens/ia_chat_screen.dart';
import 'servicios.dart';

/// Abre el chat del asistente desde cualquier pantalla. [consulta] se envía nada más abrirlo
/// (las sugerencias de un toque) y [contexto] dice de qué trata la conversación («Tareas»…).
Future<void> abrirAsistente(BuildContext context, WidgetRef ref, {String? consulta, String? contexto}) {
  final s = ref.read(serviciosProvider);
  return Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => IaChatScreen(api: s.api, locale: s.locale, consultaInicial: consulta, contexto: contexto),
  ));
}
