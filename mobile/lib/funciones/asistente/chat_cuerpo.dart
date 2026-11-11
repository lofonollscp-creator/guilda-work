import 'package:flutter/material.dart';

import '../../diseno/asistente.dart';
import '../../diseno/componentes.dart';
import '../../l10n/app_localizations.dart';
import '../../models/models.dart';
import '../../services/api_client.dart';
import '../../theme/brand_colors.dart';
import 'asistente_controlador.dart';
import 'asistente_piezas.dart';

/// El texto de un error del asistente: el que mandó el servidor tal cual, el de una [ApiException] según su categoría y, para cualquier otra cosa, el de red.
String textoDeErrorAsistente(AppLocalizations t, Object error) {
  if (error is String) return error;
  if (error is ApiException) return mensajeDeError(t, error);
  return t.errRed;
}

/// Lo que se ve de la conversación: la pantalla de inicio si está en blanco (sugerencias y conversaciones anteriores), o los mensajes con la respuesta en directo.
/// Solo lee del [AsistenteControlador]; todo lo que hace algo lo pide por las funciones que recibe.
class ChatCuerpo extends StatelessWidget {
  final AsistenteControlador c;
  final ScrollController scroll;

  /// Lo que mide el chat (pantalla o panel): los mensajes se limitan a un tanto de ello.
  final double ancho;

  /// De qué trata la conversación («Tareas»…), para «Ahora mismo · …» en la pantalla de inicio.
  final String? contexto;
  final VoidCallback alMostrarInfo;
  final ValueChanged<String> alEnviar;
  final ValueChanged<IaConversacion> alRetomar;
  final ValueChanged<IaFuente> alAbrirFuente;
  final ValueChanged<String> alCopiar;
  const ChatCuerpo({
    super.key,
    required this.c,
    required this.scroll,
    required this.ancho,
    required this.contexto,
    required this.alMostrarInfo,
    required this.alEnviar,
    required this.alRetomar,
    required this.alAbrirFuente,
    required this.alCopiar,
  });

  @override
  Widget build(BuildContext context) {
    if (c.cargando) return const Center(child: CircularProgressIndicator());
    final errorCarga = c.errorCarga;
    if (errorCarga != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(textoDeErrorAsistente(AppLocalizations.of(context), errorCarga), textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: c.cargarHistorial, child: Text(AppLocalizations.of(context).estadoVacioReintentar)),
            ],
          ),
        ),
      );
    }
    if (c.enBlanco) return _Inicio(c: c, contexto: contexto, alMostrarInfo: alMostrarInfo, alEnviar: alEnviar, alRetomar: alRetomar);
    return _Mensajes(c: c, scroll: scroll, ancho: ancho, alAbrirFuente: alAbrirFuente, alCopiar: alCopiar);
  }
}

/// La conversación en blanco: título, sugerencias de un toque (las de la pantalla desde la que se abrió) y «Continúa» con las conversaciones anteriores.
class _Inicio extends StatelessWidget {
  final AsistenteControlador c;
  final String? contexto;
  final VoidCallback alMostrarInfo;
  final ValueChanged<String> alEnviar;
  final ValueChanged<IaConversacion> alRetomar;
  const _Inicio({required this.c, required this.contexto, required this.alMostrarInfo, required this.alEnviar, required this.alRetomar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final bloqueado = c.enviando || c.pendiente != null;
    final sugerencias = sugerenciasDeContexto(t, c.contextoVisible ? c.contextoIa : null);
    final iconos = [Icons.today_outlined, Icons.mail_outline, Icons.event_note_outlined, Icons.edit_note];
    final anteriores = c.conversaciones.where((x) => !x.activa && (x.titulo ?? '').isNotEmpty).take(3).toList();
    return ListView(padding: const EdgeInsets.fromLTRB(20, 24, 20, 16), children: [
      const Align(alignment: Alignment.centerLeft, child: InsigniaIa(tamano: 48)),
      const SizedBox(height: 14),
      Text(t.iaInicioTitulo, style: tema.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Text(t.iaVacioTexto, style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
      const SizedBox(height: 22),
      EtiquetaSeccion(contexto == null ? t.iaSugerenciasTitulo : t.iaAhoraMismo(contexto!), padding: const EdgeInsets.fromLTRB(2, 0, 2, 8)),
      Material(
        color: tema.colorScheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          for (final (i, texto) in sugerencias.indexed)
            InkWell(
              onTap: bloqueado ? null : () => alEnviar(texto),
              child: Container(
                constraints: const BoxConstraints(minHeight: 60),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(border: i == 0 ? null : Border(top: BorderSide(color: tema.colorScheme.outlineVariant))),
                child: Row(children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(color: ColoresIa.de(context).fondo, borderRadius: BorderRadius.circular(12)),
                    child: ExcludeSemantics(child: Icon(iconos[i % iconos.length], size: 20, color: ColoresIa.de(context).acento)),
                  ),
                  const SizedBox(width: 12),
                  Expanded(child: Text(texto, style: tema.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
                ]),
              ),
            ),
        ]),
      ),
      if (anteriores.isNotEmpty) ...[
        EtiquetaSeccion(t.iaContinua, padding: const EdgeInsets.fromLTRB(2, 22, 2, 4)),
        for (final x in anteriores) FilaConversacion(titulo: x.titulo!, alAbrir: () => alRetomar(x)),
      ],
      const SizedBox(height: 18),
      // El aviso, una sola vez y sin banner: una línea pequeña con su enlace.
      Center(
        child: Wrap(alignment: WrapAlignment.center, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text('${t.iaPieAviso} ', style: tema.textTheme.bodySmall),
          TextButton(
            style: TextButton.styleFrom(minimumSize: const Size(48, 44), padding: const EdgeInsets.symmetric(horizontal: 6), foregroundColor: ColoresIa.de(context).acento),
            onPressed: alMostrarInfo,
            child: Text(t.iaComoFunciona, style: tema.textTheme.labelLarge?.copyWith(color: ColoresIa.de(context).acento)),
          ),
        ]),
      ),
    ]);
  }
}

