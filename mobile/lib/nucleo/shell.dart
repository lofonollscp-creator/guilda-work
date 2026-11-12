import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../diseno/adaptable.dart';
import '../diseno/asistente.dart';
import '../diseno/componentes.dart';
import '../l10n/app_localizations.dart';
import 'abrir_asistente.dart';
import 'barra_v3.dart';
import 'paginas.dart';
import 'rutas.dart' show rutaFichaje;
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
    final destinos = [
      (const Icon(Icons.home_outlined), const Icon(Icons.home), t.navInicio),
      (const Icon(Icons.checklist), null, t.navTareas),
      (const Icon(Icons.mail_outline), const Icon(Icons.mail), t.navCorreo),
      (const Icon(Icons.punch_clock_outlined), const Icon(Icons.punch_clock), t.navFichaje),
      (const Icon(Icons.menu), null, t.navMas),
    ];
    // Pulsar la pestaña activa vuelve a su raíz.
    void elegir(int i) => shell.goBranch(i, initialLocation: i == shell.currentIndex);
    final filo = BorderSide(color: tema.colorScheme.outlineVariant);
    if (esAncha(context)) {
      // Tableta: barra lateral con las etiquetas siempre visibles.
      return Scaffold(
        body: Row(children: [
          DecoratedBox(
            decoration: BoxDecoration(border: Border(right: filo)),
            child: NavigationRail(
              selectedIndex: shell.currentIndex,
              onDestinationSelected: elegir,
              labelType: NavigationRailLabelType.all,
              // El ✦ del asistente, arriba del raíl: en tableta abre el chat a pantalla completa (Tareas, Notas y Correo ya llevan su panel).
              leading: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: IconButton.filled(
                  tooltip: t.dashboardAsistenteIaTooltip,
                  icon: const Icon(Icons.auto_awesome),
                  style: IconButton.styleFrom(backgroundColor: ColoresIa.de(context).acento, foregroundColor: ColoresIa.de(context).sobreAcento, minimumSize: const Size(52, 52)),
                  onPressed: () => abrirAsistente(context),
                ),
              ),
              destinations: [for (final d in destinos) NavigationRailDestination(icon: d.$1, selectedIcon: d.$2, label: Text(d.$3))],
            ),
          ),
          Expanded(child: shell),
        ]),
      );
    }
    // Fichaje sale de la barra (vive en Hoy y en «Más»); sus enlaces profundos siguen llevando a su pestaña.
    const ramas = [0, 1, 2, 4];
    final enBarra = ramas.indexOf(shell.currentIndex);
    final contexto = switch (shell.currentIndex) {
      1 => t.navTareas,
      2 => t.navCorreo,
      _ => null,
    };
    return Scaffold(
      body: shell,
      bottomNavigationBar: Column(mainAxisSize: MainAxisSize.min, children: [
        BarraPideme(alPulsar: () => abrirHojaAsistente(context, contexto: contexto, enfocar: true)),
        BarraNavegacion(
          destinos: [for (final i in ramas) DestinoBarra(destinos[i].$1.icon!, (destinos[i].$2 ?? destinos[i].$1).icon!, destinos[i].$3)],
          seleccionado: enBarra < 0 ? null : enBarra,
          alElegir: (i) => elegir(ramas[i]),
          alAsistente: () => abrirAsistente(context, contexto: contexto),
        ),
      ]),
    );
  }
}

/// «Más»: el selector de despacho (solo con varios) y el resto de secciones.
class MasScreen extends ConsumerWidget {
  const MasScreen({super.key});

  String _etiqueta(AppLocalizations t, ClaveEtiqueta c) => switch (c) {
        ClaveEtiqueta.panel => t.masPanelClasico,
        ClaveEtiqueta.notas => t.masNotas,
        ClaveEtiqueta.papelera => t.masPapelera,
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
            GrupoAjustes(children: [
              FilaAjuste(
                icono: Icons.business_outlined,
                titulo: t.despachoActivoTitulo,
                subtitulo: estado.capacidades.despachoPorId(estado.despacho)?.nombre ?? '',
                final_: const Icon(Icons.unfold_more),
                alPulsar: () => _elegirDespacho(context, ref),
              ),
            ]),
          // Fichaje ya no está en la barra: aquí (y en Hoy) sigue a un toque.
          GrupoAjustes(children: [
            FilaAjuste(icono: Icons.punch_clock_outlined, titulo: t.navFichaje, final_: const Icon(Icons.chevron_right), alPulsar: () => context.go(rutaFichaje)),
          ]),
          GrupoAjustes(children: [
            for (final a in accesos)
              FilaAjuste(
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
