import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../diseno/asistente.dart';
import '../../l10n/app_localizations.dart';
import '../../models/models.dart';

/// De qué tipo de elemento se habla en la conversación (según el contexto que se le da al asistente: `tarea #7`, `nota #3`, `correo, mensaje #9`).
enum TipoContextoIa { tarea, nota, correo, ninguno }

TipoContextoIa tipoDeContextoIa(String? contextoIa) {
  final c = contextoIa ?? '';
  if (c.startsWith('tarea')) return TipoContextoIa.tarea;
  if (c.startsWith('nota')) return TipoContextoIa.nota;
  if (c.startsWith('correo')) return TipoContextoIa.correo;
  return TipoContextoIa.ninguno;
}

/// Las sugerencias de un toque según lo que tienes delante: sobre un correo, resumirlo o contestarlo; sobre una tarea, resumirla; y, sin nada concreto, las de siempre.
List<String> sugerenciasDeContexto(AppLocalizations t, String? contextoIa) => switch (tipoDeContextoIa(contextoIa)) {
      TipoContextoIa.correo => [t.iaSugCorreoResumir, t.iaSugCorreoResponder, t.iaSugCorreoTarea],
      TipoContextoIa.tarea => [t.iaSugTareaResumir, t.iaSugTareaFalta, t.iaSugTareaSubtareas],
      TipoContextoIa.nota => [t.iaSugNotaResumir, t.iaSugNotaTareas],
      TipoContextoIa.ninguno => [t.iaSugerencia1, t.iaSugerencia2, t.iaSugerencia3, t.iaSugerencia4],
    };

/// ¿Habla de importes, modelos o plazos fiscales? Ahí, y solo ahí, se pone la etiqueta de cautela.
bool contieneCifrasFiscales(String texto) => RegExp(r'\d[\d.,]*\s?€|€\s?\d|\b(modelo|IVA|IRPF|303|130|111|115|390|200)\b', caseSensitive: false).hasMatch(texto);

/// El nombre humano de lo que va a hacer el asistente (`crear_tarea` → «Nueva tarea»); lo que no se conoce se escribe legible (`marcar_leido_correo` → «Marcar leido correo»).
String nombreAccionIa(AppLocalizations t, String herramienta) {
  switch (herramienta) {
    case 'crear_tarea':
      return t.iaAccionCrearTarea;
    case 'crear_nota':
      return t.iaAccionCrearNota;
    case 'editar_tarea':
      return t.iaAccionEditarTarea;
    case 'editar_nota':
      return t.iaAccionEditarNota;
    case 'completar_tarea':
      return t.iaAccionCompletarTarea;
    case 'enviar_correo':
      return t.iaAccionEnviarCorreo;
  }
  final legible = herramienta.replaceAll('_', ' ').trim();
  return legible.isEmpty ? herramienta : legible[0].toUpperCase() + legible.substring(1);
}

String etiquetaCampoIa(String clave) {
  final legible = clave.replaceAll('_', ' ').trim();
  return legible.isEmpty ? clave : legible[0].toUpperCase() + legible.substring(1);
}

/// Preferencia local: «Recordarme revisar las cifras fiscales» (la etiqueta de cautela junto a importes y plazos). Por defecto, sí.
class RecordarCifras {
  RecordarCifras._();
  static const _clave = 'ia_recordar_cifras';

  static Future<bool> leer() async {
    try {
      return (await SharedPreferences.getInstance()).getBool(_clave) ?? true;
    } catch (_) {
      return true;
    }
  }

  static Future<void> guardar(bool valor) async {
    try {
      await (await SharedPreferences.getInstance()).setBool(_clave, valor);
    } catch (_) {
      // sin almacenamiento: se queda como estaba
    }
  }
}