/// Los mensajes, con la respuesta en directo (o los pasos del asistente) al final.
class _Mensajes extends StatelessWidget {
  final AsistenteControlador c;
  final ScrollController scroll;
  final double ancho;
  final ValueChanged<IaFuente> alAbrirFuente;
  final ValueChanged<String> alCopiar;
  const _Mensajes({required this.c, required this.scroll, required this.ancho, required this.alAbrirFuente, required this.alCopiar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final mensajes = c.mensajes;
    final enviando = c.enviando;
    // Lo que el asistente va haciendo en el turno en curso (consultas) se muestra como pasos al final, no mezclado con los mensajes.
    final visibles = [for (final (i, m) in mensajes.indexed) if (!(enviando && i >= c.inicioTurno && m.rol == 'tool')) m];
    final pasosHechos = enviando ? [for (final m in mensajes.skip(c.inicioTurno)) if (m.rol == 'tool') textoMensajeTool(t, m)] : <String>[];
    final ultimoAsistente = visibles.lastIndexWhere((m) => m.rol == 'assistant' && (m.contenido ?? '').isNotEmpty);
    final hayTextoVivo = c.textoVivo != null;
    return ListView.builder(
      controller: scroll,
      padding: const EdgeInsets.all(12),
      itemCount: visibles.length + (hayTextoVivo || enviando ? 1 : 0),
      itemBuilder: (context, i) {
        if (i >= visibles.length) {
          return _Asistente(ancho: ancho, child: hayTextoVivo ? Text(c.textoVivo ?? '') : PasosRespuesta(hechos: pasosHechos));
        }
        return _Burbuja(c: c, mensaje: visibles[i], ancho: ancho, esUltima: i == ultimoAsistente && !enviando, alAbrirFuente: alAbrirFuente, alCopiar: alCopiar);
      },
    );
  }
}

/// El mensaje del asistente: su insignia a la izquierda y el texto sobre el fondo, sin caja (lo tuyo va en la burbuja con el acento, a la derecha).
class _Asistente extends StatelessWidget {
  final double ancho;
  final Widget child;
  const _Asistente({required this.ancho, required this.child});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: ancho - 24),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Padding(padding: EdgeInsets.only(right: 10, top: 2), child: InsigniaIa(tamano: 26)),
            Expanded(child: child),
          ]),
        ),
      ),
    );
  }
}

class _Burbuja extends StatelessWidget {
  final AsistenteControlador c;
  final IaMensaje mensaje;
  final double ancho;
  final bool esUltima;
  final ValueChanged<IaFuente> alAbrirFuente;
  final ValueChanged<String> alCopiar;
  const _Burbuja({required this.c, required this.mensaje, required this.ancho, required this.esUltima, required this.alAbrirFuente, required this.alCopiar});

