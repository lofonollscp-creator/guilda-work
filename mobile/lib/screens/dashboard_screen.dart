import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../services/push_service.dart';
import '../services/session_service.dart';
import '../services/element_launcher.dart';
import '../services/locale_service.dart';
import '../services/sync_service.dart';
import '../services/theme_service.dart';
import '../widgets/app_card.dart';
import 'ajustes_screen.dart';
import 'correo_bandeja_screen.dart';
import 'fichaje_screen.dart';
import 'fiscal_screen.dart';
import 'herramientas_screen.dart';
import 'historial_rapido_screen.dart';
import 'ia_chat_screen.dart';
import 'menu_detail_screen.dart';
import 'tareas_outlook_screen.dart';
import 'tiquets_screen.dart';

/// Dashboard (equivalente móvil de app/templates/inicio.html): stats del
/// día, nota rápida, una rejilla de accesos a las secciones de la app, y
/// las tarjetas de menú desde las que se entra al detalle de cada uno
/// (menu_detail_screen.dart).
///
/// La barra superior llegó a tener 10 iconos sueltos (idioma, 7 secciones,
/// ajustes, cerrar sesión) -- se quedó solo con el icono de Ajustes; el
/// resto vive ahora en la rejilla de accesos del cuerpo (más grande y con
/// etiqueta, más fácil de acertar en el móvil) o dentro de Ajustes
/// (idioma, cerrar sesión).
class DashboardScreen extends StatefulWidget {
  final Usuario usuario;
  final ApiClient api;
  final SessionService sesion;
  final SyncService sync;
  final PushService push;
  final ThemeService tema;
  final LocaleService locale;