/// La etiqueta ámbar «Cifra estimada: compruébala…» que acompaña a una respuesta con importes o plazos fiscales.
class CautelaFiscal extends StatelessWidget {
  const CautelaFiscal({super.key});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final oscuro = Theme.of(context).brightness == Brightness.dark;
    final color = oscuro ? const Color(0xFFFFD27A) : const Color(0xFF7A4B00);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(color: color.withValues(alpha: oscuro ? 0.16 : 0.14), borderRadius: BorderRadius.circular(10)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        ExcludeSemantics(child: Icon(Icons.info_outline, size: 15, color: color)),
        const SizedBox(width: 6),
        Flexible(child: Text(t.iaCautela, style: Theme.of(context).textTheme.labelMedium?.copyWith(color: color, fontWeight: FontWeight.w700))),
      ]),
    );
  }
}

/// «3 fuentes»: plegado por defecto; al tocarlo, cada fuente como fila que se abre.
class FuentesPlegables extends StatefulWidget {
  final List<IaFuente> fuentes;
  final void Function(IaFuente) alAbrir;
  const FuentesPlegables({super.key, required this.fuentes, required this.alAbrir});

  @override
  State<FuentesPlegables> createState() => _FuentesPlegablesState();
}

class _FuentesPlegablesState extends State<FuentesPlegables> {
  bool _abierto = false;

  IconData _icono(String tipo) => switch (tipo) {
        'tarea' => Icons.task_alt,
        'nota' => Icons.sticky_note_2_outlined,
        'correo' => Icons.mail_outline,
        'vencimiento' => Icons.event_note_outlined,
        _ => Icons.folder_open_outlined,
      };

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final c = ColoresIa.de(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Semantics(
        button: true,
        expanded: _abierto,
        child: InkWell(
          onTap: () => setState(() => _abierto = !_abierto),
          borderRadius: BorderRadius.circular(10),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              ExcludeSemantics(child: Icon(_abierto ? Icons.expand_less : Icons.chevron_right, size: 18, color: tema.colorScheme.onSurfaceVariant)),
              const SizedBox(width: 2),
              Text(t.iaFuentesN(widget.fuentes.length), style: tema.textTheme.labelLarge?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
            ]),
          ),
        ),
      ),
      if (_abierto)
        for (final f in widget.fuentes)
          InkWell(
            onTap: () => widget.alAbrir(f),
            borderRadius: BorderRadius.circular(10),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 44),
              child: Row(children: [
                ExcludeSemantics(child: Icon(_icono(f.tipo), size: 18, color: c.acento)),
                const SizedBox(width: 10),
                Expanded(child: Text(f.titulo, style: tema.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600), maxLines: 2, overflow: TextOverflow.ellipsis)),
                ExcludeSemantics(child: Icon(Icons.north_east, size: 16, color: tema.colorScheme.onSurfaceVariant)),
              ]),
            ),
          ),
    ]);
  }
}

/// Copiar y leer en voz alta, discretos bajo la última respuesta.
class AccionesRespuesta extends StatelessWidget {
  final VoidCallback alCopiar;
  final VoidCallback? alLeer;
  const AccionesRespuesta({super.key, required this.alCopiar, this.alLeer});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final gris = Theme.of(context).colorScheme.onSurfaceVariant;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      IconButton(icon: Icon(Icons.copy_outlined, size: 19, color: gris), tooltip: t.iaCopiar, onPressed: alCopiar, constraints: const BoxConstraints(minWidth: 44, minHeight: 44)),
      if (alLeer != null) IconButton(icon: Icon(Icons.volume_up_outlined, size: 19, color: gris), tooltip: t.iaLeerEnVozAlta, onPressed: alLeer, constraints: const BoxConstraints(minWidth: 44, minHeight: 44)),
    ]);
  }
}

/// Mientras responde: los pasos que ha dado (con su marca) y puntos que laten, en vez de un spinner mudo.
class PasosRespuesta extends StatefulWidget {
  final List<String> hechos;
  final String? enCurso;
  const PasosRespuesta({super.key, required this.hechos, this.enCurso});

  @override
  State<PasosRespuesta> createState() => _PasosRespuestaState();
}

class _PasosRespuestaState extends State<PasosRespuesta> with SingleTickerProviderStateMixin {
  late final AnimationController _anim = AnimationController(vsync: this, duration: const Duration(milliseconds: 1200))..repeat();

  @override
  void dispose() {
    _anim.dispose();
    super.dispose();
  }