  /// Lo que escribiste; si iba con un archivo, su nombre sale arriba como una píldora y no la línea técnica `[Adjunto #…]`.
  Widget _contenidoUsuario(BuildContext context, String contenido) {
    final color = Theme.of(context).colorScheme.onPrimary;
    contenido = quitarContextoDelTexto(contenido);
    final partes = separarAdjuntoDelTexto(contenido);
    if (partes == null) return Text(contenido, style: TextStyle(color: color));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Row(mainAxisSize: MainAxisSize.min, children: [
        ExcludeSemantics(child: Icon(Icons.attach_file, size: 16, color: color)),
        const SizedBox(width: 4),
        Flexible(child: Text(partes.nombre, style: TextStyle(color: color, fontWeight: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis)),
      ]),
      if (partes.texto.trim().isNotEmpty) ...[const SizedBox(height: 4), Text(partes.texto.trim(), style: TextStyle(color: color))],
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final m = mensaje;
    switch (m.rol) {
      case 'user':
        return Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 4),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            constraints: BoxConstraints(maxWidth: ancho * 0.8),
            decoration: BoxDecoration(
              color: tema.colorScheme.primary,
              borderRadius: const BorderRadius.only(topLeft: Radius.circular(18), topRight: Radius.circular(4), bottomLeft: Radius.circular(18), bottomRight: Radius.circular(18)),
            ),
            // El texto va con el color que toca sobre el acento elegido (negro o blanco según contraste), no con el del tema.
            child: _contenidoUsuario(context, m.contenido ?? ''),
          ),
        );
      case 'tool':
        // Lo que hizo el asistente por detrás, como una píldora discreta (con icono: un fallo no se distingue solo por el color).
        final texto = textoMensajeTool(AppLocalizations.of(context), m);
        final fallo = (m.contenido ?? '').contains('"error"');
        return Align(
          alignment: Alignment.center,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Pildora(icono: fallo ? Icons.error_outline : Icons.build_circle_outlined, texto: texto, color: fallo ? (tema.brightness == Brightness.dark ? BrandColors.dangerTextDark : BrandColors.dangerTextLight) : null),
          ),
        );
      case 'assistant':
      default:
        if ((m.contenido ?? '').isEmpty) return const SizedBox.shrink();
        final fuentes = m.fuentes;
        final crudo = m.contenido ?? '';
        return _Asistente(
          ancho: ancho,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            SelectableText.rich(TextSpan(children: spansMarkdownLite(context, crudo))),
            // La cautela solo donde hay importes o plazos fiscales, y si no la has silenciado.
            if (c.recordarCifras && contieneCifrasFiscales(crudo)) const Padding(padding: EdgeInsets.only(top: 8), child: CautelaFiscal()),
            if (fuentes.isNotEmpty) FuentesPlegables(fuentes: fuentes, alAbrir: alAbrirFuente),
            if (esUltima) AccionesRespuesta(alCopiar: () => alCopiar(crudo), alLeer: c.voz.disponible ? () => c.voz.hablar(crudo) : null),
          ]),
        );
    }
  }
}

/// Subconjunto de markdown ya usado por `app/static/ia_asistente.js` (negrita, cursiva, código en línea, enlaces) traducido a TextSpans. Sin tablas por ahora (poco
/// frecuentes en respuestas cortas de móvil; si hiciera falta, se puede añadir un renderer de tabla como en el JS).
List<InlineSpan> spansMarkdownLite(BuildContext context, String texto) {
  final spans = <InlineSpan>[];
  final patron = RegExp(r'(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?://[^\s)]+\))');
  var ultimo = 0;
  for (final m in patron.allMatches(texto)) {
    if (m.start > ultimo) spans.add(TextSpan(text: texto.substring(ultimo, m.start)));
    final trozo = m.group(0)!;
    if (trozo.startsWith('`')) {
      spans.add(TextSpan(
        text: trozo.substring(1, trozo.length - 1),
        style: const TextStyle(fontFamily: 'monospace', backgroundColor: Color(0x22808080)),
      ));
    } else if (trozo.startsWith('**')) {
      spans.add(TextSpan(text: trozo.substring(2, trozo.length - 2), style: const TextStyle(fontWeight: FontWeight.bold)));
    } else if (trozo.startsWith('[')) {
      final cierre = trozo.indexOf(']');
      final etiqueta = trozo.substring(1, cierre);
      spans.add(TextSpan(
        text: etiqueta,
        style: TextStyle(color: Theme.of(context).colorScheme.primary, decoration: TextDecoration.underline),
      ));
    }
    ultimo = m.end;
  }
  if (ultimo < texto.length) spans.add(TextSpan(text: texto.substring(ultimo)));
  return spans;
}
