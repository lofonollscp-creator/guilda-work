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

  /// Las operaciones con una `Idempotency-Key` fija: para las acciones que pueden acabar en la cola sin conexión con esa misma clave.
  Operaciones _conClave(String? clave) => clave == null ? _o : Operaciones(_cliente.conClave(clave));

  /// Una página. `ambito`: `propias`, `asignadas`, `compartidas` o `todas`.
  /// `soloAbiertas`: como la web, sin `estado` oculta las completadas (`completadas=0`); `false` las incluye (`completadas=1`); null = lo que decida el servidor.
  Future<List<TareaOutlook>> listar({
    String ambito = 'propias',
    String? estado,
    String? q,
    int limit = 30,
    int offset = 0,
    String? prioridad,
    String? categoria,
    bool? soloAbiertas,
  }) =>
      _o.listarTareasOutlook(
        ambito: ambito,
        estado: estado,
        q: (q == null || q.trim().isEmpty) ? null : q.trim(),
        limit: limit,
        offset: offset,
        prioridad: prioridad,
        categoria: categoria,
        completadas: soloAbiertas == null ? null : (soloAbiertas ? '0' : '1'),
      );

  Future<TareaOutlook> obtener(int id) => _o.obtenerTareaOutlook(tareaId: id);

  /// `textoLibre`: el servidor interpreta el texto como el cuadro de alta de la web («viernes 10h pedir extractos @luis !alta #IVA»).
  Future<TareaOutlook> crear({required String asunto, String? fechaVencimiento, PrioridadTarea? prioridad, String? clave, bool textoLibre = false}) =>
      _conClave(clave).crearTareaOutlook(cuerpo: {
        'asunto': asunto.trim(),
        'fecha_vencimiento': ?fechaVencimiento,
        if (prioridad != null) 'prioridad': prioridad.valor,
        if (textoLibre) 'texto_libre': true,
      });

  /// A la papelera (se recupera con [restaurar]). La respuesta del servidor no trae la tarea: no se interpreta.
  Future<void> eliminar(int id) => _cliente.enviar('DELETE', '/tareas-outlook/$id');
  Future<void> restaurar(int id) => _cliente.enviar('POST', '/tareas-outlook/$id/restaurar');

  /// Una acción sobre varias tareas (`completar`, `estado`, `prioridad`, `fecha`...). Cada una con sus permisos: devuelve cuántas se hicieron y cuántas no.
  Future<({int ok, int fallos})> lote(List<int> ids, String accion, {String? valor}) async {
    final r = await _o.accionEnLote(cuerpo: {'ids': ids, 'accion': accion, 'valor': ?valor});
    return (ok: r.ok ?? 0, fallos: r.fallos ?? 0);
  }

  Future<List<Vista>> vistas() => _o.listarVistas();
  Future<Vista> guardarVista(String nombre, Map<String, String> filtros) => _o.guardarVista(cuerpo: {'nombre': nombre.trim(), 'filtros': filtros});
  Future<void> eliminarVista(int id) => _o.eliminarVista(vistaId: id);

  /// Las categorías (estilo Outlook) que ya usan las tareas: lo que admite el filtro de categoría.
  Future<List<String>> categoriasOutlook() async => [for (final c in (await _o.categoriasOutlook() as List? ?? const [])) c.toString()];

  Future<TareaOutlook> editar(int id, {String? asunto, String? cuerpo, PrioridadTarea? prioridad, String? fechaVencimiento}) => _o.editarTareaOutlook(tareaId: id, cuerpo: {
        'asunto': ?asunto,
        'cuerpo': ?cuerpo,
        if (prioridad != null) 'prioridad': prioridad.valor,
        'fecha_vencimiento': ?fechaVencimiento,
      });

  /// Cambia el estado. Con `version` solo vale si nadie ha tocado la tarea (si no, `ApiException` de conflicto con `versionActual`).
  Future<TareaOutlook> transicionar(int id, EstadoTarea estado, {String? motivo, int? version, String? clave}) => _conClave(clave).transicionarTarea(tareaId: id, cuerpo: {
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
  Future<void> comentar(int id, String texto, {String? clave}) => _conClave(clave).comentarTarea(tareaId: id, cuerpo: {'texto': texto.trim()});

  Future<List<AdjuntoTarea>> adjuntos(int id) => _o.adjuntosDeLaTarea(tareaId: id);

  /// Sube un archivo (multipart, campo `adjunto`; 15 MB como máximo, lo valida el servidor).
  Future<void> subirAdjunto(int id, MultipartFile archivo) => _o.subirAdjuntosDeLaTarea(tareaId: id, cuerpo: {'adjunto': archivo});

  Future<List<int>> descargarAdjunto(int adjuntoId) => _o.descargarAdjuntoDeTarea(adjuntoId: adjuntoId);
  Future<void> eliminarAdjunto(int adjuntoId) => _o.eliminarAdjuntoDeTarea(adjuntoId: adjuntoId);
}

final tareasRepositorioProvider = Provider<TareasRepositorio>((ref) => TareasRepositorio(ref.read(clienteApiProvider)));