  Widget _punto(int i) => AnimatedBuilder(
        animation: _anim,
        builder: (_, _) {
          final fase = ((_anim.value * 3) - i).clamp(0.0, 3.0);
          final opacidad = 0.25 + 0.75 * (fase < 1 ? fase : (fase < 2 ? 1 - (fase - 1) : 0.0));
          return Container(
            width: 6,
            height: 6,
            margin: const EdgeInsets.only(right: 3),
            decoration: BoxDecoration(color: ColoresIa.de(context).acento.withValues(alpha: opacidad.clamp(0.25, 1.0)), shape: BoxShape.circle),
          );
        },
      );

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final texto = tema.textTheme.labelLarge?.copyWith(color: tema.colorScheme.onSurfaceVariant);
    final ok = tema.brightness == Brightness.dark ? const Color(0xFF7BD88F) : const Color(0xFF1B6B34);
    return Semantics(
      liveRegion: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final h in widget.hechos)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              ExcludeSemantics(child: Icon(Icons.check, size: 16, color: ok)),
              const SizedBox(width: 8),
              Flexible(child: Text(h, style: texto)),
            ]),
          ),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            ExcludeSemantics(child: Row(children: [_punto(0), _punto(1), _punto(2)])),
            const SizedBox(width: 6),
            Flexible(child: Text(widget.enCurso ?? AppLocalizations.of(context).iaPensando, style: texto)),
          ]),
        ),
      ]),
    );
  }
}

/// La acción que espera tu confirmación, con lo que se va a hacer a la vista: su nombre humano, los campos y los botones.
class TarjetaConfirmacion extends StatelessWidget {
  final IaPendiente pendiente;
  final bool cargando;
  final VoidCallback alConfirmar;
  final VoidCallback alRechazar;
  const TarjetaConfirmacion({super.key, required this.pendiente, required this.cargando, required this.alConfirmar, required this.alRechazar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final c = ColoresIa.de(context);
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      decoration: BoxDecoration(color: tema.colorScheme.surface, border: Border.all(color: c.borde, width: 1.5), borderRadius: BorderRadius.circular(18)),
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          color: c.fondo,
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
          child: Row(children: [
            ExcludeSemantics(child: Icon(Icons.help_outline, size: 18, color: c.acento)),
            const SizedBox(width: 8),
            Expanded(child: Text(nombreAccionIa(t, pendiente.herramienta).toUpperCase(), style: tema.textTheme.labelMedium?.copyWith(color: c.sobreFondo, fontWeight: FontWeight.w800, letterSpacing: 0.4))),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 6, 14, 2),
          child: Column(children: [
            for (final (i, e) in pendiente.argumentos.entries.indexed)
              Container(
                constraints: const BoxConstraints(minHeight: 44),
                decoration: BoxDecoration(border: i == 0 ? null : Border(top: BorderSide(color: tema.colorScheme.outlineVariant))),
                child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
                  SizedBox(width: 96, child: Text(etiquetaCampoIa(e.key), style: tema.textTheme.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis)),
                  Expanded(child: Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text('${e.value}', style: tema.textTheme.titleSmall))),
                ]),
              ),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 12),
          child: Row(children: [
            Expanded(
              child: FilledButton(
                style: FilledButton.styleFrom(backgroundColor: c.acento, foregroundColor: c.sobreAcento, shape: const StadiumBorder(), minimumSize: const Size(48, 48)),
                onPressed: cargando ? null : alConfirmar,
                child: cargando ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : Text(t.iaSiHazlo),
              ),
            ),
            const SizedBox(width: 8),
            TextButton(
              style: TextButton.styleFrom(shape: const StadiumBorder(), minimumSize: const Size(64, 48), foregroundColor: tema.colorScheme.onSurfaceVariant),
              onPressed: cargando ? null : alRechazar,
              child: const Text('No'),
            ),
          ]),
        ),
      ]),
    );
  }
}

