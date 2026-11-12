import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../diseno/adaptable.dart';
import '../diseno/asistente.dart';
import '../funciones/asistente/asistente_controlador.dart';
import '../funciones/asistente/asistente_piezas.dart';
import '../funciones/asistente/chat_cuerpo.dart';
import '../funciones/asistente/chat_entrada.dart';
import '../funciones/asistente/motor_voz.dart';
import '../l10n/app_localizations.dart';
import '../models/models.dart';
import '../nucleo/abrir_destino.dart';
import '../nucleo/destinos.dart';
import '../services/api_client.dart';
import '../services/locale_service.dart';
import 'ia_ajustes_screen.dart';

/// Chat con el Asistente IA (equivalente móvil de app/templates/ia_asistente.html + app/static/ia_asistente.js). Habla con los mismos endpoints REST que ya expone
/// app/rutas_api.py (ver api_client.dart, sección «Asistente IA»): comparte historial, modelo y modo autónomo con la web; la clave de OpenRouter solo se gestiona
/// desde allí (ver IaAjustesScreen).
///
/// Envía y confirma en streaming (SSE) contra /ia/mensaje/stream y /ia/confirmar/stream y añade dictado, lectura en voz alta y un modo «Live» manos libres.
///
/// Esta pantalla es solo la piel: la conversación, el streaming y la voz viven en `funciones/asistente/` ([AsistenteControlador], [ServicioVoz]), y lo que se pinta
/// en [ChatCuerpo] y [CajaEntrada]. Aquí queda lo que es de pantalla: la barra, el selector de archivos, el portapapeles y los diálogos.
class IaChatScreen extends ConsumerStatefulWidget {
  final ApiClient api;
  final LocaleService locale;

  /// Lo que se le pide al asistente nada más abrir el chat (las sugerencias de un toque desde otras pantallas).
  final String? consultaInicial;

  /// De qué trata la conversación («Tareas»…): se muestra bajo la barra para que se sepa qué está mirando.
  final String? contexto;

  /// Lo que se le cuenta al asistente (con el primer mensaje) sobre el elemento desde el que se abrió: `tarea #7 «Presentar el 303»`.
  final String? contextoIa;

  /// Si se pasa, el chat va incrustado en un panel (tableta) en vez de a pantalla completa, y este es el aspa que lo cierra.
  final VoidCallback? alCerrar;

  const IaChatScreen({super.key, required this.api, required this.locale, this.consultaInicial, this.contexto, this.contextoIa, this.alCerrar});

  @override
  ConsumerState<IaChatScreen> createState() => _IaChatScreenState();
}

class _IaChatScreenState extends ConsumerState<IaChatScreen> {
  final _campo = TextEditingController();
  final _scroll = ScrollController();
  late final AsistenteControlador _c;
  double _ancho = 400; // lo que mide el chat (pantalla o panel): las burbujas se limitan a un tanto de él

  static const _extensionesAdjunto = ['txt', 'csv', 'tsv', 'md', 'json', 'xml', 'log'];

  @override
  void initState() {
    super.initState();
    _c = AsistenteControlador(
      api: widget.api,
      textos: () => AppLocalizations.of(context),
      motor: MotorVozReal(),
      idiomaVoz: () => widget.locale.locale.languageCode,
      contextoIa: widget.contextoIa,
      alAvanzar: _scrollAlFinal,
      alDictar: (texto) => _campo.text = texto,
      alEnviar: _campo.clear,
    )..iniciar(consultaInicial: widget.consultaInicial);
  }

  @override
  void didUpdateWidget(IaChatScreen anterior) {
    super.didUpdateWidget(anterior);
    _c.contextoIa = widget.contextoIa;
  }

  @override
  void dispose() {
    _campo.dispose();
    _scroll.dispose();
    _c.dispose();
    super.dispose();
  }

