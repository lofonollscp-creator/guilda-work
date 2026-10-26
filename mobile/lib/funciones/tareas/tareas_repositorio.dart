import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/cliente.dart';
import '../../api/errores.dart';
import '../../api/generado/modelos.g.dart';
import '../../api/generado/operaciones.g.dart';
import '../../dominio/tarea.dart';
import '../../nucleo/servicios.dart';

/// Las secciones de «Mi día», en el orden de la web.
const seccionesMiDia = ['vencidas', 'hoy', 'en_progreso', 'asignadas', 'compartidas'];

/// Las columnas del tablero, en el orden de la web.
const columnasTablero = [EstadoTarea.noIniciada, EstadoTarea.enProgreso, EstadoTarea.completada, EstadoTarea.esperando, EstadoTarea.aplazada, EstadoTarea.enRevision];

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

  /// «Mi día»: las mismas cinco secciones que la web (`vencidas`, `hoy`, `en_progreso`, `asignadas`, `compartidas`), siempre todas, aunque vengan vacías.
  Future<Map<String, List<TareaOutlook>>> miDia() async {
    final crudo = await _cliente.enviar('GET', '/mi-dia') as Map<String, dynamic>? ?? const {};
    return {
      for (final s in seccionesMiDia) s: [for (final t in (crudo[s] as List? ?? const [])) TareaOutlook.fromJson(t as Map<String, dynamic>)],
    };
  }

  /// El tablero: una columna por estado, con las completadas más recientes (15, como la web).
  Future<Map<String, List<TareaOutlook>>> tablero({int recientes = 15}) async {
    final crudo = await _cliente.enviar('GET', '/tareas-outlook/tablero', consulta: {'recientes': recientes}) as Map<String, dynamic>? ?? const {};
    return {
      for (final e in columnasTablero) e.valor: [for (final t in (crudo[e.valor] as List? ?? const [])) TareaOutlook.fromJson(t as Map<String, dynamic>)],
    };
  }

  // --- la ficha completa (Fase 3): personas, dependencias, recordatorios, proyecto y cliente ---

  /// Edición como la web. `estimacion` es texto libre («1h30», «45 min», «2» = horas) y lo interpreta el servidor; vacío la quita.
  Future<TareaOutlook> editarFicha(
    int id, {
    String? asunto,
    String? cuerpo,
    PrioridadTarea? prioridad,
    String? estimacion,
    String? categoriaOutlook,
    String? fechaInicio,
    bool quitarInicio = false,
    String? fechaVencimiento,
    bool quitarVencimiento = false,
  }) =>
      _o.editarTareaOutlook(tareaId: id, cuerpo: {
        'asunto': ?asunto,
        'cuerpo': ?cuerpo,
        if (prioridad != null) 'prioridad': prioridad.valor,
        'estimacion': ?estimacion,
        'categoria_outlook': ?categoriaOutlook,
        if (quitarInicio) 'fecha_inicio': null else 'fecha_inicio': ?fechaInicio,
        if (quitarVencimiento) 'fecha_vencimiento': null else 'fecha_vencimiento': ?fechaVencimiento,
      });

  Future<List<Companero>> companeros() => _o.listarCompaneros();

  /// Proyectos (los tuyos) y clientes fiscales del despacho, para los selectores. Sin el módulo fiscal, los clientes vienen vacíos.
  Future<List<Proyecto>> proyectos() => _o.listarProyectos();
  Future<List<ClienteFiscal>> clientesFiscales() async {
    try {
      return await _o.listarClientesFiscales(limit: 200);
    } on ApiException {
      return const [];
    }
  }

  /// Asigna (o quita con `null`) a una persona del despacho. Solo la dueña de la tarea.
  Future<void> asignar(int id, int? companeroId) => _cliente.enviar('POST', '/tareas-outlook/$id/asignar', cuerpo: {'companero_id': companeroId});

  /// Cambia de proyecto (`null` = sin proyecto): la misma acción en lote de la web, sobre una tarea.
  Future<({int ok, int fallos})> moverAProyecto(int id, int? proyectoId) => lote([id], 'proyecto', valor: proyectoId?.toString());

  /// Cliente principal (`null` = tarea interna). Conserva los demás clientes vinculados.
  Future<void> fijarCliente(int id, int? clienteId, {List<int> otros = const []}) =>
      _cliente.enviar('PUT', '/tareas-outlook/$id/clientes', cuerpo: {'cliente_ids': [?clienteId, ...otros.where((o) => o != clienteId)], 'principal_id': clienteId});

  Future<List<ParticipanteTarea>> participantes(int id) async =>
      [for (final p in (await _cliente.enviar('GET', '/tareas-outlook/$id/compartir') as List? ?? const [])) ParticipanteTarea.desdeJson(p as Map<String, dynamic>)];
  Future<void> compartir(int id, int usuarioId, String rol) => _cliente.enviar('POST', '/tareas-outlook/$id/compartir', cuerpo: {'usuario_id': usuarioId, 'rol': rol});
  Future<void> dejarDeCompartir(int id, int usuarioId) => _cliente.enviar('DELETE', '/tareas-outlook/$id/compartir/$usuarioId');

  Future<({bool bloqueada, List<DependenciaTarea> esperaA})> dependencias(int id) async {
    final r = await _cliente.enviar('GET', '/tareas-outlook/$id/dependencias') as Map<String, dynamic>? ?? const {};
    return (bloqueada: r['bloqueada'] == true, esperaA: [for (final d in (r['depende_de'] as List? ?? const [])) DependenciaTarea.desdeJson(d as Map<String, dynamic>)]);
  }

  Future<void> esperaA(int id, int dependeDeId) => _cliente.enviar('POST', '/tareas-outlook/$id/dependencias', cuerpo: {'depende_de_id': dependeDeId});
  Future<void> quitarEspera(int id, int dependeDeId) => _cliente.enviar('DELETE', '/tareas-outlook/$id/dependencias/$dependeDeId');

  Future<List<RecordatorioTarea>> recordatorios(int id) => _o.listarRecordatorios(tareaId: id);

  Future<TiempoDeTarea> tiempo(int id) async => TiempoDeTarea.desdeJson(await _cliente.enviar('GET', '/tareas-outlook/$id/tiempo') as Map<String, dynamic>? ?? const {});

  /// Empieza a contar. `proyectoId` solo hace falta si la tarea no tiene proyecto. Devuelve el id del cronómetro.
  Future<int> iniciarCronometro(int id, {int? proyectoId}) async {
    final r = await _cliente.enviar('POST', '/tareas-outlook/$id/cronometro/iniciar', cuerpo: {'proyecto_id': ?proyectoId}) as Map<String, dynamic>;
    return (r['tarea_cronometro_id'] as num).toInt();
  }

  Future<void> pausarCronometro(int cronometroId) => _cliente.enviar('POST', '/tareas/$cronometroId/pausar');
  Future<void> reanudarCronometro(int cronometroId) => _cliente.enviar('POST', '/tareas/$cronometroId/reanudar');
  Future<void> finalizarCronometro(int cronometroId) => _cliente.enviar('POST', '/tareas/$cronometroId/finalizar');

  Future<List<ActividadDeTarea>> actividad(int id) async =>
      [for (final a in (await _cliente.enviar('GET', '/tareas-outlook/$id/actividad') as List? ?? const [])) ActividadDeTarea.desdeJson(a as Map<String, dynamic>)];

  /// Enseña (o no) la tarea al cliente en su portal; `comentarios` deja además que escriba en ella.
  Future<void> visibleParaCliente(int id, {required bool visible, bool? comentarios}) =>
      _cliente.enviar('PUT', '/tareas-outlook/$id/visible-cliente', cuerpo: {'visible': visible, 'comentarios': ?comentarios});

  /// `avisarEn` (`YYYY-MM-DDTHH:MM`) o un `atajo` relativo al vencimiento (`1d_antes`, `1h_antes`, `al_vencer`).
  Future<void> anadirRecordatorio(int id, {String? avisarEn, String? atajo, List<String> canales = const ['app']}) =>
      _cliente.enviar('POST', '/tareas-outlook/$id/recordatorios', cuerpo: {'avisar_en': ?avisarEn, 'atajo': ?atajo, 'canales': canales});
  Future<void> quitarRecordatorio(int recordatorioId) => _cliente.enviar('DELETE', '/tareas-outlook/recordatorios/$recordatorioId');

  /// `opcion`: `1h`, `manana` (9:00) o `1s` (una semana).
  Future<void> posponerRecordatorio(int recordatorioId, String opcion) => _cliente.enviar('POST', '/tareas-outlook/recordatorios/$recordatorioId/posponer', cuerpo: {'opcion': opcion});

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

/// Las personas del despacho a las que se puede asignar o compartir (para nombres y selectores). Se pide una vez.
final companerosProvider = FutureProvider.autoDispose<List<Companero>>((ref) => ref.read(tareasRepositorioProvider).companeros());