/// «Cómo funciona el asistente»: lo que ve, lo que hace con tu permiso y que puede equivocarse. [alAjustes] abre sus ajustes.
Future<void> mostrarComoFunciona(BuildContext context, {required VoidCallback alAjustes}) async {
  final recordar = await RecordarCifras.leer();
  if (!context.mounted) return;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    builder: (c) => _HojaComoFunciona(recordarInicial: recordar, alAjustes: alAjustes),
  );
}

class _HojaComoFunciona extends StatefulWidget {
  final bool recordarInicial;
  final VoidCallback alAjustes;
  const _HojaComoFunciona({required this.recordarInicial, required this.alAjustes});

  @override
  State<_HojaComoFunciona> createState() => _HojaComoFuncionaState();
}

class _HojaComoFuncionaState extends State<_HojaComoFunciona> {
  late bool _recordar = widget.recordarInicial;

  Widget _punto(BuildContext context, IconData icono, String titulo, String texto) {
    final tema = Theme.of(context);
    final c = ColoresIa.de(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(width: 40, height: 40, decoration: BoxDecoration(color: c.fondo, borderRadius: BorderRadius.circular(13)), child: ExcludeSemantics(child: Icon(icono, size: 20, color: c.acento))),
        const SizedBox(width: 14),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(titulo, style: tema.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
          const SizedBox(height: 2),
          Text(texto, style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
        ])),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const InsigniaIa(tamano: 40),
            const SizedBox(width: 12),
            Expanded(child: Text(t.iaComoTitulo, style: tema.textTheme.titleLarge)),
          ]),
          const SizedBox(height: 6),
          _punto(context, Icons.visibility_outlined, t.iaComoVeTitulo, t.iaComoVeTexto),
          Divider(height: 1, color: tema.colorScheme.outlineVariant),
          _punto(context, Icons.check, t.iaComoHaceTitulo, t.iaComoHaceTexto),
          Divider(height: 1, color: tema.colorScheme.outlineVariant),
          _punto(context, Icons.error_outline, t.iaComoErrorTitulo, t.iaComoErrorTexto),
          const SizedBox(height: 8),
          SwitchListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 4),
            title: Text(t.iaComoRecordarTitulo, style: tema.textTheme.titleSmall),
            subtitle: Text(t.iaComoRecordarDetalle),
            value: _recordar,
            onChanged: (v) {
              setState(() => _recordar = v);
              RecordarCifras.guardar(v);
            },
          ),
          const SizedBox(height: 4),
          OutlinedButton(
            style: OutlinedButton.styleFrom(shape: const StadiumBorder(), minimumSize: const Size.fromHeight(50)),
            onPressed: () {
              Navigator.of(context).pop();
              widget.alAjustes();
            },
            child: Text(t.iaComoAjustes),
          ),
        ]),
      ),
    );
  }
}

/// Lo que hace el asistente en el modo voz.
enum EstadoVoz { escuchando, pensando, hablando }

/// El modo voz a pantalla completa: un orbe que late, lo que va captando o diciendo, y tres botones (silenciar, terminar, escribir).
class SuperficieVoz extends StatefulWidget {
  final EstadoVoz estado;
  final String texto;
  final bool silenciado;
  final VoidCallback alSilenciar;
  final VoidCallback alTerminar;
  final VoidCallback alEscribir;
  const SuperficieVoz({super.key, required this.estado, required this.texto, required this.silenciado, required this.alSilenciar, required this.alTerminar, required this.alEscribir});

  @override
  State<SuperficieVoz> createState() => _SuperficieVozState();
}

class _SuperficieVozState extends State<SuperficieVoz> with SingleTickerProviderStateMixin {
  late final AnimationController _latido = AnimationController(vsync: this, duration: const Duration(milliseconds: 2600))..repeat(reverse: true);

  @override
  void dispose() {
    _latido.dispose();
    super.dispose();
  }

  static const _fondo = Color(0xFF17143F);
  static const _lila = Color(0xFFB9B3FF);