  void _scrollAlFinal() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
    });
  }

  void _enviar([String? texto]) => _c.enviar(texto ?? _campo.text);

  void _aviso(String texto, {Duration? duracion}) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(texto), duration: duracion ?? const Duration(milliseconds: 4000)));

  Future<void> _retomar(IaConversacion conversacion) async {
    final error = await _c.retomar(conversacion);
    if (error != null && mounted) _aviso(error);
  }

  Future<void> _adjuntar() async {
    final t = AppLocalizations.of(context);
    final r = await FilePicker.pickFiles(withData: true, type: FileType.custom, allowedExtensions: _extensionesAdjunto);
    final archivo = r?.files.firstOrNull;
    final bytes = archivo?.bytes;
    if (archivo == null || bytes == null) return;
    final error = await _c.subirAdjunto(bytes, archivo.name);
    if (error != null && mounted) _aviso(error is ApiException ? error.mensaje : t.iaAdjuntoError);
  }

  Future<void> _abrirFuente(IaFuente f) => ref.read(abridorDeDestinosProvider)(destinoDeFuenteIa(f.tipo, f.url), urlWeb: f.url);

  Future<void> _copiar(String texto) async {
    final t = AppLocalizations.of(context);
    await Clipboard.setData(ClipboardData(text: texto));
    if (mounted) _aviso(t.iaCopiado, duracion: const Duration(seconds: 1));
  }

  Future<void> _vaciar() async {
    final t = AppLocalizations.of(context);
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(t.iaMenuVaciar),
        content: Text(t.iaVaciarConfirmar),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(t.comunBorrar)),
        ],
      ),
    );
    if (confirmado != true) return;
    final error = await _c.vaciar();
    if (error != null && mounted) _aviso(error);
  }

  Future<void> _mostrarInfo() async {
    await mostrarComoFunciona(context, alAjustes: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => IaAjustesScreen(api: widget.api))));
    await _c.recargarRecordarCifras();
  }

  /// El menú «⋮» del chat: modo Live, ajustes del asistente y vaciar la conversación.
  Widget _menuOpciones(BuildContext context) => PopupMenuButton<String>(
        tooltip: AppLocalizations.of(context).menuMasOpciones,
        onSelected: (v) {
          switch (v) {
            case 'live':
              _c.voz.alternarLive();
            case 'ajustes':
              Navigator.of(context).push(MaterialPageRoute(builder: (_) => IaAjustesScreen(api: widget.api)));
            case 'vaciar':
              _vaciar();
          }
        },
        itemBuilder: (_) {
          final t = AppLocalizations.of(context);
          return [
            if (_c.voz.disponible) PopupMenuItem(value: 'live', child: ListTile(leading: Icon(_c.voz.liveActivo ? Icons.headset_mic : Icons.headset_mic_outlined), title: Text(t.iaMenuLive), contentPadding: EdgeInsets.zero)),
            PopupMenuItem(value: 'ajustes', child: ListTile(leading: const Icon(Icons.tune), title: Text(t.iaMenuAjustes), contentPadding: EdgeInsets.zero)),
            PopupMenuItem(value: 'vaciar', enabled: _c.mensajes.isNotEmpty, child: ListTile(leading: const Icon(Icons.delete_outline), title: Text(t.iaMenuVaciar), contentPadding: EdgeInsets.zero)),
          ];
        },
      );

  /// Lo de dentro del chat (contexto, mensajes, confirmación, atajos y campo de escritura): igual en pantalla completa y en el panel de la tableta.
  Widget _contenido(BuildContext context) => LayoutBuilder(builder: (context, k) {
        _ancho = k.maxWidth;
        final error = _c.errorTurno;
        return Column(
          children: [
            if (widget.contexto != null && _c.contextoVisible) _etiquetaContexto(context, widget.contexto!),
            Expanded(
              child: ChatCuerpo(
                c: _c,
                scroll: _scroll,
                ancho: _ancho,
                contexto: widget.contexto,
                alMostrarInfo: _mostrarInfo,
                alEnviar: _enviar,
                alRetomar: _retomar,
                alAbrirFuente: _abrirFuente,
                alCopiar: _copiar,
              ),
            ),
            if (_c.pendiente != null)
              TarjetaConfirmacion(pendiente: _c.pendiente!, cargando: _c.confirmando, alConfirmar: () => _c.confirmar(true), alRechazar: () => _c.confirmar(false)),
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: Text(textoDeErrorAsistente(AppLocalizations.of(context), error), style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            AtajosRapidos(c: _c, alEnviar: _enviar),
            CajaEntrada(c: _c, campo: _campo, alEnviar: _enviar, alAdjuntar: _adjuntar),
          ],
        );
      });

  @override
  Widget build(BuildContext context) => ListenableBuilder(listenable: _c, builder: (context, _) => _construir(context));

  Widget _construir(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final voz = _c.voz;
    // Modo voz: a pantalla completa (o en todo el panel) mientras dura.
    if (voz.liveActivo) {
      return SuperficieVoz(
        estado: voz.hablando ? EstadoVoz.hablando : (_c.enviando ? EstadoVoz.pensando : EstadoVoz.escuchando),
        texto: voz.hablando ? (_c.textoVivo ?? _c.ultimaRespuesta) : (_c.enviando ? '' : voz.textoVoz),
        silenciado: voz.silenciado,
        alSilenciar: voz.alternarSilencio,
        alTerminar: voz.alternarLive,
        alEscribir: voz.alternarLive,
      );
    }
    // En la tableta el chat vive en un panel junto a la tarea abierta: sin barra de aplicación, con su cabecera y su aspa.
    if (widget.alCerrar != null) {
      return Material(
        color: tema.colorScheme.surface,
        child: SafeArea(
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 4, 8),
              child: Row(children: [
                const InsigniaIa(tamano: 34),
                const SizedBox(width: 10),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(t.dashboardAsistenteIaTooltip, style: tema.textTheme.titleMedium), _subtituloIa(context)])),
                _botonInfo(context),
                _menuOpciones(context),
                IconButton(icon: const Icon(Icons.close), tooltip: t.iaOcultarAsistente, onPressed: widget.alCerrar),
              ]),
            ),
            Divider(height: 1, color: tema.colorScheme.outlineVariant),
            Expanded(child: _contenido(context)),
          ]),
        ),
      );
    }
    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          const InsigniaIa(tamano: 34),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(t.dashboardAsistenteIaTooltip, style: tema.textTheme.titleMedium),
              _subtituloIa(context),
            ]),
          ),
        ]),
        // Antes tres iconos sueltos; ahora un menú con nombre (la acción destructiva, «Vaciar», ya no está a un toque por error).
        actions: [_botonInfo(context), _menuOpciones(context)],
      ),
      body: AnchoMaximo(child: SafeArea(child: _contenido(context))),
    );
  }

  /// «IA · puede equivocarse»: el aviso, en el subtítulo; el botón «i» de la barra abre «Cómo funciona».
  Widget _subtituloIa(BuildContext context) =>
      Text(AppLocalizations.of(context).iaInfoSubtitulo, style: Theme.of(context).textTheme.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis);

  Widget _botonInfo(BuildContext context) => IconButton(icon: const Icon(Icons.info_outline), tooltip: AppLocalizations.of(context).iaComoFunciona, onPressed: _mostrarInfo);

  /// «Contexto: Tareas»: de qué trata esta conversación, en la píldora violeta del asistente.
  Widget _etiquetaContexto(BuildContext context, String contexto) {
    final c = ColoresIa.de(context);
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Container(
        padding: const EdgeInsets.only(left: 10),
        decoration: BoxDecoration(color: c.fondo, border: Border.all(color: c.borde), borderRadius: BorderRadius.circular(99)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          ExcludeSemantics(child: Icon(Icons.auto_awesome, size: 14, color: c.acento)),
          const SizedBox(width: 6),
          Text(AppLocalizations.of(context).iaContexto(contexto), style: Theme.of(context).textTheme.labelMedium?.copyWith(color: c.sobreFondo, fontWeight: FontWeight.w700)),
          IconButton(
            icon: Icon(Icons.close, size: 16, color: c.sobreFondo),
            tooltip: AppLocalizations.of(context).iaQuitarContexto,
            constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
            onPressed: _c.ocultarContexto,
          ),
        ]),
      ),
    );
  }
}
