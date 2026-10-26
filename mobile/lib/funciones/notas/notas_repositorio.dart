import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/cliente.dart';
import '../../api/generado/modelos.g.dart';
import '../../api/generado/operaciones.g.dart';
import '../../nucleo/servicios.dart';

/// Quién ve una nota en la lista.
enum AmbitoNotas {
  todas('incluir'),
  mias(null),
  compartidas('solo');

  final String? valor;
  const AmbitoNotas(this.valor);
}

/// Todo lo que la app hace con notas contra la API (`/notas/...`), sobre el SDK generado.
class NotasRepositorio {
  final ClienteApi _cliente;
  NotasRepositorio(this._cliente);

  Operaciones get _o => Operaciones(_cliente);

  Future<List<Nota>> listar({AmbitoNotas ambito = AmbitoNotas.todas, String? q, int? proyectoId, int limit = 30, int offset = 0}) => _o.listarNotas(
        compartidas: ambito.valor,
        q: (q == null || q.trim().isEmpty) ? null : q.trim(),
        proyectoId: proyectoId,
        limit: limit,
        offset: offset,
      );

  Future<Nota> obtener(int id) => _o.obtenerNota(notaId: id);

  /// Lo que no se pasa no se toca; `titulo: ''` quita el título.
  Future<Nota> editar(int id, {String? texto, String? titulo, bool? fijada}) =>
      _o.editarNota(notaId: id, cuerpo: {'texto': ?texto, 'titulo': ?titulo, 'fijada': ?fijada});

  Future<Nota> fijar(int id, bool fijada) => _o.fijarNota(notaId: id, cuerpo: {'fijada': fijada});

  /// A la papelera; [restaurar] la recupera.
  Future<void> eliminar(int id) async {
    await _cliente.enviar('DELETE', '/notas/$id');
  }

  Future<void> restaurar(int id) => _o.restaurarDePapelera(tipo: 'nota', itemId: id);

  Future<List<Proyecto>> proyectos() => _o.listarCategorias();

  Future<List<ParticipanteNota>> compartir(int id, int usuarioId, String rol) => _o.compartirNotaCon(notaId: id, cuerpo: {'usuario_id': usuarioId, 'rol': rol});
  Future<void> dejarDeCompartir(int id, int usuarioId) => _o.dejarDeCompartirNota(notaId: id, otroId: usuarioId);

  Future<List<AdjuntoNota>> adjuntos(int id) => _o.listarAdjuntosNota(notaId: id);
  Future<void> subirAdjunto(int id, MultipartFile archivo) => _o.subirAdjuntosNota(notaId: id, cuerpo: {'adjunto': archivo});
  Future<List<int>> descargarAdjunto(int adjuntoId) => _o.descargarAdjuntoNota(adjuntoId: adjuntoId);
  Future<void> eliminarAdjunto(int adjuntoId) => _o.eliminarAdjuntoNota(adjuntoId: adjuntoId);
}

final notasRepositorioProvider = Provider<NotasRepositorio>((ref) => NotasRepositorio(ref.read(clienteApiProvider)));

/// Los proyectos del despacho, para el filtro de la lista.
final proyectosProvider = FutureProvider.autoDispose<List<Proyecto>>((ref) => ref.read(notasRepositorioProvider).proyectos());