  Widget _boton(IconData icono, String etiqueta, VoidCallback alPulsar, {bool grande = false, bool claro = false, bool marcado = false}) {
    final tam = grande ? 76.0 : 64.0;
    return Semantics(
      button: true,
      label: etiqueta,
      child: Material(
        color: claro ? Colors.white : Colors.white.withValues(alpha: marcado ? 0.3 : 0.14),
        shape: const CircleBorder(),
        child: InkWell(customBorder: const CircleBorder(), onTap: alPulsar, child: SizedBox(width: tam, height: tam, child: Icon(icono, size: grande ? 30 : 26, color: claro ? _fondo : Colors.white))),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final etiqueta = switch (widget.estado) {
      EstadoVoz.escuchando => t.iaVozEscuchando,
      EstadoVoz.pensando => t.iaVozPensando,
      EstadoVoz.hablando => t.iaVozHablando,
    };
    return Material(
      color: _fondo,
      child: SafeArea(
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
            child: Row(children: [
              IconButton(icon: const Icon(Icons.keyboard_arrow_down, color: Colors.white), tooltip: t.iaVozEscribir, onPressed: widget.alEscribir, constraints: const BoxConstraints(minWidth: 48, minHeight: 48)),
              Expanded(child: Text(t.iaVozTitulo, textAlign: TextAlign.center, style: Theme.of(context).textTheme.labelLarge?.copyWith(color: const Color(0xFFCFCBFF)))),
              const SizedBox(width: 48),
            ]),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 28),
              child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                ExcludeSemantics(
                  child: AnimatedBuilder(
                    animation: _latido,
                    builder: (_, _) => SizedBox(
                      width: 200,
                      height: 200,
                      child: Stack(alignment: Alignment.center, children: [
                        Transform.scale(scale: 1 + 0.06 * _latido.value, child: Container(decoration: BoxDecoration(shape: BoxShape.circle, color: const Color(0xFF4A3FB5).withValues(alpha: 0.35)))),
                        Transform.scale(scale: 0.74 + 0.07 * (1 - _latido.value), child: Container(decoration: BoxDecoration(shape: BoxShape.circle, color: const Color(0xFF6A5FE0).withValues(alpha: 0.6)))),
                        Container(width: 96, height: 96, decoration: const BoxDecoration(shape: BoxShape.circle, color: _lila), child: const Icon(Icons.auto_awesome, size: 44, color: _fondo)),
                      ]),
                    ),
                  ),
                ),
                const SizedBox(height: 28),
                Semantics(
                  liveRegion: true,
                  child: Text(etiqueta.toUpperCase(), style: Theme.of(context).textTheme.labelMedium?.copyWith(color: _lila, fontWeight: FontWeight.w800, letterSpacing: 1)),
                ),
                const SizedBox(height: 10),
                Text(widget.texto.isEmpty ? t.iaVozAyuda : widget.texto, textAlign: TextAlign.center, maxLines: 6, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleLarge?.copyWith(color: Colors.white, height: 1.3)),
              ]),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 28),
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              _boton(widget.silenciado ? Icons.mic_off : Icons.mic_none, t.iaVozSilenciar, widget.alSilenciar, marcado: widget.silenciado),
              const SizedBox(width: 26),
              _boton(Icons.stop_rounded, t.iaVozTerminar, widget.alTerminar, grande: true, claro: true),
              const SizedBox(width: 26),
              _boton(Icons.keyboard_outlined, t.iaVozEscribir, widget.alEscribir),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// Un hueco de conversación pasada, en «Continúa».
class FilaConversacion extends StatelessWidget {
  final String titulo;
  final String? cuando;
  final VoidCallback alAbrir;
  const FilaConversacion({super.key, required this.titulo, this.cuando, required this.alAbrir});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return InkWell(
      onTap: alAbrir,
      borderRadius: BorderRadius.circular(10),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: Row(children: [
          ExcludeSemantics(child: Icon(Icons.chat_bubble_outline, size: 18, color: tema.colorScheme.onSurfaceVariant)),
          const SizedBox(width: 10),
          Expanded(child: Text(titulo, style: tema.textTheme.titleSmall, maxLines: 1, overflow: TextOverflow.ellipsis)),
          if (cuando != null) Text(cuando!, style: tema.textTheme.bodySmall),
        ]),
      ),
    );
  }
}
