import 'dart:convert';

/// A dónde lleva un elemento de «Hoy» o un aviso: `{tipo, id, ...}`. El servidor
/// manda el mismo formato en `GET /hoy`, en `GET /notificaciones` y en el push
/// (`data.destino`, como JSON), así que la app tiene un único sitio que lo interpreta.
class Destino {
  final String tipo;
  final int? id;
  final Map<String, dynamic> extra;
  const Destino(this.tipo, [this.id, this.extra = const {}]);

  factory Destino.desdeJson(Map<dynamic, dynamic> j) => Destino(
        j['tipo']?.toString() ?? 'aviso',
        (j['id'] as num?)?.toInt(),
        {for (final e in j.entries) if (e.key != 'tipo' && e.key != 'id') e.key.toString(): e.value},
      );

  /// Del `data` de un push. Acepta el contrato nuevo (`destino` en JSON, o `destino_tipo`/`destino_id`) y,
  /// para avisos emitidos por un servidor anterior, el `tipo` suelto (`correo_nuevo` → bandeja de correo).
  factory Destino.desdePush(Map<String, dynamic> datos) {
    final crudo = datos['destino'];
    try {
      if (crudo is String && crudo.isNotEmpty) return Destino.desdeJson(jsonDecode(crudo) as Map);
      if (crudo is Map) return Destino.desdeJson(crudo);
    } catch (_) {
      // JSON roto: se prueba lo siguiente
    }
    if (datos['destino_tipo'] != null) {
      return Destino(datos['destino_tipo'].toString(), int.tryParse('${datos['destino_id'] ?? ''}'));
    }
    return datos['tipo'] == 'correo_nuevo' ? const Destino('correo') : const Destino('aviso');
  }

  @override
  String toString() => 'Destino($tipo, $id)';
}

/// Qué hace la app con un destino. Es una decisión pura (sin pantallas) para poder
/// probarla; `abrirApertura` (en `abrir_destino.dart`) la ejecuta.
sealed class Apertura {
  const Apertura();
}

/// Abre la ficha de una tarea (se pide por id).
class AbrirTarea extends Apertura {
  final int id;
  const AbrirTarea(this.id);
}

/// Abre un correo concreto, o la bandeja si no hay id.
class AbrirCorreo extends Apertura {
  final int? id;
  const AbrirCorreo([this.id]);
}

/// Abre una nota (también una compartida).
class AbrirNota extends Apertura {
  final int id;
  const AbrirNota(this.id);
}

class AbrirVencimiento extends Apertura {
  final int id;
  const AbrirVencimiento(this.id);
}

/// Una pantalla suelta que no es una pestaña: `ausencias`, `ia`, `tiquets`.
class AbrirPantalla extends Apertura {
  final String clave;
  const AbrirPantalla(this.clave);
}

/// Una de las pestañas de la barra inferior (la ruta del enrutador).
class IrAPestana extends Apertura {
  final String ruta;
  const IrAPestana(this.ruta);
}

/// Todavía no hay pantalla nativa: se ofrece abrirlo en la web.
class SoloWeb extends Apertura {
  const SoloWeb();
}

Apertura resolverDestino(Destino d) {
  switch (d.tipo) {
    case 'tarea':
      return d.id == null ? const IrAPestana('/tareas') : AbrirTarea(d.id!);
    case 'correo':
      return AbrirCorreo(d.id ?? (d.extra['mensaje_id'] as num?)?.toInt());
    case 'nota':
      return d.id == null ? const AbrirPantalla('notas') : AbrirNota(d.id!);
    case 'vencimiento':
      return d.id == null ? const SoloWeb() : AbrirVencimiento(d.id!);
    case 'ausencias':
    case 'ausencia':
      return const AbrirPantalla('ausencias');
    case 'fichaje':
    case 'turnos':
    case 'bolsa_horas':
      return const IrAPestana('/fichaje');
    case 'hoy':
    case 'aviso':
      return const IrAPestana('/inicio');
    case 'ia':
      return const AbrirPantalla('ia');
    case 'tiquet':
      return const AbrirPantalla('tiquets');
    default:
      // plazo, expediente, visita, traspaso(s), factura, contabilizacion, certificado, aviso_fiscal...
      return const SoloWeb();
  }
}
