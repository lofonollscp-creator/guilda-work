import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../l10n/app_localizations.dart';
import 'paginas.dart';
import 'sesion.dart';

/// La barra inferior: Inicio · Tareas · Correo · Fichaje · Más. Cada pestaña
/// conserva su propia pila de pantallas (`StatefulShellRoute`), así que cambiar
/// de sección ya no obliga a volver atrás hasta el inicio.
class ShellApp extends StatelessWidget {
  final StatefulNavigationShell shell;
  const ShellApp({super.key, required this.shell});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    return Scaffold(
      body: shell,
      // Un filo arriba separa la barra del contenido (sin sombra: en oscuro no se veía y en claro pesaba).
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(border: Border(top: BorderSide(color: tema.colorScheme.outlineVariant))),
        child: NavigationBar(
        selectedIndex: shell.currentIndex,
        // Pulsar la pestaña activa vuelve a su raíz.
        onDestinationSelected: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
        destinations: [
          NavigationDestination(icon: const Icon(Icons.home_outlined), selectedIcon: const Icon(Icons.home), label: t.navInicio),
          NavigationDestination(icon: const Icon(Icons.checklist), label: t.navTareas),
          NavigationDestination(icon: const Icon(Icons.mail_outline), selectedIcon: const Icon(Icons.mail), label: t.navCorreo),
          NavigationDestination(icon: const Icon(Icons.punch_clock_outlined), selectedIcon: const Icon(Icons.punch_clock), label: t.navFichaje),
          NavigationDestination(icon: const Icon(Icons.menu), label: t.navMas),
        ],
        ),
      ),
    );
  }
}

/// «Más»: el selector de despacho (solo con varios) y el resto de secciones.
class MasScreen extends ConsumerWidget {
  const MasScreen({super.key});

  String _etiqueta(AppLocalizations t, ClaveEtiqueta c) => switch (c) {
        ClaveEtiqueta.panel => t.masPanelClasico,
        ClaveEtiqueta.herramientas => t.dashboardHerramientasTooltip,
        ClaveEtiqueta.tiquets => t.dashboardTiquetsTooltip,
        ClaveEtiqueta.asistenteIa => t.dashboardAsistenteIaTooltip,
        ClaveEtiqueta.chat => t.dashboardChatTooltip,
        ClaveEtiqueta.fiscal => t.dashboardFiscalTooltip,
        ClaveEtiqueta.ajustes => t.dashboardAjustesTooltip,
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final estado = ref.watch(estadoSesionProvider);
    final usuario = estado.usuario;
    final accesos = usuario == null ? const <AccesoMas>[] : ref.read(paginasProvider).accesosMas(ref, usuario);
    return Scaffold(
      appBar: AppBar(title: Text(t.masTitulo)),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          if (estado.capacidades.variosDespachos)
            _TarjetaMas(children: [
              _FilaMas(
                icono: Icons.business_outlined,
                titulo: t.despachoActivoTitulo,
                subtitulo: estado.capacidades.despachoPorId(estado.despacho)?.nombre ?? '',
                final_: const Icon(Icons.unfold_more),
                alPulsar: () => _elegirDespacho(context, ref),
              ),
            ]),
          _TarjetaMas(children: [
            for (final a in accesos)
              _FilaMas(
                icono: a.icono,
                titulo: _etiqueta(t, a.etiqueta),
                final_: const Icon(Icons.chevron_right),
                alPulsar: () => a.construir != null ? Navigator.of(context).push(MaterialPageRoute(builder: a.construir!)) : a.alPulsar?.call(),
              ),
          ]),
        ],
      ),
    );
  }

  Future<void> _elegirDespacho(BuildContext context, WidgetRef ref) async {
    final t = AppLocalizations.of(context);
    final estado = ref.read(estadoSesionProvider);
    final id = await showModalBottomSheet<String>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(title: Text(t.despachoCambiarTitulo, style: Theme.of(context).textTheme.titleMedium)),
          for (final d in estado.capacidades.despachos)
            ListTile(
              leading: Icon(d.id == estado.despacho ? Icons.radio_button_checked : Icons.radio_button_unchecked),
              title: Text(d.nombre),
              subtitle: d.principal ? Text(t.despachoPrincipal) : null,
              onTap: () => Navigator.pop(context, d.id),
            ),
        ]),
      ),
    );
    if (id != null) await ref.read(estadoSesionProvider.notifier).cambiarDespacho(id);
  }
}

/// Un grupo de accesos en una tarjeta, con filo entre ellos.
class _TarjetaMas extends StatelessWidget {
  final List<Widget> children;
  const _TarjetaMas({required this.children});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: tema.colorScheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          for (var i = 0; i < children.length; i++) ...[if (i > 0) Divider(height: 1, indent: 64, color: tema.colorScheme.outlineVariant), children[i]],
        ]),
      ),
    );
  }
}

/// Un acceso de «Más»: su icono en un círculo con el tinte del acento, el nombre y, a la derecha, una flecha.
class _FilaMas extends StatelessWidget {
  final IconData icono;
  final String titulo;
  final String? subtitulo;
  final Widget? final_;
  final VoidCallback alPulsar;
  const _FilaMas({required this.icono, required this.titulo, this.subtitulo, this.final_, required this.alPulsar});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return ListTile(
      minTileHeight: 56,
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(color: tema.colorScheme.primary.withValues(alpha: tema.brightness == Brightness.dark ? 0.22 : 0.30), shape: BoxShape.circle),
        child: ExcludeSemantics(child: Icon(icono, size: 22, color: tema.colorScheme.onSurface)),
      ),
      title: Text(titulo, style: tema.textTheme.titleSmall),
      subtitle: subtitulo == null ? null : Text(subtitulo!),
      trailing: final_,
      onTap: alPulsar,
    );
  }
}