  const DashboardScreen({
    super.key,
    required this.usuario,
    required this.api,
    required this.sesion,
    required this.sync,
    required this.push,
    required this.tema,
    required this.locale,
  });

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late Future<void> _cargaInicial;
  Map<String, dynamic>? _dashboard;
  List<Categoria> _categorias = [];
  final _notaController = TextEditingController();
  int? _categoriaNotaSeleccionada;
  bool _guardandoNota = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _cargaInicial = _cargar();
    widget.push.inicializar();
  }

  Future<void> _cargar() async {
    final resultados = await Future.wait([
      widget.api.dashboard(),
      widget.api.listarCategorias(),
    ]);
    setState(() {
      _dashboard = resultados[0] as Map<String, dynamic>;
      _categorias = resultados[1] as List<Categoria>;
    });
  }

  Future<void> _recargar() async {
    final futuro = _cargar();
    setState(() {
      _cargaInicial = futuro;
    });
    await futuro;
  }

  Future<void> _anotar() async {
    final t = AppLocalizations.of(context);
    final texto = _notaController.text.trim();
    if (texto.isEmpty) return;
    setState(() {
      _guardandoNota = true;
      _error = null;
    });
    try {
      await widget.api.crearNota(
        texto,
        categoriaId: _categoriaNotaSeleccionada,
      );
      _notaController.clear();
      await _recargar();
    } on ApiException catch (e) {
      if (e.esDeConexion) {
        await widget.sync.encolarNota(
          texto,
          _categoriaNotaSeleccionada,
          DateTime.now(),
        );
        _notaController.clear();
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(t.dashboardSinConexionNota)));
        }
      } else {
        setState(() => _error = e.toString());
      }
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _guardandoNota = false);
    }
  }

  Future<void> _crearMenu() async {
    final t = AppLocalizations.of(context);
    final controlador = TextEditingController();
    final nombre = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(t.dashboardNuevoMenuDialogTitulo),
        content: TextField(
          controller: controlador,
          decoration: InputDecoration(
            labelText: t.dashboardNuevoMenuDialogLabel,
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(t.comunCancelar),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controlador.text.trim()),
            child: Text(t.dashboardCrearBoton),
          ),
        ],
      ),
    );
    if (nombre == null || nombre.isEmpty) return;
    await widget.api.crearCategoria(nombre);
    await _recargar();
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Guilda Work'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: t.dashboardAjustesTooltip,
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => AjustesScreen(
                  api: widget.api,
                  usuario: widget.usuario,
                  sesion: widget.sesion,
                  sync: widget.sync,
                  push: widget.push,
                  tema: widget.tema,
                  locale: widget.locale,
                ),
              ),
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _crearMenu,
        tooltip: t.dashboardNuevoMenuTooltip,
        child: const Icon(Icons.add),
      ),
      body: FutureBuilder<void>(
        future: _cargaInicial,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(
              child: Text(t.comunErrorCargar(snapshot.error.toString())),
            );
          }
          return RefreshIndicator(
            onRefresh: _recargar,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_dashboard?['onboarding_visible'] == true) ...[
                  _tarjetaOnboarding(t),
                  const SizedBox(height: 16),
                ],
                _tarjetaStats(t),
                const SizedBox(height: 16),
                _tarjetaNotaRapida(t),
                if (_error != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    _error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                Text(
                  t.dashboardAccesosTitulo,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                _rejillaAccesos(t),
                const SizedBox(height: 24),
                Text(
                  t.dashboardTusMenus,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                if (_categorias.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 24),
                    child: Text(t.dashboardSinMenus),
                  )
                else
                  ..._categorias.map((c) => _tarjetaMenu(c, t)),
              ],
            ),
          );
        },
      ),
    );
  }

  /// Rejilla de accesos a las secciones de la app -- sustituye a los 7
  /// IconButton sueltos que antes vivían en la barra superior. Cada tarjeta
  /// es más grande y lleva etiqueta, más fácil de acertar en el móvil que
  /// un icono pequeño en una barra ya apretada.
  void _abrirPantalla(Widget Function() construir) => Navigator.of(
    context,
  ).push(MaterialPageRoute(builder: (_) => construir()));

  Widget _rejillaAccesos(AppLocalizations t) {
    final accesos = [
      (
        Icons.checklist,
        t.dashboardTareasTooltip,
        () => _abrirPantalla(() => TareasOutlookScreen(api: widget.api)),
      ),
      (
        Icons.mail_outline,
        t.dashboardCorreoTooltip,
        () => _abrirPantalla(() => CorreoBandejaScreen(api: widget.api)),
      ),
      (
        Icons.apps,
        t.dashboardHerramientasTooltip,
        () => _abrirPantalla(() => HerramientasScreen(api: widget.api)),
      ),
      (
        Icons.confirmation_number_outlined,
        t.dashboardTiquetsTooltip,
        () => _abrirPantalla(
          () => TiquetsScreen(api: widget.api, usuario: widget.usuario),
        ),
      ),
      (
        Icons.punch_clock_outlined,
        t.dashboardFichajeTooltip,
        () => _abrirPantalla(
          () => FichajeScreen(api: widget.api, sync: widget.sync),
        ),
      ),
      (
        Icons.smart_toy_outlined,
        t.dashboardAsistenteIaTooltip,
        () => _abrirPantalla(
          () => IaChatScreen(api: widget.api, locale: widget.locale),
        ),
      ),
      // A petición del usuario: "Chat de equipo" lanza la app nativa de
      // Element X (o manda a la tienda si no la tiene) en vez de abrir el
      // cliente Matrix propio de la app (chat_login_screen.dart, que se
      // deja intacto sin usar desde aquí por si se retoma más adelante).
      (Icons.chat_bubble_outline, t.dashboardChatTooltip, abrirElementX),
      // Fase F5 (calendario fiscal en móvil): solo visible con tenant
      // asignado -- primera vez que el dashboard móvil hace gating por
      // tenant, mismo criterio que ya usa la web con g.tenant_id (ver
      // app/templates/base.html).
      if (widget.usuario.tenantId != null)
        (
          Icons.calendar_month_outlined,
          t.dashboardFiscalTooltip,
          () => _abrirPantalla(() => FiscalScreen(api: widget.api)),
        ),
    ];
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 3,
      mainAxisSpacing: 8,
      crossAxisSpacing: 8,
      childAspectRatio: 0.95,
      children: accesos
          .map((a) => _accesoTile(icono: a.$1, etiqueta: a.$2, onTap: a.$3))
          .toList(),
    );
  }

  Widget _accesoTile({
    required IconData icono,
    required String etiqueta,
    required VoidCallback onTap,
  }) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icono, size: 28),
              const SizedBox(height: 8),
              Text(
                etiqueta,
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _tarjetaOnboarding(AppLocalizations t) {
    final tieneMenu = _dashboard?['onboarding_tiene_menu'] == true;
    final tieneCorreo = _dashboard?['onboarding_tiene_correo'] == true;
    final haUsadoIa = _dashboard?['onboarding_ha_usado_ia'] == true;
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 4, 0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    t.dashboardPrimerosPasos,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  TextButton(
                    onPressed: _ocultarOnboarding,
                    child: Text(t.dashboardOcultar),
                  ),
                ],
              ),
            ),
            _pasoOnboarding(
              t.dashboardPasoCrearMenu,
              tieneMenu,
              onTap: tieneMenu ? null : () => _crearMenu(),
            ),
            _pasoOnboarding(
              t.dashboardPasoConectarCorreo,
              tieneCorreo,
              onTap: tieneCorreo
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => CorreoBandejaScreen(api: widget.api),
                      ),
                    ),
            ),
            _pasoOnboarding(
              t.dashboardPasoAsistenteIa,
              haUsadoIa,
              onTap: haUsadoIa
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => IaChatScreen(
                          api: widget.api,
                          locale: widget.locale,
                        ),
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _pasoOnboarding(String texto, bool hecho, {VoidCallback? onTap}) {
    return ListTile(
      dense: true,
      leading: Icon(
        hecho ? Icons.check_circle : Icons.radio_button_unchecked,
        color: hecho ? Colors.green : Theme.of(context).disabledColor,
        size: 20,
      ),
      title: Text(
        texto,
        style: hecho
            ? TextStyle(
                decoration: TextDecoration.lineThrough,
                color: Theme.of(context).disabledColor,
              )
            : null,
      ),
      trailing: onTap != null ? const Icon(Icons.chevron_right) : null,
      onTap: onTap,
    );
  }

  Future<void> _ocultarOnboarding() async {
    try {
      await widget.api.ocultarOnboarding();
      if (!mounted) return;
      setState(
        () => _dashboard = {...?_dashboard, 'onboarding_visible': false},
      );
    } catch (_) {
      // Fallo silencioso: si la petición no llega, la tarjeta sigue
      // visible y el usuario puede volver a intentar "Ocultar" sin más.
    }
  }

  Widget _tarjetaStats(AppLocalizations t) {
    final tareasActivas = (_dashboard?['tareas_activas'] as List?)?.length ?? 0;
    final notasHoy = _dashboard?['notas_hoy'] ?? 0;
    final correosNoLeidos = _dashboard?['correos_no_leidos'] ?? 0;
    return Row(
      children: [
        Expanded(
          child: _stat(
            '$tareasActivas',
            t.dashboardStatEnCurso,
            onTap: () => _abrirPantalla(
              () => HistorialRapidoScreen(
                api: widget.api,
                filtro: FiltroHistorialRapido.enCurso,
                titulo: t.dashboardStatEnCurso,
              ),
            ),
          ),
        ),
        Expanded(
          child: _stat(
            '$notasHoy',
            t.dashboardStatNotasHoy,
            onTap: () => _abrirPantalla(
              () => HistorialRapidoScreen(
                api: widget.api,
                filtro: FiltroHistorialRapido.notasHoy,
                titulo: t.dashboardStatNotasHoy,
              ),
            ),
          ),
        ),
        Expanded(
          child: _stat(
            '$correosNoLeidos',
            t.dashboardStatCorreosSinLeer,
            onTap: () =>
                _abrirPantalla(() => CorreoBandejaScreen(api: widget.api)),
          ),
        ),
      ],
    );
  }

  Widget _stat(String valor, String etiqueta, {required VoidCallback onTap}) {
    return AppCard(
      padding: EdgeInsets.zero,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Column(
            children: [
              Text(valor, style: Theme.of(context).textTheme.headlineSmall),
              Text(
                etiqueta,
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _tarjetaNotaRapida(AppLocalizations t) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t.dashboardNotaRapidaTitulo),
            const SizedBox(height: 8),
            if (_categorias.isNotEmpty)
              DropdownButton<int?>(
                isExpanded: true,
                value: _categoriaNotaSeleccionada,
                hint: Text(t.dashboardSinMenu),
                items: [
                  DropdownMenuItem(
                    value: null,
                    child: Text(t.dashboardSinMenu),
                  ),
                  ..._categorias.map(
                    (c) => DropdownMenuItem(value: c.id, child: Text(c.nombre)),
                  ),
                ],
                onChanged: (v) =>
                    setState(() => _categoriaNotaSeleccionada = v),
              ),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _notaController,
                    decoration: InputDecoration(hintText: t.dashboardNotaHint),
                    onSubmitted: (_) => _anotar(),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _guardandoNota ? null : _anotar,
                  child: Text(t.dashboardAnotarBoton),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _tarjetaMenu(Categoria c, AppLocalizations loc) {
    final tareasActivas = (_dashboard?['tareas_activas'] as List? ?? [])
        .where((item) => item['categoria_id'] == c.id)
        .length;
    final color = _colorDesdeHex(c.color) ?? Colors.blueGrey;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: CircleAvatar(backgroundColor: color, radius: 8),
        title: Text(c.nombre),
        subtitle: tareasActivas > 0
            ? Text(loc.dashboardMenuEnCurso(tareasActivas))
            : null,
        trailing: const Icon(Icons.chevron_right),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => MenuDetailScreen(categoria: c, api: widget.api),
            ),
          );
          await _recargar();
        },
      ),
    );
  }

  Color? _colorDesdeHex(String? hex) {
    if (hex == null || !hex.startsWith('#')) return null;
    final valor = int.tryParse(hex.substring(1), radix: 16);
    if (valor == null) return null;
    return Color(0xFF000000 | valor);
  }
}
