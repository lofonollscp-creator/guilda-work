import 'package:flutter/material.dart';

/// Botón primario/secundario con estado de carga integrado -- sustituye al
/// patrón repetido "if (cargando) spinner else Text(...)" que había suelto
/// en login_screen, ia_chat_screen, ia_ajustes_screen, fichaje_screen...
/// (Fase 5 del plan "eventual-herding-kitten"). El estilo en sí (color,
/// radio, tipografía) ya viene del FilledButtonTheme/OutlinedButtonTheme
/// globales definidos en theme/app_theme.dart -- este widget solo evita
/// repetir la lógica del spinner.
class AppButton extends StatelessWidget {
  final String texto;
  final VoidCallback? onPressed;
  final bool cargando;
  final bool secundario;
  final IconData? icono;

  const AppButton({
    super.key,
    required this.texto,
    required this.onPressed,
    this.cargando = false,
    this.secundario = false,
    this.icono,
  });

  @override
  Widget build(BuildContext context) {
    final deshabilitado = cargando || onPressed == null;
    final child = cargando
        ? SizedBox(
            height: 18,
            width: 18,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: secundario ? Theme.of(context).colorScheme.onSurface : Theme.of(context).colorScheme.onPrimary,
            ),
          )
        : icono != null
            ? Row(
                mainAxisSize: MainAxisSize.min,
                children: [Icon(icono, size: 18), const SizedBox(width: 8), Text(texto)],
              )
            : Text(texto);

    return secundario
        ? OutlinedButton(onPressed: deshabilitado ? null : onPressed, child: child)
        : FilledButton(onPressed: deshabilitado ? null : onPressed, child: child);
  }
}
