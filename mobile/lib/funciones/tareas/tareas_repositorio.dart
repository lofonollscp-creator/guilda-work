import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/cliente.dart';
import '../../api/generado/modelos.g.dart';
import '../../api/generado/operaciones.g.dart';
import '../../dominio/tarea.dart';
import '../../nucleo/servicios.dart';

/// Todo lo que la app hace con tareas contra la API (`/tareas-outlook/...`).
/// Sobre el SDK generado; las pantallas no conocen rutas ni cuerpos.
class TareasRepositorio {
  final ClienteApi _cliente;
  TareasRepositorio(this._cliente);

  Operaciones get _o => Operaciones(_cliente);

  /// Una página. `ambito`: `propias`, `asignadas`, `compartidas` o `todas`.
  Future<List<TareaOutlook>> listar({String ambito = 'propias', String? estado, String? q, int limit = 30, int offset = 0}) =>
      _o.listarTareasOutlook(ambito: ambito, estado: estado, q: (q == null || q.trim().isEmpty) ? null : q.trim(), limit: limit, offset: offset);

  Future<TareaOutlook> obtener(int id) => _o.obtenerTareaOutlook(tareaId: id);

  Future<TareaOutlook> crear({required String asunto, String? fechaVencimiento, PrioridadTarea? prioridad}) => _o.crearTareaOutlook(cuerpo: {
        'asunto': asunto.trim(),
        'fecha_vencimiento': ?fechaVencimiento,
        if (prioridad != null) 'prioridad': prioridad.valor,
      });

  Future<TareaOutlook> editar(int id, {String? asunto, String? cuerpo, PrioridadTarea? prioridad, String? fechaVencimiento}) => _o.editarTareaOutlook(tareaId: id, cuerpo: {
        'asunto': ?asunto,
        'cuerpo': ?cuerpo,
        if (prioridad != null) 'prioridad': prioridad.valor,
        'fecha_vencimiento': ?fechaVencimiento,
      });

  /// Cambia el estado. Con `version` solo vale si nadie ha tocado la tarea (si no, `ApiException` de conflicto con `versionActual`).
  Future<TareaOutlook> transicionar(int id, EstadoTarea estado, {String? motivo, int? version}) => _o.transicionarTarea(tareaId: id, cuerpo: {
        'estado': estado.valor,
        'motivo': ?motivo,
        'version': ?version,
      });

  Future<({List<Subtarea> subtareas, int hechas})> subtareas(int id) async {
    final r = await _o.subtareasDeLaTarea(tareaId: id);
    final lista = [for (final m in r.subtareas ?? const <Map<String, dynamic>>[]) Subtarea.desdeJson(m)];
    return (subtareas: lista, hechas: lista.where((s) => !s.estado.abierta).length);
  }

  Future<void> crearSubtarea(int id, String asunto) => _o.crearSubtareaDeLaTarea(tareaId: id, cuerpo: {'asunto': asunto.trim()});

  Future<List<ChecklistItem>> checklist(int id) => _o.listarChecklist(tareaId: id);
  Future<void> alternarItem(int itemId) => _o.alternarItemChecklist(itemId: itemId);
  Future<void> agregarItem(int id, String texto) => _o.agregarItemChecklist(tareaId: id, cuerpo: {'texto': texto.trim()});

  Future<List<ComentarioTarea>> comentarios(int id) => _o.listarComentarios(tareaId: id, limit: 100);
  Future<void> comentar(int id, String texto) => _o.comentarTarea(tareaId: id, cuerpo: {'texto': texto.trim()});

  Future<List<AdjuntoTarea>> adjuntos(int id) => _o.adjuntosDeLaTarea(tareaId: id);

  /// Sube un archivo (multipart, campo `adjunto`; 15 MB como máximo, lo valida el servidor).
  Future<void> subirAdjunto(int id, MultipartFile archivo) => _o.subirAdjuntosDeLaTarea(tareaId: id, cuerpo: {'adjunto': archivo});

  Future<List<int>> descargarAdjunto(int adjuntoId) => _o.descargarAdjuntoDeTarea(adjuntoId: adjuntoId);
  Future<void> eliminarAdjunto(int adjuntoId) => _o.eliminarAdjuntoDeTarea(adjuntoId: adjuntoId);
}

final tareasRepositorioProvider = Provider<TareasRepositorio>((ref) => TareasRepositorio(ref.read(clienteApiProvider)));
