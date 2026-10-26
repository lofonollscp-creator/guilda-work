// GENERADO desde el OpenAPI de la API (app/sdk_dart.py, scripts/generar_sdk_dart.py). No editar a mano.
// ignore_for_file: unnecessary_question_mark

bool _aBool(Object? v) => v is bool ? v : (v is num ? v != 0 : false);

enum AdjuntoJuridicoEstado { pendiente('pendiente'), lista('lista'), fallida('fallida'), sinReconocer('');
  final String valor; const AdjuntoJuridicoEstado(this.valor);
  static AdjuntoJuridicoEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => AdjuntoJuridicoEstado.sinReconocer);
}

enum AparienciaDensidad { normal('normal'), compacta('compacta'), sinReconocer('');
  final String valor; const AparienciaDensidad(this.valor);
  static AparienciaDensidad desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => AparienciaDensidad.sinReconocer);
}

enum AparienciaIdioma { es('es'), ca('ca'), en('en'), fr('fr'), sinReconocer('');
  final String valor; const AparienciaIdioma(this.valor);
  static AparienciaIdioma desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => AparienciaIdioma.sinReconocer);
}

enum AparienciaTema { system('system'), light('light'), dark('dark'), sinReconocer('');
  final String valor; const AparienciaTema(this.valor);
  static AparienciaTema desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => AparienciaTema.sinReconocer);
}

enum BusquedaJuridicaModo { texto('texto'), hibrido('hibrido'), sinFuentes('sin_fuentes'), sinReconocer('');
  final String valor; const BusquedaJuridicaModo(this.valor);
  static BusquedaJuridicaModo desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => BusquedaJuridicaModo.sinReconocer);
}

enum CertificadoRenovacion { sinIniciar('sin_iniciar'), enGestion('en_gestion'), pendienteTitular('pendiente_titular'), obtenido('obtenido'), validado('validado'), implantado('implantado'), cerrado('cerrado'), cancelada('cancelada'), sinReconocer('');
  final String valor; const CertificadoRenovacion(this.valor);
  static CertificadoRenovacion desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => CertificadoRenovacion.sinReconocer);
}

enum CertificadoTemporal { todaviaNoVigente('todavia_no_vigente'), vigente('vigente'), caducado('caducado'), desconocido('desconocido'), sinReconocer('');
  final String valor; const CertificadoTemporal(this.valor);
  static CertificadoTemporal desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => CertificadoTemporal.sinReconocer);
}

enum ComunicadoNivel { info('info'), aviso('aviso'), critico('critico'), sinReconocer('');
  final String valor; const ComunicadoNivel(this.valor);
  static ComunicadoNivel desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => ComunicadoNivel.sinReconocer);
}

enum DestinoHoyTipo { tarea('tarea'), correo('correo'), vencimiento('vencimiento'), plazo('plazo'), expediente('expediente'), visita('visita'), traspaso('traspaso'), ausencia('ausencia'), factura('factura'), contabilizacion('contabilizacion'), certificado('certificado'), sinReconocer('');
  final String valor; const DestinoHoyTipo(this.valor);
  static DestinoHoyTipo desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => DestinoHoyTipo.sinReconocer);
}

enum ElementoHoyUrgencia { vencido('vencido'), hoy('hoy'), proximo('proximo'), info('info'), sinReconocer('');
  final String valor; const ElementoHoyUrgencia(this.valor);
  static ElementoHoyUrgencia desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => ElementoHoyUrgencia.sinReconocer);
}

enum ErrorCodigo { peticionInvalida('peticion_invalida'), tokenInvalido('token_invalido'), tokenCaducado('token_caducado'), tokenSoloLectura('token_solo_lectura'), tokenAreaNoPermitida('token_area_no_permitida'), noAutenticado('no_autenticado'), prohibido('prohibido'), sinPermiso('sin_permiso'), noEncontrado('no_encontrado'), metodoNoPermitido('metodo_no_permitido'), conflicto('conflicto'), referenciaDuplicada('referencia_duplicada'), referenciaInvalida('referencia_invalida'), vencimientoDuplicado('vencimiento_duplicado'), idempotenciaConflicto('idempotencia_conflicto'), idempotenciaEnCurso('idempotencia_en_curso'), tareaBloqueada('tarea_bloqueada'), limiteExcedido('limite_excedido'), requiere2fa('requiere_2fa'), credencialesOCodigoIncorrectos('credenciales_o_codigo_incorrectos'), ipNoPermitida('ip_no_permitida'), servicioNoDisponible('servicio_no_disponible'), valorInvalido('valor_invalido'), adjuntoInvalido('adjunto_invalido'), errorInterno('error_interno'), sinReconocer('');
  final String valor; const ErrorCodigo(this.valor);
  static ErrorCodigo desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => ErrorCodigo.sinReconocer);
}

enum EstadoServicioBaseDeDatos { ok('ok'), sinReconocer('');
  final String valor; const EstadoServicioBaseDeDatos(this.valor);
  static EstadoServicioBaseDeDatos desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => EstadoServicioBaseDeDatos.sinReconocer);
}

enum EstadoServicioEstado { ok('ok'), sinReconocer('');
  final String valor; const EstadoServicioEstado(this.valor);
  static EstadoServicioEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => EstadoServicioEstado.sinReconocer);
}

enum EtapaComercialTipo { abierta('abierta'), ganada('ganada'), perdida('perdida'), sinReconocer('');
  final String valor; const EtapaComercialTipo(this.valor);
  static EtapaComercialTipo desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => EtapaComercialTipo.sinReconocer);
}

enum ExpedienteControlPrioridad { baja('baja'), normal('normal'), alta('alta'), urgente('urgente'), sinReconocer('');
  final String valor; const ExpedienteControlPrioridad(this.valor);
  static ExpedienteControlPrioridad desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => ExpedienteControlPrioridad.sinReconocer);
}

enum FacturaContableEstado { pendiente('pendiente'), revisada('revisada'), exportada('exportada'), descartada('descartada'), sinReconocer('');
  final String valor; const FacturaContableEstado(this.valor);
  static FacturaContableEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => FacturaContableEstado.sinReconocer);
}

enum FacturaContableTipo { emitida('emitida'), recibida('recibida'), sinReconocer('');
  final String valor; const FacturaContableTipo(this.valor);
  static FacturaContableTipo desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => FacturaContableTipo.sinReconocer);
}

enum FiscalApunteLibro { emitidas('emitidas'), recibidas('recibidas'), sinReconocer('');
  final String valor; const FiscalApunteLibro(this.valor);
  static FiscalApunteLibro desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => FiscalApunteLibro.sinReconocer);
}

enum FiscalDeclaracionResumenEstado { borrador('borrador'), revisada('revisada'), exportada('exportada'), presentada('presentada'), anulada('anulada'), sinReconocer('');
  final String valor; const FiscalDeclaracionResumenEstado(this.valor);
  static FiscalDeclaracionResumenEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => FiscalDeclaracionResumenEstado.sinReconocer);
}

enum FlujoObligacionFase { pendiente('pendiente'), enPreparacion('en_preparacion'), enRevision('en_revision'), aprobada('aprobada'), presentada('presentada'), cerrada('cerrada'), noAplica('no_aplica'), anulada('anulada'), sinReconocer('');
  final String valor; const FlujoObligacionFase(this.valor);
  static FlujoObligacionFase desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => FlujoObligacionFase.sinReconocer);
}

enum HistorialOrigen { nota('nota'), tarea('tarea'), sinReconocer('');
  final String valor; const HistorialOrigen(this.valor);
  static HistorialOrigen desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => HistorialOrigen.sinReconocer);
}

enum InformeJuridicoDetalleEstado { borrador('borrador'), revisado('revisado'), archivado('archivado'), sinReconocer('');
  final String valor; const InformeJuridicoDetalleEstado(this.valor);
  static InformeJuridicoDetalleEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => InformeJuridicoDetalleEstado.sinReconocer);
}

enum InformeJuridicoEstado { borrador('borrador'), revisado('revisado'), archivado('archivado'), sinReconocer('');
  final String valor; const InformeJuridicoEstado(this.valor);
  static InformeJuridicoEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => InformeJuridicoEstado.sinReconocer);
}

enum NotificacionCanal { tareas('tareas'), correo('correo'), fiscal('fiscal'), equipo('equipo'), resumenes('resumenes'), general('general'), sinReconocer('');
  final String valor; const NotificacionCanal(this.valor);
  static NotificacionCanal desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => NotificacionCanal.sinReconocer);
}

enum OportunidadComercialDetalleEstado { abierta('abierta'), ganada('ganada'), perdida('perdida'), sinReconocer('');
  final String valor; const OportunidadComercialDetalleEstado(this.valor);
  static OportunidadComercialDetalleEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => OportunidadComercialDetalleEstado.sinReconocer);
}

enum OportunidadComercialEstado { abierta('abierta'), ganada('ganada'), perdida('perdida'), sinReconocer('');
  final String valor; const OportunidadComercialEstado(this.valor);
  static OportunidadComercialEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => OportunidadComercialEstado.sinReconocer);
}

enum PanelFiscalAmbito { todo('todo'), parcial('parcial'), sinReconocer('');
  final String valor; const PanelFiscalAmbito(this.valor);
  static PanelFiscalAmbito desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => PanelFiscalAmbito.sinReconocer);
}

enum PresentacionEstado { pendiente('pendiente'), presentado('presentado'), fueraPlazo('fuera_plazo'), sinReconocer('');
  final String valor; const PresentacionEstado(this.valor);
  static PresentacionEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => PresentacionEstado.sinReconocer);
}

enum RespuestaJuridicaStatus { answered('answered'), needsContext('needs_context'), insufficientEvidence('insufficient_evidence'), failed('failed'), enCurso('en_curso'), sinReconocer('');
  final String valor; const RespuestaJuridicaStatus(this.valor);
  static RespuestaJuridicaStatus desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => RespuestaJuridicaStatus.sinReconocer);
}

enum ReunionComercialPlantilla { cliente('cliente'), comercial('comercial'), interna('interna'), sinReconocer('');
  final String valor; const ReunionComercialPlantilla(this.valor);
  static ReunionComercialPlantilla desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => ReunionComercialPlantilla.sinReconocer);
}

enum RevisionTareaEstado { pendiente('pendiente'), aprobada('aprobada'), cambios('cambios'), cancelada('cancelada'), sinReconocer('');
  final String valor; const RevisionTareaEstado(this.valor);
  static RevisionTareaEstado desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => RevisionTareaEstado.sinReconocer);
}

enum RevisionTareaModo { todos('todos'), cualquiera('cualquiera'), cadena('cadena'), sinReconocer('');
  final String valor; const RevisionTareaModo(this.valor);
  static RevisionTareaModo desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => RevisionTareaModo.sinReconocer);
}

enum RiesgoCertificadoTipo { coberturaDesconocida('cobertura_desconocida'), caducaAntes('caduca_antes'), sinAlternativa('sin_alternativa'), sinReconocer('');
  final String valor; const RiesgoCertificadoTipo(this.valor);
  static RiesgoCertificadoTipo desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => RiesgoCertificadoTipo.sinReconocer);
}

enum TokenCreadoPermisos { completo('completo'), soloLectura('solo_lectura'), sinReconocer('');
  final String valor; const TokenCreadoPermisos(this.valor);
  static TokenCreadoPermisos desde(String s) => values.firstWhere((e) => e.valor == s, orElse: () => TokenCreadoPermisos.sinReconocer);
}

class AccesoCliente {
  final int id;
  final int? tenantId;
  final int? clienteFiscalId;
  final int? usuarioId;
  final String? accion;
  final String? detalle;
  final String? creadoEn;
  final String? usuario;
  const AccesoCliente({required this.id, this.tenantId, this.clienteFiscalId, this.usuarioId, this.accion, this.detalle, this.creadoEn, this.usuario, });
  factory AccesoCliente.fromJson(Map<String, dynamic> j) => AccesoCliente(
    id: (j['id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    accion: j['accion'] == null ? null : j['accion'] as String,
    detalle: j['detalle'] == null ? null : j['detalle'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    usuario: j['usuario'] == null ? null : j['usuario'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tenant_id': ?tenantId,
    'cliente_fiscal_id': ?clienteFiscalId,
    'usuario_id': ?usuarioId,
    'accion': ?accion,
    'detalle': ?detalle,
    'creado_en': ?creadoEn,
    'usuario': ?usuario,
  };
  AccesoCliente copyWith({int? id, int? tenantId, int? clienteFiscalId, int? usuarioId, String? accion, String? detalle, String? creadoEn, String? usuario, }) => AccesoCliente(id: id ?? this.id, tenantId: tenantId ?? this.tenantId, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, usuarioId: usuarioId ?? this.usuarioId, accion: accion ?? this.accion, detalle: detalle ?? this.detalle, creadoEn: creadoEn ?? this.creadoEn, usuario: usuario ?? this.usuario, );
  @override bool operator ==(Object other) => other is AccesoCliente && other.id == id && other.tenantId == tenantId && other.clienteFiscalId == clienteFiscalId && other.usuarioId == usuarioId && other.accion == accion && other.detalle == detalle && other.creadoEn == creadoEn && other.usuario == usuario;
  @override int get hashCode => Object.hashAll([id, tenantId, clienteFiscalId, usuarioId, accion, detalle, creadoEn, usuario]);
}

class ActividadTarea {
  final String? creadoEn;
  final String? usuario;
  final String? accion;
  final String? detalle;
  const ActividadTarea({this.creadoEn, this.usuario, this.accion, this.detalle, });
  factory ActividadTarea.fromJson(Map<String, dynamic> j) => ActividadTarea(
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    usuario: j['usuario'] == null ? null : j['usuario'] as String,
    accion: j['accion'] == null ? null : j['accion'] as String,
    detalle: j['detalle'] == null ? null : j['detalle'] as String,
  );
  Map<String, dynamic> toJson() => {
    'creado_en': ?creadoEn,
    'usuario': ?usuario,
    'accion': ?accion,
    'detalle': ?detalle,
  };
  ActividadTarea copyWith({String? creadoEn, String? usuario, String? accion, String? detalle, }) => ActividadTarea(creadoEn: creadoEn ?? this.creadoEn, usuario: usuario ?? this.usuario, accion: accion ?? this.accion, detalle: detalle ?? this.detalle, );
  @override bool operator ==(Object other) => other is ActividadTarea && other.creadoEn == creadoEn && other.usuario == usuario && other.accion == accion && other.detalle == detalle;
  @override int get hashCode => Object.hashAll([creadoEn, usuario, accion, detalle]);
}

class AdjuntoJuridico {
  final int? id;
  final String? nombre;
  final String? tipoMime;
  final int? tamano;
  final AdjuntoJuridicoEstado? estado;
  final String? error;
  final String? retenerHasta;
  final String? creadoEn;
  final int? clienteId;
  final int? expedienteId;
  final int? fragmentos;
  const AdjuntoJuridico({this.id, this.nombre, this.tipoMime, this.tamano, this.estado, this.error, this.retenerHasta, this.creadoEn, this.clienteId, this.expedienteId, this.fragmentos, });
  factory AdjuntoJuridico.fromJson(Map<String, dynamic> j) => AdjuntoJuridico(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    tipoMime: j['tipo_mime'] == null ? null : j['tipo_mime'] as String,
    tamano: j['tamano'] == null ? null : (j['tamano'] as num).toInt(),
    estado: j['estado'] == null ? null : AdjuntoJuridicoEstado.desde(j['estado'] as String),
    error: j['error'] == null ? null : j['error'] as String,
    retenerHasta: j['retener_hasta'] == null ? null : j['retener_hasta'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    expedienteId: j['expediente_id'] == null ? null : (j['expediente_id'] as num).toInt(),
    fragmentos: j['fragmentos'] == null ? null : (j['fragmentos'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
    'tipo_mime': ?tipoMime,
    'tamano': ?tamano,
    if (estado != null) 'estado': estado!.valor,
    'error': ?error,
    'retener_hasta': ?retenerHasta,
    'creado_en': ?creadoEn,
    'cliente_id': ?clienteId,
    'expediente_id': ?expedienteId,
    'fragmentos': ?fragmentos,
  };
  AdjuntoJuridico copyWith({int? id, String? nombre, String? tipoMime, int? tamano, AdjuntoJuridicoEstado? estado, String? error, String? retenerHasta, String? creadoEn, int? clienteId, int? expedienteId, int? fragmentos, }) => AdjuntoJuridico(id: id ?? this.id, nombre: nombre ?? this.nombre, tipoMime: tipoMime ?? this.tipoMime, tamano: tamano ?? this.tamano, estado: estado ?? this.estado, error: error ?? this.error, retenerHasta: retenerHasta ?? this.retenerHasta, creadoEn: creadoEn ?? this.creadoEn, clienteId: clienteId ?? this.clienteId, expedienteId: expedienteId ?? this.expedienteId, fragmentos: fragmentos ?? this.fragmentos, );
  @override bool operator ==(Object other) => other is AdjuntoJuridico && other.id == id && other.nombre == nombre && other.tipoMime == tipoMime && other.tamano == tamano && other.estado == estado && other.error == error && other.retenerHasta == retenerHasta && other.creadoEn == creadoEn && other.clienteId == clienteId && other.expedienteId == expedienteId && other.fragmentos == fragmentos;
  @override int get hashCode => Object.hashAll([id, nombre, tipoMime, tamano, estado, error, retenerHasta, creadoEn, clienteId, expedienteId, fragmentos]);
}

class AdjuntoNota {
  final int id;
  final int? notaId;
  final String? nombre;
  final String? tipoMime;
  final int? tamano;
  final String? creadoEn;
  const AdjuntoNota({required this.id, this.notaId, this.nombre, this.tipoMime, this.tamano, this.creadoEn, });
  factory AdjuntoNota.fromJson(Map<String, dynamic> j) => AdjuntoNota(
    id: (j['id'] as num).toInt(),
    notaId: j['nota_id'] == null ? null : (j['nota_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    tipoMime: j['tipo_mime'] == null ? null : j['tipo_mime'] as String,
    tamano: j['tamano'] == null ? null : (j['tamano'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'nota_id': ?notaId,
    'nombre': ?nombre,
    'tipo_mime': ?tipoMime,
    'tamano': ?tamano,
    'creado_en': ?creadoEn,
  };
  AdjuntoNota copyWith({int? id, int? notaId, String? nombre, String? tipoMime, int? tamano, String? creadoEn, }) => AdjuntoNota(id: id ?? this.id, notaId: notaId ?? this.notaId, nombre: nombre ?? this.nombre, tipoMime: tipoMime ?? this.tipoMime, tamano: tamano ?? this.tamano, creadoEn: creadoEn ?? this.creadoEn, );
  @override bool operator ==(Object other) => other is AdjuntoNota && other.id == id && other.notaId == notaId && other.nombre == nombre && other.tipoMime == tipoMime && other.tamano == tamano && other.creadoEn == creadoEn;
  @override int get hashCode => Object.hashAll([id, notaId, nombre, tipoMime, tamano, creadoEn]);
}

class AdjuntoTarea {
  final int? id;
  final String? nombreArchivo;
  final String? tipoMime;
  final int? tamanoBytes;
  final int? subidoPor;
  final String? creadoEn;
  const AdjuntoTarea({this.id, this.nombreArchivo, this.tipoMime, this.tamanoBytes, this.subidoPor, this.creadoEn, });
  factory AdjuntoTarea.fromJson(Map<String, dynamic> j) => AdjuntoTarea(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nombreArchivo: j['nombre_archivo'] == null ? null : j['nombre_archivo'] as String,
    tipoMime: j['tipo_mime'] == null ? null : j['tipo_mime'] as String,
    tamanoBytes: j['tamano_bytes'] == null ? null : (j['tamano_bytes'] as num).toInt(),
    subidoPor: j['subido_por'] == null ? null : (j['subido_por'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre_archivo': ?nombreArchivo,
    'tipo_mime': ?tipoMime,
    'tamano_bytes': ?tamanoBytes,
    'subido_por': ?subidoPor,
    'creado_en': ?creadoEn,
  };
  AdjuntoTarea copyWith({int? id, String? nombreArchivo, String? tipoMime, int? tamanoBytes, int? subidoPor, String? creadoEn, }) => AdjuntoTarea(id: id ?? this.id, nombreArchivo: nombreArchivo ?? this.nombreArchivo, tipoMime: tipoMime ?? this.tipoMime, tamanoBytes: tamanoBytes ?? this.tamanoBytes, subidoPor: subidoPor ?? this.subidoPor, creadoEn: creadoEn ?? this.creadoEn, );
  @override bool operator ==(Object other) => other is AdjuntoTarea && other.id == id && other.nombreArchivo == nombreArchivo && other.tipoMime == tipoMime && other.tamanoBytes == tamanoBytes && other.subidoPor == subidoPor && other.creadoEn == creadoEn;
  @override int get hashCode => Object.hashAll([id, nombreArchivo, tipoMime, tamanoBytes, subidoPor, creadoEn]);
}

class Apariencia {
  final AparienciaTema? tema;
  final AparienciaDensidad? densidad;
  final AparienciaIdioma? idioma;
  const Apariencia({this.tema, this.densidad, this.idioma, });
  factory Apariencia.fromJson(Map<String, dynamic> j) => Apariencia(
    tema: j['tema'] == null ? null : AparienciaTema.desde(j['tema'] as String),
    densidad: j['densidad'] == null ? null : AparienciaDensidad.desde(j['densidad'] as String),
    idioma: j['idioma'] == null ? null : AparienciaIdioma.desde(j['idioma'] as String),
  );
  Map<String, dynamic> toJson() => {
    if (tema != null) 'tema': tema!.valor,
    if (densidad != null) 'densidad': densidad!.valor,
    if (idioma != null) 'idioma': idioma!.valor,
  };
  Apariencia copyWith({AparienciaTema? tema, AparienciaDensidad? densidad, AparienciaIdioma? idioma, }) => Apariencia(tema: tema ?? this.tema, densidad: densidad ?? this.densidad, idioma: idioma ?? this.idioma, );
  @override bool operator ==(Object other) => other is Apariencia && other.tema == tema && other.densidad == densidad && other.idioma == idioma;
  @override int get hashCode => Object.hashAll([tema, densidad, idioma]);
}

class Archivada {
  final bool? archivada;
  const Archivada({this.archivada, });
  factory Archivada.fromJson(Map<String, dynamic> j) => Archivada(
    archivada: j['archivada'] == null ? null : _aBool(j['archivada']),
  );
  Map<String, dynamic> toJson() => {
    'archivada': ?archivada,
  };
  Archivada copyWith({bool? archivada, }) => Archivada(archivada: archivada ?? this.archivada, );
  @override bool operator ==(Object other) => other is Archivada && other.archivada == archivada;
  @override int get hashCode => Object.hashAll([archivada]);
}

class AtajoIA {
  final int? id;
  final int? usuarioId;
  final String? titulo;
  final String? prompt;
  final String? creadoEn;
  const AtajoIA({this.id, this.usuarioId, this.titulo, this.prompt, this.creadoEn, });
  factory AtajoIA.fromJson(Map<String, dynamic> j) => AtajoIA(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    prompt: j['prompt'] == null ? null : j['prompt'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'usuario_id': ?usuarioId,
    'titulo': ?titulo,
    'prompt': ?prompt,
    'creado_en': ?creadoEn,
  };
  AtajoIA copyWith({int? id, int? usuarioId, String? titulo, String? prompt, String? creadoEn, }) => AtajoIA(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, titulo: titulo ?? this.titulo, prompt: prompt ?? this.prompt, creadoEn: creadoEn ?? this.creadoEn, );
  @override bool operator ==(Object other) => other is AtajoIA && other.id == id && other.usuarioId == usuarioId && other.titulo == titulo && other.prompt == prompt && other.creadoEn == creadoEn;
  @override int get hashCode => Object.hashAll([id, usuarioId, titulo, prompt, creadoEn]);
}

class Ausencia {
  final int id;
  final int? usuarioId;
  final String? tipo;
  final String? desde;
  final String? hasta;
  final int? medioDia;
  final double? dias;
  final String? motivo;
  final String? estado;
  final String? resueltaEn;
  final String? comentario;
  final String? creadaEn;
  final String? persona;
  const Ausencia({required this.id, this.usuarioId, this.tipo, this.desde, this.hasta, this.medioDia, this.dias, this.motivo, this.estado, this.resueltaEn, this.comentario, this.creadaEn, this.persona, });
  factory Ausencia.fromJson(Map<String, dynamic> j) => Ausencia(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    desde: j['desde'] == null ? null : j['desde'] as String,
    hasta: j['hasta'] == null ? null : j['hasta'] as String,
    medioDia: j['medio_dia'] == null ? null : (j['medio_dia'] as num).toInt(),
    dias: j['dias'] == null ? null : (j['dias'] as num).toDouble(),
    motivo: j['motivo'] == null ? null : j['motivo'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    resueltaEn: j['resuelta_en'] == null ? null : j['resuelta_en'] as String,
    comentario: j['comentario'] == null ? null : j['comentario'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    persona: j['persona'] == null ? null : j['persona'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'tipo': ?tipo,
    'desde': ?desde,
    'hasta': ?hasta,
    'medio_dia': ?medioDia,
    'dias': ?dias,
    'motivo': ?motivo,
    'estado': ?estado,
    'resuelta_en': ?resueltaEn,
    'comentario': ?comentario,
    'creada_en': ?creadaEn,
    'persona': ?persona,
  };
  Ausencia copyWith({int? id, int? usuarioId, String? tipo, String? desde, String? hasta, int? medioDia, double? dias, String? motivo, String? estado, String? resueltaEn, String? comentario, String? creadaEn, String? persona, }) => Ausencia(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, tipo: tipo ?? this.tipo, desde: desde ?? this.desde, hasta: hasta ?? this.hasta, medioDia: medioDia ?? this.medioDia, dias: dias ?? this.dias, motivo: motivo ?? this.motivo, estado: estado ?? this.estado, resueltaEn: resueltaEn ?? this.resueltaEn, comentario: comentario ?? this.comentario, creadaEn: creadaEn ?? this.creadaEn, persona: persona ?? this.persona, );
  @override bool operator ==(Object other) => other is Ausencia && other.id == id && other.usuarioId == usuarioId && other.tipo == tipo && other.desde == desde && other.hasta == hasta && other.medioDia == medioDia && other.dias == dias && other.motivo == motivo && other.estado == estado && other.resueltaEn == resueltaEn && other.comentario == comentario && other.creadaEn == creadaEn && other.persona == persona;
  @override int get hashCode => Object.hashAll([id, usuarioId, tipo, desde, hasta, medioDia, dias, motivo, estado, resueltaEn, comentario, creadaEn, persona]);
}

class AvisoFiscal {
  final int id;
  final String? tipo;
  final String? severidad;
  final String? objetoTipo;
  final int? objetoId;
  final int? clienteFiscalId;
  final String? titulo;
  final String? detalle;
  final String? url;
  final int? destinatarioId;
  final int? nivel;
  final String? estado;
  final String? creadoEn;
  final String? ultimoEnvioEn;
  final int? envios;
  final int? fallos;
  final String? escaladaEn;
  final int? acusadaPor;
  final String? acusadaEn;
  final String? notaAcuse;
  final String? resueltaEn;
  final String? motivoResolucion;
  final String? cliente;
  final String? destinatario;
  final String? acusadaPorNombre;
  final int? horasAbierta;
  const AvisoFiscal({required this.id, this.tipo, this.severidad, this.objetoTipo, this.objetoId, this.clienteFiscalId, this.titulo, this.detalle, this.url, this.destinatarioId, this.nivel, this.estado, this.creadoEn, this.ultimoEnvioEn, this.envios, this.fallos, this.escaladaEn, this.acusadaPor, this.acusadaEn, this.notaAcuse, this.resueltaEn, this.motivoResolucion, this.cliente, this.destinatario, this.acusadaPorNombre, this.horasAbierta, });
  factory AvisoFiscal.fromJson(Map<String, dynamic> j) => AvisoFiscal(
    id: (j['id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    severidad: j['severidad'] == null ? null : j['severidad'] as String,
    objetoTipo: j['objeto_tipo'] == null ? null : j['objeto_tipo'] as String,
    objetoId: j['objeto_id'] == null ? null : (j['objeto_id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    detalle: j['detalle'] == null ? null : j['detalle'] as String,
    url: j['url'] == null ? null : j['url'] as String,
    destinatarioId: j['destinatario_id'] == null ? null : (j['destinatario_id'] as num).toInt(),
    nivel: j['nivel'] == null ? null : (j['nivel'] as num).toInt(),
    estado: j['estado'] == null ? null : j['estado'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    ultimoEnvioEn: j['ultimo_envio_en'] == null ? null : j['ultimo_envio_en'] as String,
    envios: j['envios'] == null ? null : (j['envios'] as num).toInt(),
    fallos: j['fallos'] == null ? null : (j['fallos'] as num).toInt(),
    escaladaEn: j['escalada_en'] == null ? null : j['escalada_en'] as String,
    acusadaPor: j['acusada_por'] == null ? null : (j['acusada_por'] as num).toInt(),
    acusadaEn: j['acusada_en'] == null ? null : j['acusada_en'] as String,
    notaAcuse: j['nota_acuse'] == null ? null : j['nota_acuse'] as String,
    resueltaEn: j['resuelta_en'] == null ? null : j['resuelta_en'] as String,
    motivoResolucion: j['motivo_resolucion'] == null ? null : j['motivo_resolucion'] as String,
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    destinatario: j['destinatario'] == null ? null : j['destinatario'] as String,
    acusadaPorNombre: j['acusada_por_nombre'] == null ? null : j['acusada_por_nombre'] as String,
    horasAbierta: j['horas_abierta'] == null ? null : (j['horas_abierta'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tipo': ?tipo,
    'severidad': ?severidad,
    'objeto_tipo': ?objetoTipo,
    'objeto_id': ?objetoId,
    'cliente_fiscal_id': ?clienteFiscalId,
    'titulo': ?titulo,
    'detalle': ?detalle,
    'url': ?url,
    'destinatario_id': ?destinatarioId,
    'nivel': ?nivel,
    'estado': ?estado,
    'creado_en': ?creadoEn,
    'ultimo_envio_en': ?ultimoEnvioEn,
    'envios': ?envios,
    'fallos': ?fallos,
    'escalada_en': ?escaladaEn,
    'acusada_por': ?acusadaPor,
    'acusada_en': ?acusadaEn,
    'nota_acuse': ?notaAcuse,
    'resuelta_en': ?resueltaEn,
    'motivo_resolucion': ?motivoResolucion,
    'cliente': ?cliente,
    'destinatario': ?destinatario,
    'acusada_por_nombre': ?acusadaPorNombre,
    'horas_abierta': ?horasAbierta,
  };
  AvisoFiscal copyWith({int? id, String? tipo, String? severidad, String? objetoTipo, int? objetoId, int? clienteFiscalId, String? titulo, String? detalle, String? url, int? destinatarioId, int? nivel, String? estado, String? creadoEn, String? ultimoEnvioEn, int? envios, int? fallos, String? escaladaEn, int? acusadaPor, String? acusadaEn, String? notaAcuse, String? resueltaEn, String? motivoResolucion, String? cliente, String? destinatario, String? acusadaPorNombre, int? horasAbierta, }) => AvisoFiscal(id: id ?? this.id, tipo: tipo ?? this.tipo, severidad: severidad ?? this.severidad, objetoTipo: objetoTipo ?? this.objetoTipo, objetoId: objetoId ?? this.objetoId, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, titulo: titulo ?? this.titulo, detalle: detalle ?? this.detalle, url: url ?? this.url, destinatarioId: destinatarioId ?? this.destinatarioId, nivel: nivel ?? this.nivel, estado: estado ?? this.estado, creadoEn: creadoEn ?? this.creadoEn, ultimoEnvioEn: ultimoEnvioEn ?? this.ultimoEnvioEn, envios: envios ?? this.envios, fallos: fallos ?? this.fallos, escaladaEn: escaladaEn ?? this.escaladaEn, acusadaPor: acusadaPor ?? this.acusadaPor, acusadaEn: acusadaEn ?? this.acusadaEn, notaAcuse: notaAcuse ?? this.notaAcuse, resueltaEn: resueltaEn ?? this.resueltaEn, motivoResolucion: motivoResolucion ?? this.motivoResolucion, cliente: cliente ?? this.cliente, destinatario: destinatario ?? this.destinatario, acusadaPorNombre: acusadaPorNombre ?? this.acusadaPorNombre, horasAbierta: horasAbierta ?? this.horasAbierta, );
  @override bool operator ==(Object other) => other is AvisoFiscal && other.id == id && other.tipo == tipo && other.severidad == severidad && other.objetoTipo == objetoTipo && other.objetoId == objetoId && other.clienteFiscalId == clienteFiscalId && other.titulo == titulo && other.detalle == detalle && other.url == url && other.destinatarioId == destinatarioId && other.nivel == nivel && other.estado == estado && other.creadoEn == creadoEn && other.ultimoEnvioEn == ultimoEnvioEn && other.envios == envios && other.fallos == fallos && other.escaladaEn == escaladaEn && other.acusadaPor == acusadaPor && other.acusadaEn == acusadaEn && other.notaAcuse == notaAcuse && other.resueltaEn == resueltaEn && other.motivoResolucion == motivoResolucion && other.cliente == cliente && other.destinatario == destinatario && other.acusadaPorNombre == acusadaPorNombre && other.horasAbierta == horasAbierta;
  @override int get hashCode => Object.hashAll([id, tipo, severidad, objetoTipo, objetoId, clienteFiscalId, titulo, detalle, url, destinatarioId, nivel, estado, creadoEn, ultimoEnvioEn, envios, fallos, escaladaEn, acusadaPor, acusadaEn, notaAcuse, resueltaEn, motivoResolucion, cliente, destinatario, acusadaPorNombre, horasAbierta]);
}

class BandejaHoy {
  final int? total;
  final int? urgentes;
  final int? despachoId;
  final String? generadoEn;
  final List<SeccionHoy>? secciones;
  final List<ElementoHoy>? destacados;
  const BandejaHoy({this.total, this.urgentes, this.despachoId, this.generadoEn, this.secciones, this.destacados, });
  factory BandejaHoy.fromJson(Map<String, dynamic> j) => BandejaHoy(
    total: j['total'] == null ? null : (j['total'] as num).toInt(),
    urgentes: j['urgentes'] == null ? null : (j['urgentes'] as num).toInt(),
    despachoId: j['despacho_id'] == null ? null : (j['despacho_id'] as num).toInt(),
    generadoEn: j['generado_en'] == null ? null : j['generado_en'] as String,
    secciones: j['secciones'] == null ? null : (j['secciones'] as List).map((e) => SeccionHoy.fromJson(e as Map<String, dynamic>)).toList(),
    destacados: j['destacados'] == null ? null : (j['destacados'] as List).map((e) => ElementoHoy.fromJson(e as Map<String, dynamic>)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'total': ?total,
    'urgentes': ?urgentes,
    'despacho_id': ?despachoId,
    'generado_en': ?generadoEn,
    if (secciones != null) 'secciones': secciones!.map((e) => e.toJson()).toList(),
    if (destacados != null) 'destacados': destacados!.map((e) => e.toJson()).toList(),
  };
  BandejaHoy copyWith({int? total, int? urgentes, int? despachoId, String? generadoEn, List<SeccionHoy>? secciones, List<ElementoHoy>? destacados, }) => BandejaHoy(total: total ?? this.total, urgentes: urgentes ?? this.urgentes, despachoId: despachoId ?? this.despachoId, generadoEn: generadoEn ?? this.generadoEn, secciones: secciones ?? this.secciones, destacados: destacados ?? this.destacados, );
  @override bool operator ==(Object other) => other is BandejaHoy && other.total == total && other.urgentes == urgentes && other.despachoId == despachoId && other.generadoEn == generadoEn && other.secciones == secciones && other.destacados == destacados;
  @override int get hashCode => Object.hashAll([total, urgentes, despachoId, generadoEn, secciones, destacados]);
}

class BolsaEquipo {
  final int? usuarioId;
  final String? nombre;
  final bool? sinJornada;
  final double? jornadaSemanalHoras;
  final double? esperadoSeg;
  final double? trabajadoSeg;
  final double? ajustesSeg;
  final double? saldoSeg;
  const BolsaEquipo({this.usuarioId, this.nombre, this.sinJornada, this.jornadaSemanalHoras, this.esperadoSeg, this.trabajadoSeg, this.ajustesSeg, this.saldoSeg, });
  factory BolsaEquipo.fromJson(Map<String, dynamic> j) => BolsaEquipo(
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    sinJornada: j['sin_jornada'] == null ? null : _aBool(j['sin_jornada']),
    jornadaSemanalHoras: j['jornada_semanal_horas'] == null ? null : (j['jornada_semanal_horas'] as num).toDouble(),
    esperadoSeg: j['esperado_seg'] == null ? null : (j['esperado_seg'] as num).toDouble(),
    trabajadoSeg: j['trabajado_seg'] == null ? null : (j['trabajado_seg'] as num).toDouble(),
    ajustesSeg: j['ajustes_seg'] == null ? null : (j['ajustes_seg'] as num).toDouble(),
    saldoSeg: j['saldo_seg'] == null ? null : (j['saldo_seg'] as num).toDouble(),
  );
  Map<String, dynamic> toJson() => {
    'usuario_id': ?usuarioId,
    'nombre': ?nombre,
    'sin_jornada': ?sinJornada,
    'jornada_semanal_horas': ?jornadaSemanalHoras,
    'esperado_seg': ?esperadoSeg,
    'trabajado_seg': ?trabajadoSeg,
    'ajustes_seg': ?ajustesSeg,
    'saldo_seg': ?saldoSeg,
  };
  BolsaEquipo copyWith({int? usuarioId, String? nombre, bool? sinJornada, double? jornadaSemanalHoras, double? esperadoSeg, double? trabajadoSeg, double? ajustesSeg, double? saldoSeg, }) => BolsaEquipo(usuarioId: usuarioId ?? this.usuarioId, nombre: nombre ?? this.nombre, sinJornada: sinJornada ?? this.sinJornada, jornadaSemanalHoras: jornadaSemanalHoras ?? this.jornadaSemanalHoras, esperadoSeg: esperadoSeg ?? this.esperadoSeg, trabajadoSeg: trabajadoSeg ?? this.trabajadoSeg, ajustesSeg: ajustesSeg ?? this.ajustesSeg, saldoSeg: saldoSeg ?? this.saldoSeg, );
  @override bool operator ==(Object other) => other is BolsaEquipo && other.usuarioId == usuarioId && other.nombre == nombre && other.sinJornada == sinJornada && other.jornadaSemanalHoras == jornadaSemanalHoras && other.esperadoSeg == esperadoSeg && other.trabajadoSeg == trabajadoSeg && other.ajustesSeg == ajustesSeg && other.saldoSeg == saldoSeg;
  @override int get hashCode => Object.hashAll([usuarioId, nombre, sinJornada, jornadaSemanalHoras, esperadoSeg, trabajadoSeg, ajustesSeg, saldoSeg]);
}

class BolsaHoras {
  final int? usuarioId;
  final String? desde;
  final String? hasta;
  final double? jornadaSemanalHoras;
  final bool? sinJornada;
  final int? diasConTurno;
  final int? diasLaborables;
  final double? diasJustificados;
  final double? esperadoSeg;
  final double? trabajadoSeg;
  final double? ajustesSeg;
  final double? saldoSeg;
  final List<Map<String, dynamic>>? porMes;
  const BolsaHoras({this.usuarioId, this.desde, this.hasta, this.jornadaSemanalHoras, this.sinJornada, this.diasConTurno, this.diasLaborables, this.diasJustificados, this.esperadoSeg, this.trabajadoSeg, this.ajustesSeg, this.saldoSeg, this.porMes, });
  factory BolsaHoras.fromJson(Map<String, dynamic> j) => BolsaHoras(
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    desde: j['desde'] == null ? null : j['desde'] as String,
    hasta: j['hasta'] == null ? null : j['hasta'] as String,
    jornadaSemanalHoras: j['jornada_semanal_horas'] == null ? null : (j['jornada_semanal_horas'] as num).toDouble(),
    sinJornada: j['sin_jornada'] == null ? null : _aBool(j['sin_jornada']),
    diasConTurno: j['dias_con_turno'] == null ? null : (j['dias_con_turno'] as num).toInt(),
    diasLaborables: j['dias_laborables'] == null ? null : (j['dias_laborables'] as num).toInt(),
    diasJustificados: j['dias_justificados'] == null ? null : (j['dias_justificados'] as num).toDouble(),
    esperadoSeg: j['esperado_seg'] == null ? null : (j['esperado_seg'] as num).toDouble(),
    trabajadoSeg: j['trabajado_seg'] == null ? null : (j['trabajado_seg'] as num).toDouble(),
    ajustesSeg: j['ajustes_seg'] == null ? null : (j['ajustes_seg'] as num).toDouble(),
    saldoSeg: j['saldo_seg'] == null ? null : (j['saldo_seg'] as num).toDouble(),
    porMes: j['por_mes'] == null ? null : (j['por_mes'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'usuario_id': ?usuarioId,
    'desde': ?desde,
    'hasta': ?hasta,
    'jornada_semanal_horas': ?jornadaSemanalHoras,
    'sin_jornada': ?sinJornada,
    'dias_con_turno': ?diasConTurno,
    'dias_laborables': ?diasLaborables,
    'dias_justificados': ?diasJustificados,
    'esperado_seg': ?esperadoSeg,
    'trabajado_seg': ?trabajadoSeg,
    'ajustes_seg': ?ajustesSeg,
    'saldo_seg': ?saldoSeg,
    if (porMes != null) 'por_mes': porMes!.map((e) => e).toList(),
  };
  BolsaHoras copyWith({int? usuarioId, String? desde, String? hasta, double? jornadaSemanalHoras, bool? sinJornada, int? diasConTurno, int? diasLaborables, double? diasJustificados, double? esperadoSeg, double? trabajadoSeg, double? ajustesSeg, double? saldoSeg, List<Map<String, dynamic>>? porMes, }) => BolsaHoras(usuarioId: usuarioId ?? this.usuarioId, desde: desde ?? this.desde, hasta: hasta ?? this.hasta, jornadaSemanalHoras: jornadaSemanalHoras ?? this.jornadaSemanalHoras, sinJornada: sinJornada ?? this.sinJornada, diasConTurno: diasConTurno ?? this.diasConTurno, diasLaborables: diasLaborables ?? this.diasLaborables, diasJustificados: diasJustificados ?? this.diasJustificados, esperadoSeg: esperadoSeg ?? this.esperadoSeg, trabajadoSeg: trabajadoSeg ?? this.trabajadoSeg, ajustesSeg: ajustesSeg ?? this.ajustesSeg, saldoSeg: saldoSeg ?? this.saldoSeg, porMes: porMes ?? this.porMes, );
  @override bool operator ==(Object other) => other is BolsaHoras && other.usuarioId == usuarioId && other.desde == desde && other.hasta == hasta && other.jornadaSemanalHoras == jornadaSemanalHoras && other.sinJornada == sinJornada && other.diasConTurno == diasConTurno && other.diasLaborables == diasLaborables && other.diasJustificados == diasJustificados && other.esperadoSeg == esperadoSeg && other.trabajadoSeg == trabajadoSeg && other.ajustesSeg == ajustesSeg && other.saldoSeg == saldoSeg && other.porMes == porMes;
  @override int get hashCode => Object.hashAll([usuarioId, desde, hasta, jornadaSemanalHoras, sinJornada, diasConTurno, diasLaborables, diasJustificados, esperadoSeg, trabajadoSeg, ajustesSeg, saldoSeg, porMes]);
}

class BusquedaJuridica {
  final List<Map<String, dynamic>>? resultados;
  final int? total;
  final String? siguienteCursor;
  final BusquedaJuridicaModo? modo;
  final List<String>? avisos;
  final List<String>? huecos;
  final List<String>? fuentes;
  const BusquedaJuridica({this.resultados, this.total, this.siguienteCursor, this.modo, this.avisos, this.huecos, this.fuentes, });
  factory BusquedaJuridica.fromJson(Map<String, dynamic> j) => BusquedaJuridica(
    resultados: j['resultados'] == null ? null : (j['resultados'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    total: j['total'] == null ? null : (j['total'] as num).toInt(),
    siguienteCursor: j['siguiente_cursor'] == null ? null : j['siguiente_cursor'] as String,
    modo: j['modo'] == null ? null : BusquedaJuridicaModo.desde(j['modo'] as String),
    avisos: j['avisos'] == null ? null : (j['avisos'] as List).map((e) => e as String).toList(),
    huecos: j['huecos'] == null ? null : (j['huecos'] as List).map((e) => e as String).toList(),
    fuentes: j['fuentes'] == null ? null : (j['fuentes'] as List).map((e) => e as String).toList(),
  );
  Map<String, dynamic> toJson() => {
    if (resultados != null) 'resultados': resultados!.map((e) => e).toList(),
    'total': ?total,
    'siguiente_cursor': ?siguienteCursor,
    if (modo != null) 'modo': modo!.valor,
    if (avisos != null) 'avisos': avisos!.map((e) => e).toList(),
    if (huecos != null) 'huecos': huecos!.map((e) => e).toList(),
    if (fuentes != null) 'fuentes': fuentes!.map((e) => e).toList(),
  };
  BusquedaJuridica copyWith({List<Map<String, dynamic>>? resultados, int? total, String? siguienteCursor, BusquedaJuridicaModo? modo, List<String>? avisos, List<String>? huecos, List<String>? fuentes, }) => BusquedaJuridica(resultados: resultados ?? this.resultados, total: total ?? this.total, siguienteCursor: siguienteCursor ?? this.siguienteCursor, modo: modo ?? this.modo, avisos: avisos ?? this.avisos, huecos: huecos ?? this.huecos, fuentes: fuentes ?? this.fuentes, );
  @override bool operator ==(Object other) => other is BusquedaJuridica && other.resultados == resultados && other.total == total && other.siguienteCursor == siguienteCursor && other.modo == modo && other.avisos == avisos && other.huecos == huecos && other.fuentes == fuentes;
  @override int get hashCode => Object.hashAll([resultados, total, siguienteCursor, modo, avisos, huecos, fuentes]);
}

class Carpeta {
  final String? nombre;
  final int? noLeidos;
  const Carpeta({this.nombre, this.noLeidos, });
  factory Carpeta.fromJson(Map<String, dynamic> j) => Carpeta(
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    noLeidos: j['no_leidos'] == null ? null : (j['no_leidos'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'nombre': ?nombre,
    'no_leidos': ?noLeidos,
  };
  Carpeta copyWith({String? nombre, int? noLeidos, }) => Carpeta(nombre: nombre ?? this.nombre, noLeidos: noLeidos ?? this.noLeidos, );
  @override bool operator ==(Object other) => other is Carpeta && other.nombre == nombre && other.noLeidos == noLeidos;
  @override int get hashCode => Object.hashAll([nombre, noLeidos]);
}

class CategoriaCorreo {
  final int id;
  final int? usuarioId;
  final String? nombre;
  final String? color;
  final String? creadaEn;
  const CategoriaCorreo({required this.id, this.usuarioId, this.nombre, this.color, this.creadaEn, });
  factory CategoriaCorreo.fromJson(Map<String, dynamic> j) => CategoriaCorreo(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    color: j['color'] == null ? null : j['color'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'nombre': ?nombre,
    'color': ?color,
    'creada_en': ?creadaEn,
  };
  CategoriaCorreo copyWith({int? id, int? usuarioId, String? nombre, String? color, String? creadaEn, }) => CategoriaCorreo(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, nombre: nombre ?? this.nombre, color: color ?? this.color, creadaEn: creadaEn ?? this.creadaEn, );
  @override bool operator ==(Object other) => other is CategoriaCorreo && other.id == id && other.usuarioId == usuarioId && other.nombre == nombre && other.color == color && other.creadaEn == creadaEn;
  @override int get hashCode => Object.hashAll([id, usuarioId, nombre, color, creadaEn]);
}

class Certificado {
  final int id;
  final String? huellaSha256;
  final int? verificado;
  final String? origen;
  final String? numeroSerie;
  final String? emisor;
  final String? sujeto;
  final String? nombreComun;
  final List<String>? san;
  final String? notBefore;
  final String? notAfter;
  final String? algoritmoFirma;
  final String? clavePublica;
  final List<String>? usosClave;
  final List<String>? politicas;
  final int? esCa;
  final List<Map<String, dynamic>>? rutaCadena;
  final String? nifSugerido;
  final String? nifConfirmado;
  final String? tipoTitularSugerido;
  final String? tipoTitular;
  final int? custodioId;
  final String? ubicacionExterna;
  final String? notas;
  final String? estadoOperativo;
  final int? sustituyeA;
  final int? version;
  final int? creadoPor;
  final String? creadoEn;
  final String? actualizadoEn;
  final String? tipoCertificado;
  final int? clienteTitularId;
  final int? avisarCliente;
  final String? ayudaSolicitadaEn;
  final CertificadoTemporal? temporal;
  final int? diasRestantes;
  final Map<String, dynamic>? cadena;
  final Map<String, dynamic>? revocacion;
  final Map<String, dynamic>? clave;
  final CertificadoRenovacion? renovacion;
  final int? vinculosActivos;
  final String? custodioNombre;
  final bool? pendienteDeComprobar;
  final String? caducaEl;
  final String? emitidoEl;
  final String? clienteNombre;
  const Certificado({required this.id, this.huellaSha256, this.verificado, this.origen, this.numeroSerie, this.emisor, this.sujeto, this.nombreComun, this.san, this.notBefore, this.notAfter, this.algoritmoFirma, this.clavePublica, this.usosClave, this.politicas, this.esCa, this.rutaCadena, this.nifSugerido, this.nifConfirmado, this.tipoTitularSugerido, this.tipoTitular, this.custodioId, this.ubicacionExterna, this.notas, this.estadoOperativo, this.sustituyeA, this.version, this.creadoPor, this.creadoEn, this.actualizadoEn, this.tipoCertificado, this.clienteTitularId, this.avisarCliente, this.ayudaSolicitadaEn, this.temporal, this.diasRestantes, this.cadena, this.revocacion, this.clave, this.renovacion, this.vinculosActivos, this.custodioNombre, this.pendienteDeComprobar, this.caducaEl, this.emitidoEl, this.clienteNombre, });
  factory Certificado.fromJson(Map<String, dynamic> j) => Certificado(
    id: (j['id'] as num).toInt(),
    huellaSha256: j['huella_sha256'] == null ? null : j['huella_sha256'] as String,
    verificado: j['verificado'] == null ? null : (j['verificado'] as num).toInt(),
    origen: j['origen'] == null ? null : j['origen'] as String,
    numeroSerie: j['numero_serie'] == null ? null : j['numero_serie'] as String,
    emisor: j['emisor'] == null ? null : j['emisor'] as String,
    sujeto: j['sujeto'] == null ? null : j['sujeto'] as String,
    nombreComun: j['nombre_comun'] == null ? null : j['nombre_comun'] as String,
    san: j['san'] == null ? null : (j['san'] as List).map((e) => e as String).toList(),
    notBefore: j['not_before'] == null ? null : j['not_before'] as String,
    notAfter: j['not_after'] == null ? null : j['not_after'] as String,
    algoritmoFirma: j['algoritmo_firma'] == null ? null : j['algoritmo_firma'] as String,
    clavePublica: j['clave_publica'] == null ? null : j['clave_publica'] as String,
    usosClave: j['usos_clave'] == null ? null : (j['usos_clave'] as List).map((e) => e as String).toList(),
    politicas: j['politicas'] == null ? null : (j['politicas'] as List).map((e) => e as String).toList(),
    esCa: j['es_ca'] == null ? null : (j['es_ca'] as num).toInt(),
    rutaCadena: j['ruta_cadena'] == null ? null : (j['ruta_cadena'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    nifSugerido: j['nif_sugerido'] == null ? null : j['nif_sugerido'] as String,
    nifConfirmado: j['nif_confirmado'] == null ? null : j['nif_confirmado'] as String,
    tipoTitularSugerido: j['tipo_titular_sugerido'] == null ? null : j['tipo_titular_sugerido'] as String,
    tipoTitular: j['tipo_titular'] == null ? null : j['tipo_titular'] as String,
    custodioId: j['custodio_id'] == null ? null : (j['custodio_id'] as num).toInt(),
    ubicacionExterna: j['ubicacion_externa'] == null ? null : j['ubicacion_externa'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    estadoOperativo: j['estado_operativo'] == null ? null : j['estado_operativo'] as String,
    sustituyeA: j['sustituye_a'] == null ? null : (j['sustituye_a'] as num).toInt(),
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    creadoPor: j['creado_por'] == null ? null : (j['creado_por'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    actualizadoEn: j['actualizado_en'] == null ? null : j['actualizado_en'] as String,
    tipoCertificado: j['tipo_certificado'] == null ? null : j['tipo_certificado'] as String,
    clienteTitularId: j['cliente_titular_id'] == null ? null : (j['cliente_titular_id'] as num).toInt(),
    avisarCliente: j['avisar_cliente'] == null ? null : (j['avisar_cliente'] as num).toInt(),
    ayudaSolicitadaEn: j['ayuda_solicitada_en'] == null ? null : j['ayuda_solicitada_en'] as String,
    temporal: j['temporal'] == null ? null : CertificadoTemporal.desde(j['temporal'] as String),
    diasRestantes: j['dias_restantes'] == null ? null : (j['dias_restantes'] as num).toInt(),
    cadena: j['cadena'] == null ? null : Map<String, dynamic>.from(j['cadena'] as Map),
    revocacion: j['revocacion'] == null ? null : Map<String, dynamic>.from(j['revocacion'] as Map),
    clave: j['clave'] == null ? null : Map<String, dynamic>.from(j['clave'] as Map),
    renovacion: j['renovacion'] == null ? null : CertificadoRenovacion.desde(j['renovacion'] as String),
    vinculosActivos: j['vinculos_activos'] == null ? null : (j['vinculos_activos'] as num).toInt(),
    custodioNombre: j['custodio_nombre'] == null ? null : j['custodio_nombre'] as String,
    pendienteDeComprobar: j['pendiente_de_comprobar'] == null ? null : _aBool(j['pendiente_de_comprobar']),
    caducaEl: j['caduca_el'] == null ? null : j['caduca_el'] as String,
    emitidoEl: j['emitido_el'] == null ? null : j['emitido_el'] as String,
    clienteNombre: j['cliente_nombre'] == null ? null : j['cliente_nombre'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'huella_sha256': ?huellaSha256,
    'verificado': ?verificado,
    'origen': ?origen,
    'numero_serie': ?numeroSerie,
    'emisor': ?emisor,
    'sujeto': ?sujeto,
    'nombre_comun': ?nombreComun,
    if (san != null) 'san': san!.map((e) => e).toList(),
    'not_before': ?notBefore,
    'not_after': ?notAfter,
    'algoritmo_firma': ?algoritmoFirma,
    'clave_publica': ?clavePublica,
    if (usosClave != null) 'usos_clave': usosClave!.map((e) => e).toList(),
    if (politicas != null) 'politicas': politicas!.map((e) => e).toList(),
    'es_ca': ?esCa,
    if (rutaCadena != null) 'ruta_cadena': rutaCadena!.map((e) => e).toList(),
    'nif_sugerido': ?nifSugerido,
    'nif_confirmado': ?nifConfirmado,
    'tipo_titular_sugerido': ?tipoTitularSugerido,
    'tipo_titular': ?tipoTitular,
    'custodio_id': ?custodioId,
    'ubicacion_externa': ?ubicacionExterna,
    'notas': ?notas,
    'estado_operativo': ?estadoOperativo,
    'sustituye_a': ?sustituyeA,
    'version': ?version,
    'creado_por': ?creadoPor,
    'creado_en': ?creadoEn,
    'actualizado_en': ?actualizadoEn,
    'tipo_certificado': ?tipoCertificado,
    'cliente_titular_id': ?clienteTitularId,
    'avisar_cliente': ?avisarCliente,
    'ayuda_solicitada_en': ?ayudaSolicitadaEn,
    if (temporal != null) 'temporal': temporal!.valor,
    'dias_restantes': ?diasRestantes,
    'cadena': ?cadena,
    'revocacion': ?revocacion,
    'clave': ?clave,
    if (renovacion != null) 'renovacion': renovacion!.valor,
    'vinculos_activos': ?vinculosActivos,
    'custodio_nombre': ?custodioNombre,
    'pendiente_de_comprobar': ?pendienteDeComprobar,
    'caduca_el': ?caducaEl,
    'emitido_el': ?emitidoEl,
    'cliente_nombre': ?clienteNombre,
  };
  Certificado copyWith({int? id, String? huellaSha256, int? verificado, String? origen, String? numeroSerie, String? emisor, String? sujeto, String? nombreComun, List<String>? san, String? notBefore, String? notAfter, String? algoritmoFirma, String? clavePublica, List<String>? usosClave, List<String>? politicas, int? esCa, List<Map<String, dynamic>>? rutaCadena, String? nifSugerido, String? nifConfirmado, String? tipoTitularSugerido, String? tipoTitular, int? custodioId, String? ubicacionExterna, String? notas, String? estadoOperativo, int? sustituyeA, int? version, int? creadoPor, String? creadoEn, String? actualizadoEn, String? tipoCertificado, int? clienteTitularId, int? avisarCliente, String? ayudaSolicitadaEn, CertificadoTemporal? temporal, int? diasRestantes, Map<String, dynamic>? cadena, Map<String, dynamic>? revocacion, Map<String, dynamic>? clave, CertificadoRenovacion? renovacion, int? vinculosActivos, String? custodioNombre, bool? pendienteDeComprobar, String? caducaEl, String? emitidoEl, String? clienteNombre, }) => Certificado(id: id ?? this.id, huellaSha256: huellaSha256 ?? this.huellaSha256, verificado: verificado ?? this.verificado, origen: origen ?? this.origen, numeroSerie: numeroSerie ?? this.numeroSerie, emisor: emisor ?? this.emisor, sujeto: sujeto ?? this.sujeto, nombreComun: nombreComun ?? this.nombreComun, san: san ?? this.san, notBefore: notBefore ?? this.notBefore, notAfter: notAfter ?? this.notAfter, algoritmoFirma: algoritmoFirma ?? this.algoritmoFirma, clavePublica: clavePublica ?? this.clavePublica, usosClave: usosClave ?? this.usosClave, politicas: politicas ?? this.politicas, esCa: esCa ?? this.esCa, rutaCadena: rutaCadena ?? this.rutaCadena, nifSugerido: nifSugerido ?? this.nifSugerido, nifConfirmado: nifConfirmado ?? this.nifConfirmado, tipoTitularSugerido: tipoTitularSugerido ?? this.tipoTitularSugerido, tipoTitular: tipoTitular ?? this.tipoTitular, custodioId: custodioId ?? this.custodioId, ubicacionExterna: ubicacionExterna ?? this.ubicacionExterna, notas: notas ?? this.notas, estadoOperativo: estadoOperativo ?? this.estadoOperativo, sustituyeA: sustituyeA ?? this.sustituyeA, version: version ?? this.version, creadoPor: creadoPor ?? this.creadoPor, creadoEn: creadoEn ?? this.creadoEn, actualizadoEn: actualizadoEn ?? this.actualizadoEn, tipoCertificado: tipoCertificado ?? this.tipoCertificado, clienteTitularId: clienteTitularId ?? this.clienteTitularId, avisarCliente: avisarCliente ?? this.avisarCliente, ayudaSolicitadaEn: ayudaSolicitadaEn ?? this.ayudaSolicitadaEn, temporal: temporal ?? this.temporal, diasRestantes: diasRestantes ?? this.diasRestantes, cadena: cadena ?? this.cadena, revocacion: revocacion ?? this.revocacion, clave: clave ?? this.clave, renovacion: renovacion ?? this.renovacion, vinculosActivos: vinculosActivos ?? this.vinculosActivos, custodioNombre: custodioNombre ?? this.custodioNombre, pendienteDeComprobar: pendienteDeComprobar ?? this.pendienteDeComprobar, caducaEl: caducaEl ?? this.caducaEl, emitidoEl: emitidoEl ?? this.emitidoEl, clienteNombre: clienteNombre ?? this.clienteNombre, );
  @override bool operator ==(Object other) => other is Certificado && other.id == id && other.huellaSha256 == huellaSha256 && other.verificado == verificado && other.origen == origen && other.numeroSerie == numeroSerie && other.emisor == emisor && other.sujeto == sujeto && other.nombreComun == nombreComun && other.san == san && other.notBefore == notBefore && other.notAfter == notAfter && other.algoritmoFirma == algoritmoFirma && other.clavePublica == clavePublica && other.usosClave == usosClave && other.politicas == politicas && other.esCa == esCa && other.rutaCadena == rutaCadena && other.nifSugerido == nifSugerido && other.nifConfirmado == nifConfirmado && other.tipoTitularSugerido == tipoTitularSugerido && other.tipoTitular == tipoTitular && other.custodioId == custodioId && other.ubicacionExterna == ubicacionExterna && other.notas == notas && other.estadoOperativo == estadoOperativo && other.sustituyeA == sustituyeA && other.version == version && other.creadoPor == creadoPor && other.creadoEn == creadoEn && other.actualizadoEn == actualizadoEn && other.tipoCertificado == tipoCertificado && other.clienteTitularId == clienteTitularId && other.avisarCliente == avisarCliente && other.ayudaSolicitadaEn == ayudaSolicitadaEn && other.temporal == temporal && other.diasRestantes == diasRestantes && other.cadena == cadena && other.revocacion == revocacion && other.clave == clave && other.renovacion == renovacion && other.vinculosActivos == vinculosActivos && other.custodioNombre == custodioNombre && other.pendienteDeComprobar == pendienteDeComprobar && other.caducaEl == caducaEl && other.emitidoEl == emitidoEl && other.clienteNombre == clienteNombre;
  @override int get hashCode => Object.hashAll([id, huellaSha256, verificado, origen, numeroSerie, emisor, sujeto, nombreComun, san, notBefore, notAfter, algoritmoFirma, clavePublica, usosClave, politicas, esCa, rutaCadena, nifSugerido, nifConfirmado, tipoTitularSugerido, tipoTitular, custodioId, ubicacionExterna, notas, estadoOperativo, sustituyeA, version, creadoPor, creadoEn, actualizadoEn, tipoCertificado, clienteTitularId, avisarCliente, ayudaSolicitadaEn, temporal, diasRestantes, cadena, revocacion, clave, renovacion, vinculosActivos, custodioNombre, pendienteDeComprobar, caducaEl, emitidoEl, clienteNombre]);
}

class CertificadoRenovado {
  final int? id;
  final int? anteriorId;
  const CertificadoRenovado({this.id, this.anteriorId, });
  factory CertificadoRenovado.fromJson(Map<String, dynamic> j) => CertificadoRenovado(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    anteriorId: j['anterior_id'] == null ? null : (j['anterior_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'anterior_id': ?anteriorId,
  };
  CertificadoRenovado copyWith({int? id, int? anteriorId, }) => CertificadoRenovado(id: id ?? this.id, anteriorId: anteriorId ?? this.anteriorId, );
  @override bool operator ==(Object other) => other is CertificadoRenovado && other.id == id && other.anteriorId == anteriorId;
  @override int get hashCode => Object.hashAll([id, anteriorId]);
}

class ChecklistItem {
  final int id;
  final int? tareaOutlookId;
  final String? texto;
  final int? hecha;
  final int? orden;
  const ChecklistItem({required this.id, this.tareaOutlookId, this.texto, this.hecha, this.orden, });
  factory ChecklistItem.fromJson(Map<String, dynamic> j) => ChecklistItem(
    id: (j['id'] as num).toInt(),
    tareaOutlookId: j['tarea_outlook_id'] == null ? null : (j['tarea_outlook_id'] as num).toInt(),
    texto: j['texto'] == null ? null : j['texto'] as String,
    hecha: j['hecha'] == null ? null : (j['hecha'] as num).toInt(),
    orden: j['orden'] == null ? null : (j['orden'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tarea_outlook_id': ?tareaOutlookId,
    'texto': ?texto,
    'hecha': ?hecha,
    'orden': ?orden,
  };
  ChecklistItem copyWith({int? id, int? tareaOutlookId, String? texto, int? hecha, int? orden, }) => ChecklistItem(id: id ?? this.id, tareaOutlookId: tareaOutlookId ?? this.tareaOutlookId, texto: texto ?? this.texto, hecha: hecha ?? this.hecha, orden: orden ?? this.orden, );
  @override bool operator ==(Object other) => other is ChecklistItem && other.id == id && other.tareaOutlookId == tareaOutlookId && other.texto == texto && other.hecha == hecha && other.orden == orden;
  @override int get hashCode => Object.hashAll([id, tareaOutlookId, texto, hecha, orden]);
}

class ChequeoExportacion {
  final String? cliente;
  final bool? ok;
  final int? facturas;
  final int? registros;
  final double? total;
  final List<Map<String, dynamic>>? errores;
  final List<Map<String, dynamic>>? avisos;
  final List<Map<String, dynamic>>? periodosCerrados;
  final List<Map<String, dynamic>>? subcuentasNuevas;
  const ChequeoExportacion({this.cliente, this.ok, this.facturas, this.registros, this.total, this.errores, this.avisos, this.periodosCerrados, this.subcuentasNuevas, });
  factory ChequeoExportacion.fromJson(Map<String, dynamic> j) => ChequeoExportacion(
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    ok: j['ok'] == null ? null : _aBool(j['ok']),
    facturas: j['facturas'] == null ? null : (j['facturas'] as num).toInt(),
    registros: j['registros'] == null ? null : (j['registros'] as num).toInt(),
    total: j['total'] == null ? null : (j['total'] as num).toDouble(),
    errores: j['errores'] == null ? null : (j['errores'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    avisos: j['avisos'] == null ? null : (j['avisos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    periodosCerrados: j['periodos_cerrados'] == null ? null : (j['periodos_cerrados'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    subcuentasNuevas: j['subcuentas_nuevas'] == null ? null : (j['subcuentas_nuevas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'cliente': ?cliente,
    'ok': ?ok,
    'facturas': ?facturas,
    'registros': ?registros,
    'total': ?total,
    if (errores != null) 'errores': errores!.map((e) => e).toList(),
    if (avisos != null) 'avisos': avisos!.map((e) => e).toList(),
    if (periodosCerrados != null) 'periodos_cerrados': periodosCerrados!.map((e) => e).toList(),
    if (subcuentasNuevas != null) 'subcuentas_nuevas': subcuentasNuevas!.map((e) => e).toList(),
  };
  ChequeoExportacion copyWith({String? cliente, bool? ok, int? facturas, int? registros, double? total, List<Map<String, dynamic>>? errores, List<Map<String, dynamic>>? avisos, List<Map<String, dynamic>>? periodosCerrados, List<Map<String, dynamic>>? subcuentasNuevas, }) => ChequeoExportacion(cliente: cliente ?? this.cliente, ok: ok ?? this.ok, facturas: facturas ?? this.facturas, registros: registros ?? this.registros, total: total ?? this.total, errores: errores ?? this.errores, avisos: avisos ?? this.avisos, periodosCerrados: periodosCerrados ?? this.periodosCerrados, subcuentasNuevas: subcuentasNuevas ?? this.subcuentasNuevas, );
  @override bool operator ==(Object other) => other is ChequeoExportacion && other.cliente == cliente && other.ok == ok && other.facturas == facturas && other.registros == registros && other.total == total && other.errores == errores && other.avisos == avisos && other.periodosCerrados == periodosCerrados && other.subcuentasNuevas == subcuentasNuevas;
  @override int get hashCode => Object.hashAll([cliente, ok, facturas, registros, total, errores, avisos, periodosCerrados, subcuentasNuevas]);
}

class ClienteDeTarea {
  final int? id;
  final String? nombre;
  final String? nif;
  final bool? principal;
  const ClienteDeTarea({this.id, this.nombre, this.nif, this.principal, });
  factory ClienteDeTarea.fromJson(Map<String, dynamic> j) => ClienteDeTarea(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    principal: j['principal'] == null ? null : _aBool(j['principal']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
    'nif': ?nif,
    'principal': ?principal,
  };
  ClienteDeTarea copyWith({int? id, String? nombre, String? nif, bool? principal, }) => ClienteDeTarea(id: id ?? this.id, nombre: nombre ?? this.nombre, nif: nif ?? this.nif, principal: principal ?? this.principal, );
  @override bool operator ==(Object other) => other is ClienteDeTarea && other.id == id && other.nombre == nombre && other.nif == nif && other.principal == principal;
  @override int get hashCode => Object.hashAll([id, nombre, nif, principal]);
}

class ClienteFiscal {
  final int id;
  final int? tenantId;
  final String? nombre;
  final String? nif;
  final String? notas;
  final String? creadoEn;
  final String? papeleraEn;
  final String? referenciaExterna;
  final String? modelosFiscales;
  final int? generacionAutomatica;
  final String? espocrmCuentaId;
  final String? email;
  final int? recordatoriosPortal;
  final String? idioma;
  final String? facturascriptsClienteCodigo;
  final String? pais;
  final String? perfilFiscal;
  final int? clienteId;
  final String? nifNormalizado;
  final String? nifDuplicadoAutorizado;
  final int? version;
  final int? oficinaId;
  final int? responsableId;
  const ClienteFiscal({required this.id, this.tenantId, this.nombre, this.nif, this.notas, this.creadoEn, this.papeleraEn, this.referenciaExterna, this.modelosFiscales, this.generacionAutomatica, this.espocrmCuentaId, this.email, this.recordatoriosPortal, this.idioma, this.facturascriptsClienteCodigo, this.pais, this.perfilFiscal, this.clienteId, this.nifNormalizado, this.nifDuplicadoAutorizado, this.version, this.oficinaId, this.responsableId, });
  factory ClienteFiscal.fromJson(Map<String, dynamic> j) => ClienteFiscal(
    id: (j['id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
    referenciaExterna: j['referencia_externa'] == null ? null : j['referencia_externa'] as String,
    modelosFiscales: j['modelos_fiscales'] == null ? null : j['modelos_fiscales'] as String,
    generacionAutomatica: j['generacion_automatica'] == null ? null : (j['generacion_automatica'] as num).toInt(),
    espocrmCuentaId: j['espocrm_cuenta_id'] == null ? null : j['espocrm_cuenta_id'] as String,
    email: j['email'] == null ? null : j['email'] as String,
    recordatoriosPortal: j['recordatorios_portal'] == null ? null : (j['recordatorios_portal'] as num).toInt(),
    idioma: j['idioma'] == null ? null : j['idioma'] as String,
    facturascriptsClienteCodigo: j['facturascripts_cliente_codigo'] == null ? null : j['facturascripts_cliente_codigo'] as String,
    pais: j['pais'] == null ? null : j['pais'] as String,
    perfilFiscal: j['perfil_fiscal'] == null ? null : j['perfil_fiscal'] as String,
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    nifNormalizado: j['nif_normalizado'] == null ? null : j['nif_normalizado'] as String,
    nifDuplicadoAutorizado: j['nif_duplicado_autorizado'] == null ? null : j['nif_duplicado_autorizado'] as String,
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    oficinaId: j['oficina_id'] == null ? null : (j['oficina_id'] as num).toInt(),
    responsableId: j['responsable_id'] == null ? null : (j['responsable_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tenant_id': ?tenantId,
    'nombre': ?nombre,
    'nif': ?nif,
    'notas': ?notas,
    'creado_en': ?creadoEn,
    'papelera_en': ?papeleraEn,
    'referencia_externa': ?referenciaExterna,
    'modelos_fiscales': ?modelosFiscales,
    'generacion_automatica': ?generacionAutomatica,
    'espocrm_cuenta_id': ?espocrmCuentaId,
    'email': ?email,
    'recordatorios_portal': ?recordatoriosPortal,
    'idioma': ?idioma,
    'facturascripts_cliente_codigo': ?facturascriptsClienteCodigo,
    'pais': ?pais,
    'perfil_fiscal': ?perfilFiscal,
    'cliente_id': ?clienteId,
    'nif_normalizado': ?nifNormalizado,
    'nif_duplicado_autorizado': ?nifDuplicadoAutorizado,
    'version': ?version,
    'oficina_id': ?oficinaId,
    'responsable_id': ?responsableId,
  };
  ClienteFiscal copyWith({int? id, int? tenantId, String? nombre, String? nif, String? notas, String? creadoEn, String? papeleraEn, String? referenciaExterna, String? modelosFiscales, int? generacionAutomatica, String? espocrmCuentaId, String? email, int? recordatoriosPortal, String? idioma, String? facturascriptsClienteCodigo, String? pais, String? perfilFiscal, int? clienteId, String? nifNormalizado, String? nifDuplicadoAutorizado, int? version, int? oficinaId, int? responsableId, }) => ClienteFiscal(id: id ?? this.id, tenantId: tenantId ?? this.tenantId, nombre: nombre ?? this.nombre, nif: nif ?? this.nif, notas: notas ?? this.notas, creadoEn: creadoEn ?? this.creadoEn, papeleraEn: papeleraEn ?? this.papeleraEn, referenciaExterna: referenciaExterna ?? this.referenciaExterna, modelosFiscales: modelosFiscales ?? this.modelosFiscales, generacionAutomatica: generacionAutomatica ?? this.generacionAutomatica, espocrmCuentaId: espocrmCuentaId ?? this.espocrmCuentaId, email: email ?? this.email, recordatoriosPortal: recordatoriosPortal ?? this.recordatoriosPortal, idioma: idioma ?? this.idioma, facturascriptsClienteCodigo: facturascriptsClienteCodigo ?? this.facturascriptsClienteCodigo, pais: pais ?? this.pais, perfilFiscal: perfilFiscal ?? this.perfilFiscal, clienteId: clienteId ?? this.clienteId, nifNormalizado: nifNormalizado ?? this.nifNormalizado, nifDuplicadoAutorizado: nifDuplicadoAutorizado ?? this.nifDuplicadoAutorizado, version: version ?? this.version, oficinaId: oficinaId ?? this.oficinaId, responsableId: responsableId ?? this.responsableId, );
  @override bool operator ==(Object other) => other is ClienteFiscal && other.id == id && other.tenantId == tenantId && other.nombre == nombre && other.nif == nif && other.notas == notas && other.creadoEn == creadoEn && other.papeleraEn == papeleraEn && other.referenciaExterna == referenciaExterna && other.modelosFiscales == modelosFiscales && other.generacionAutomatica == generacionAutomatica && other.espocrmCuentaId == espocrmCuentaId && other.email == email && other.recordatoriosPortal == recordatoriosPortal && other.idioma == idioma && other.facturascriptsClienteCodigo == facturascriptsClienteCodigo && other.pais == pais && other.perfilFiscal == perfilFiscal && other.clienteId == clienteId && other.nifNormalizado == nifNormalizado && other.nifDuplicadoAutorizado == nifDuplicadoAutorizado && other.version == version && other.oficinaId == oficinaId && other.responsableId == responsableId;
  @override int get hashCode => Object.hashAll([id, tenantId, nombre, nif, notas, creadoEn, papeleraEn, referenciaExterna, modelosFiscales, generacionAutomatica, espocrmCuentaId, email, recordatoriosPortal, idioma, facturascriptsClienteCodigo, pais, perfilFiscal, clienteId, nifNormalizado, nifDuplicadoAutorizado, version, oficinaId, responsableId]);
}

class ClienteFiscalDetalle {
  final int id;
  final int? tenantId;
  final String? nombre;
  final String? nif;
  final String? notas;
  final String? creadoEn;
  final String? papeleraEn;
  final String? referenciaExterna;
  final List<String>? modelosFiscales;
  final int? generacionAutomatica;
  final String? espocrmCuentaId;
  final String? email;
  final int? recordatoriosPortal;
  final String? idioma;
  final String? facturascriptsClienteCodigo;
  final String? pais;
  final String? perfilFiscal;
  final int? clienteId;
  final String? nifNormalizado;
  final String? nifDuplicadoAutorizado;
  final int? version;
  final int? oficinaId;
  final int? responsableId;
  const ClienteFiscalDetalle({required this.id, this.tenantId, this.nombre, this.nif, this.notas, this.creadoEn, this.papeleraEn, this.referenciaExterna, this.modelosFiscales, this.generacionAutomatica, this.espocrmCuentaId, this.email, this.recordatoriosPortal, this.idioma, this.facturascriptsClienteCodigo, this.pais, this.perfilFiscal, this.clienteId, this.nifNormalizado, this.nifDuplicadoAutorizado, this.version, this.oficinaId, this.responsableId, });
  factory ClienteFiscalDetalle.fromJson(Map<String, dynamic> j) => ClienteFiscalDetalle(
    id: (j['id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
    referenciaExterna: j['referencia_externa'] == null ? null : j['referencia_externa'] as String,
    modelosFiscales: j['modelos_fiscales'] == null ? null : (j['modelos_fiscales'] as List).map((e) => e as String).toList(),
    generacionAutomatica: j['generacion_automatica'] == null ? null : (j['generacion_automatica'] as num).toInt(),
    espocrmCuentaId: j['espocrm_cuenta_id'] == null ? null : j['espocrm_cuenta_id'] as String,
    email: j['email'] == null ? null : j['email'] as String,
    recordatoriosPortal: j['recordatorios_portal'] == null ? null : (j['recordatorios_portal'] as num).toInt(),
    idioma: j['idioma'] == null ? null : j['idioma'] as String,
    facturascriptsClienteCodigo: j['facturascripts_cliente_codigo'] == null ? null : j['facturascripts_cliente_codigo'] as String,
    pais: j['pais'] == null ? null : j['pais'] as String,
    perfilFiscal: j['perfil_fiscal'] == null ? null : j['perfil_fiscal'] as String,
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    nifNormalizado: j['nif_normalizado'] == null ? null : j['nif_normalizado'] as String,
    nifDuplicadoAutorizado: j['nif_duplicado_autorizado'] == null ? null : j['nif_duplicado_autorizado'] as String,
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    oficinaId: j['oficina_id'] == null ? null : (j['oficina_id'] as num).toInt(),
    responsableId: j['responsable_id'] == null ? null : (j['responsable_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tenant_id': ?tenantId,
    'nombre': ?nombre,
    'nif': ?nif,
    'notas': ?notas,
    'creado_en': ?creadoEn,
    'papelera_en': ?papeleraEn,
    'referencia_externa': ?referenciaExterna,
    if (modelosFiscales != null) 'modelos_fiscales': modelosFiscales!.map((e) => e).toList(),
    'generacion_automatica': ?generacionAutomatica,
    'espocrm_cuenta_id': ?espocrmCuentaId,
    'email': ?email,
    'recordatorios_portal': ?recordatoriosPortal,
    'idioma': ?idioma,
    'facturascripts_cliente_codigo': ?facturascriptsClienteCodigo,
    'pais': ?pais,
    'perfil_fiscal': ?perfilFiscal,
    'cliente_id': ?clienteId,
    'nif_normalizado': ?nifNormalizado,
    'nif_duplicado_autorizado': ?nifDuplicadoAutorizado,
    'version': ?version,
    'oficina_id': ?oficinaId,
    'responsable_id': ?responsableId,
  };
  ClienteFiscalDetalle copyWith({int? id, int? tenantId, String? nombre, String? nif, String? notas, String? creadoEn, String? papeleraEn, String? referenciaExterna, List<String>? modelosFiscales, int? generacionAutomatica, String? espocrmCuentaId, String? email, int? recordatoriosPortal, String? idioma, String? facturascriptsClienteCodigo, String? pais, String? perfilFiscal, int? clienteId, String? nifNormalizado, String? nifDuplicadoAutorizado, int? version, int? oficinaId, int? responsableId, }) => ClienteFiscalDetalle(id: id ?? this.id, tenantId: tenantId ?? this.tenantId, nombre: nombre ?? this.nombre, nif: nif ?? this.nif, notas: notas ?? this.notas, creadoEn: creadoEn ?? this.creadoEn, papeleraEn: papeleraEn ?? this.papeleraEn, referenciaExterna: referenciaExterna ?? this.referenciaExterna, modelosFiscales: modelosFiscales ?? this.modelosFiscales, generacionAutomatica: generacionAutomatica ?? this.generacionAutomatica, espocrmCuentaId: espocrmCuentaId ?? this.espocrmCuentaId, email: email ?? this.email, recordatoriosPortal: recordatoriosPortal ?? this.recordatoriosPortal, idioma: idioma ?? this.idioma, facturascriptsClienteCodigo: facturascriptsClienteCodigo ?? this.facturascriptsClienteCodigo, pais: pais ?? this.pais, perfilFiscal: perfilFiscal ?? this.perfilFiscal, clienteId: clienteId ?? this.clienteId, nifNormalizado: nifNormalizado ?? this.nifNormalizado, nifDuplicadoAutorizado: nifDuplicadoAutorizado ?? this.nifDuplicadoAutorizado, version: version ?? this.version, oficinaId: oficinaId ?? this.oficinaId, responsableId: responsableId ?? this.responsableId, );
  @override bool operator ==(Object other) => other is ClienteFiscalDetalle && other.id == id && other.tenantId == tenantId && other.nombre == nombre && other.nif == nif && other.notas == notas && other.creadoEn == creadoEn && other.papeleraEn == papeleraEn && other.referenciaExterna == referenciaExterna && other.modelosFiscales == modelosFiscales && other.generacionAutomatica == generacionAutomatica && other.espocrmCuentaId == espocrmCuentaId && other.email == email && other.recordatoriosPortal == recordatoriosPortal && other.idioma == idioma && other.facturascriptsClienteCodigo == facturascriptsClienteCodigo && other.pais == pais && other.perfilFiscal == perfilFiscal && other.clienteId == clienteId && other.nifNormalizado == nifNormalizado && other.nifDuplicadoAutorizado == nifDuplicadoAutorizado && other.version == version && other.oficinaId == oficinaId && other.responsableId == responsableId;
  @override int get hashCode => Object.hashAll([id, tenantId, nombre, nif, notas, creadoEn, papeleraEn, referenciaExterna, modelosFiscales, generacionAutomatica, espocrmCuentaId, email, recordatoriosPortal, idioma, facturascriptsClienteCodigo, pais, perfilFiscal, clienteId, nifNormalizado, nifDuplicadoAutorizado, version, oficinaId, responsableId]);
}

class ClientesDeTarea {
  final List<ClienteDeTarea>? clientes;
  final int? version;
  const ClientesDeTarea({this.clientes, this.version, });
  factory ClientesDeTarea.fromJson(Map<String, dynamic> j) => ClientesDeTarea(
    clientes: j['clientes'] == null ? null : (j['clientes'] as List).map((e) => ClienteDeTarea.fromJson(e as Map<String, dynamic>)).toList(),
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    if (clientes != null) 'clientes': clientes!.map((e) => e.toJson()).toList(),
    'version': ?version,
  };
  ClientesDeTarea copyWith({List<ClienteDeTarea>? clientes, int? version, }) => ClientesDeTarea(clientes: clientes ?? this.clientes, version: version ?? this.version, );
  @override bool operator ==(Object other) => other is ClientesDeTarea && other.clientes == clientes && other.version == version;
  @override int get hashCode => Object.hashAll([clientes, version]);
}

class ColeccionJuridica {
  final String? clave;
  final String? nombre;
  final bool? disponible;
  final List<Map<String, dynamic>>? fuentes;
  const ColeccionJuridica({this.clave, this.nombre, this.disponible, this.fuentes, });
  factory ColeccionJuridica.fromJson(Map<String, dynamic> j) => ColeccionJuridica(
    clave: j['clave'] == null ? null : j['clave'] as String,
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    disponible: j['disponible'] == null ? null : _aBool(j['disponible']),
    fuentes: j['fuentes'] == null ? null : (j['fuentes'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'clave': ?clave,
    'nombre': ?nombre,
    'disponible': ?disponible,
    if (fuentes != null) 'fuentes': fuentes!.map((e) => e).toList(),
  };
  ColeccionJuridica copyWith({String? clave, String? nombre, bool? disponible, List<Map<String, dynamic>>? fuentes, }) => ColeccionJuridica(clave: clave ?? this.clave, nombre: nombre ?? this.nombre, disponible: disponible ?? this.disponible, fuentes: fuentes ?? this.fuentes, );
  @override bool operator ==(Object other) => other is ColeccionJuridica && other.clave == clave && other.nombre == nombre && other.disponible == disponible && other.fuentes == fuentes;
  @override int get hashCode => Object.hashAll([clave, nombre, disponible, fuentes]);
}

class ComentarioOculto {
  final int? id;
  final int? tareaId;
  final bool? oculto;
  const ComentarioOculto({this.id, this.tareaId, this.oculto, });
  factory ComentarioOculto.fromJson(Map<String, dynamic> j) => ComentarioOculto(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    tareaId: j['tarea_id'] == null ? null : (j['tarea_id'] as num).toInt(),
    oculto: j['oculto'] == null ? null : _aBool(j['oculto']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'tarea_id': ?tareaId,
    'oculto': ?oculto,
  };
  ComentarioOculto copyWith({int? id, int? tareaId, bool? oculto, }) => ComentarioOculto(id: id ?? this.id, tareaId: tareaId ?? this.tareaId, oculto: oculto ?? this.oculto, );
  @override bool operator ==(Object other) => other is ComentarioOculto && other.id == id && other.tareaId == tareaId && other.oculto == oculto;
  @override int get hashCode => Object.hashAll([id, tareaId, oculto]);
}

class ComentarioTarea {
  final int id;
  final int? tareaId;
  final int? usuarioId;
  final String? texto;
  final String? menciones;
  final String? creadoEn;
  const ComentarioTarea({required this.id, this.tareaId, this.usuarioId, this.texto, this.menciones, this.creadoEn, });
  factory ComentarioTarea.fromJson(Map<String, dynamic> j) => ComentarioTarea(
    id: (j['id'] as num).toInt(),
    tareaId: j['tarea_id'] == null ? null : (j['tarea_id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    texto: j['texto'] == null ? null : j['texto'] as String,
    menciones: j['menciones'] == null ? null : j['menciones'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tarea_id': ?tareaId,
    'usuario_id': ?usuarioId,
    'texto': ?texto,
    'menciones': ?menciones,
    'creado_en': ?creadoEn,
  };
  ComentarioTarea copyWith({int? id, int? tareaId, int? usuarioId, String? texto, String? menciones, String? creadoEn, }) => ComentarioTarea(id: id ?? this.id, tareaId: tareaId ?? this.tareaId, usuarioId: usuarioId ?? this.usuarioId, texto: texto ?? this.texto, menciones: menciones ?? this.menciones, creadoEn: creadoEn ?? this.creadoEn, );
  @override bool operator ==(Object other) => other is ComentarioTarea && other.id == id && other.tareaId == tareaId && other.usuarioId == usuarioId && other.texto == texto && other.menciones == menciones && other.creadoEn == creadoEn;
  @override int get hashCode => Object.hashAll([id, tareaId, usuarioId, texto, menciones, creadoEn]);
}

class Companero {
  final int? id;
  final String? nombre;
  final String? email;
  const Companero({this.id, this.nombre, this.email, });
  factory Companero.fromJson(Map<String, dynamic> j) => Companero(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    email: j['email'] == null ? null : j['email'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
    'email': ?email,
  };
  Companero copyWith({int? id, String? nombre, String? email, }) => Companero(id: id ?? this.id, nombre: nombre ?? this.nombre, email: email ?? this.email, );
  @override bool operator ==(Object other) => other is Companero && other.id == id && other.nombre == nombre && other.email == email;
  @override int get hashCode => Object.hashAll([id, nombre, email]);
}

class Comunicado {
  final int? id;
  final String? titulo;
  final String? texto;
  final ComunicadoNivel? nivel;
  const Comunicado({this.id, this.titulo, this.texto, this.nivel, });
  factory Comunicado.fromJson(Map<String, dynamic> j) => Comunicado(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    texto: j['texto'] == null ? null : j['texto'] as String,
    nivel: j['nivel'] == null ? null : ComunicadoNivel.desde(j['nivel'] as String),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'titulo': ?titulo,
    'texto': ?texto,
    if (nivel != null) 'nivel': nivel!.valor,
  };
  Comunicado copyWith({int? id, String? titulo, String? texto, ComunicadoNivel? nivel, }) => Comunicado(id: id ?? this.id, titulo: titulo ?? this.titulo, texto: texto ?? this.texto, nivel: nivel ?? this.nivel, );
  @override bool operator ==(Object other) => other is Comunicado && other.id == id && other.titulo == titulo && other.texto == texto && other.nivel == nivel;
  @override int get hashCode => Object.hashAll([id, titulo, texto, nivel]);
}

class Concesion {
  final int id;
  final int? clienteFiscalId;
  final int? oficinaId;
  final int? usuarioId;
  final String? nivel;
  final String? vigenteHasta;
  final int? creadoPor;
  final String? creadoEn;
  final String? revocadaEn;
  final String? oficina;
  final String? persona;
  const Concesion({required this.id, this.clienteFiscalId, this.oficinaId, this.usuarioId, this.nivel, this.vigenteHasta, this.creadoPor, this.creadoEn, this.revocadaEn, this.oficina, this.persona, });
  factory Concesion.fromJson(Map<String, dynamic> j) => Concesion(
    id: (j['id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    oficinaId: j['oficina_id'] == null ? null : (j['oficina_id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nivel: j['nivel'] == null ? null : j['nivel'] as String,
    vigenteHasta: j['vigente_hasta'] == null ? null : j['vigente_hasta'] as String,
    creadoPor: j['creado_por'] == null ? null : (j['creado_por'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    revocadaEn: j['revocada_en'] == null ? null : j['revocada_en'] as String,
    oficina: j['oficina'] == null ? null : j['oficina'] as String,
    persona: j['persona'] == null ? null : j['persona'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'cliente_fiscal_id': ?clienteFiscalId,
    'oficina_id': ?oficinaId,
    'usuario_id': ?usuarioId,
    'nivel': ?nivel,
    'vigente_hasta': ?vigenteHasta,
    'creado_por': ?creadoPor,
    'creado_en': ?creadoEn,
    'revocada_en': ?revocadaEn,
    'oficina': ?oficina,
    'persona': ?persona,
  };
  Concesion copyWith({int? id, int? clienteFiscalId, int? oficinaId, int? usuarioId, String? nivel, String? vigenteHasta, int? creadoPor, String? creadoEn, String? revocadaEn, String? oficina, String? persona, }) => Concesion(id: id ?? this.id, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, oficinaId: oficinaId ?? this.oficinaId, usuarioId: usuarioId ?? this.usuarioId, nivel: nivel ?? this.nivel, vigenteHasta: vigenteHasta ?? this.vigenteHasta, creadoPor: creadoPor ?? this.creadoPor, creadoEn: creadoEn ?? this.creadoEn, revocadaEn: revocadaEn ?? this.revocadaEn, oficina: oficina ?? this.oficina, persona: persona ?? this.persona, );
  @override bool operator ==(Object other) => other is Concesion && other.id == id && other.clienteFiscalId == clienteFiscalId && other.oficinaId == oficinaId && other.usuarioId == usuarioId && other.nivel == nivel && other.vigenteHasta == vigenteHasta && other.creadoPor == creadoPor && other.creadoEn == creadoEn && other.revocadaEn == revocadaEn && other.oficina == oficina && other.persona == persona;
  @override int get hashCode => Object.hashAll([id, clienteFiscalId, oficinaId, usuarioId, nivel, vigenteHasta, creadoPor, creadoEn, revocadaEn, oficina, persona]);
}

class ConfigAvisosCertificados {
  final bool? avisarCliente;
  final bool? mostrarEnPortal;
  final List<int>? diasAntes;
  final List<int>? diasDespues;
  final String? asunto;
  final String? cuerpo;
  final String? instrucciones;
  const ConfigAvisosCertificados({this.avisarCliente, this.mostrarEnPortal, this.diasAntes, this.diasDespues, this.asunto, this.cuerpo, this.instrucciones, });
  factory ConfigAvisosCertificados.fromJson(Map<String, dynamic> j) => ConfigAvisosCertificados(
    avisarCliente: j['avisar_cliente'] == null ? null : _aBool(j['avisar_cliente']),
    mostrarEnPortal: j['mostrar_en_portal'] == null ? null : _aBool(j['mostrar_en_portal']),
    diasAntes: j['dias_antes'] == null ? null : (j['dias_antes'] as List).map((e) => (e as num).toInt()).toList(),
    diasDespues: j['dias_despues'] == null ? null : (j['dias_despues'] as List).map((e) => (e as num).toInt()).toList(),
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    cuerpo: j['cuerpo'] == null ? null : j['cuerpo'] as String,
    instrucciones: j['instrucciones'] == null ? null : j['instrucciones'] as String,
  );
  Map<String, dynamic> toJson() => {
    'avisar_cliente': ?avisarCliente,
    'mostrar_en_portal': ?mostrarEnPortal,
    if (diasAntes != null) 'dias_antes': diasAntes!.map((e) => e).toList(),
    if (diasDespues != null) 'dias_despues': diasDespues!.map((e) => e).toList(),
    'asunto': ?asunto,
    'cuerpo': ?cuerpo,
    'instrucciones': ?instrucciones,
  };
  ConfigAvisosCertificados copyWith({bool? avisarCliente, bool? mostrarEnPortal, List<int>? diasAntes, List<int>? diasDespues, String? asunto, String? cuerpo, String? instrucciones, }) => ConfigAvisosCertificados(avisarCliente: avisarCliente ?? this.avisarCliente, mostrarEnPortal: mostrarEnPortal ?? this.mostrarEnPortal, diasAntes: diasAntes ?? this.diasAntes, diasDespues: diasDespues ?? this.diasDespues, asunto: asunto ?? this.asunto, cuerpo: cuerpo ?? this.cuerpo, instrucciones: instrucciones ?? this.instrucciones, );
  @override bool operator ==(Object other) => other is ConfigAvisosCertificados && other.avisarCliente == avisarCliente && other.mostrarEnPortal == mostrarEnPortal && other.diasAntes == diasAntes && other.diasDespues == diasDespues && other.asunto == asunto && other.cuerpo == cuerpo && other.instrucciones == instrucciones;
  @override int get hashCode => Object.hashAll([avisarCliente, mostrarEnPortal, diasAntes, diasDespues, asunto, cuerpo, instrucciones]);
}

class ConfigAvisosFiscales {
  final bool? activo;
  final List<int>? diasAntes;
  final List<int>? diasCertificados;
  final int? escalarHorasUrgente;
  final int? escalarHorasAtencion;
  final int? reenviarHoras;
  final int? maxReenvios;
  const ConfigAvisosFiscales({this.activo, this.diasAntes, this.diasCertificados, this.escalarHorasUrgente, this.escalarHorasAtencion, this.reenviarHoras, this.maxReenvios, });
  factory ConfigAvisosFiscales.fromJson(Map<String, dynamic> j) => ConfigAvisosFiscales(
    activo: j['activo'] == null ? null : _aBool(j['activo']),
    diasAntes: j['dias_antes'] == null ? null : (j['dias_antes'] as List).map((e) => (e as num).toInt()).toList(),
    diasCertificados: j['dias_certificados'] == null ? null : (j['dias_certificados'] as List).map((e) => (e as num).toInt()).toList(),
    escalarHorasUrgente: j['escalar_horas_urgente'] == null ? null : (j['escalar_horas_urgente'] as num).toInt(),
    escalarHorasAtencion: j['escalar_horas_atencion'] == null ? null : (j['escalar_horas_atencion'] as num).toInt(),
    reenviarHoras: j['reenviar_horas'] == null ? null : (j['reenviar_horas'] as num).toInt(),
    maxReenvios: j['max_reenvios'] == null ? null : (j['max_reenvios'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'activo': ?activo,
    if (diasAntes != null) 'dias_antes': diasAntes!.map((e) => e).toList(),
    if (diasCertificados != null) 'dias_certificados': diasCertificados!.map((e) => e).toList(),
    'escalar_horas_urgente': ?escalarHorasUrgente,
    'escalar_horas_atencion': ?escalarHorasAtencion,
    'reenviar_horas': ?reenviarHoras,
    'max_reenvios': ?maxReenvios,
  };
  ConfigAvisosFiscales copyWith({bool? activo, List<int>? diasAntes, List<int>? diasCertificados, int? escalarHorasUrgente, int? escalarHorasAtencion, int? reenviarHoras, int? maxReenvios, }) => ConfigAvisosFiscales(activo: activo ?? this.activo, diasAntes: diasAntes ?? this.diasAntes, diasCertificados: diasCertificados ?? this.diasCertificados, escalarHorasUrgente: escalarHorasUrgente ?? this.escalarHorasUrgente, escalarHorasAtencion: escalarHorasAtencion ?? this.escalarHorasAtencion, reenviarHoras: reenviarHoras ?? this.reenviarHoras, maxReenvios: maxReenvios ?? this.maxReenvios, );
  @override bool operator ==(Object other) => other is ConfigAvisosFiscales && other.activo == activo && other.diasAntes == diasAntes && other.diasCertificados == diasCertificados && other.escalarHorasUrgente == escalarHorasUrgente && other.escalarHorasAtencion == escalarHorasAtencion && other.reenviarHoras == reenviarHoras && other.maxReenvios == maxReenvios;
  @override int get hashCode => Object.hashAll([activo, diasAntes, diasCertificados, escalarHorasUrgente, escalarHorasAtencion, reenviarHoras, maxReenvios]);
}

class ConfigFlujo {
  final bool? flujoEstricto;
  final bool? exigirJustificante;
  const ConfigFlujo({this.flujoEstricto, this.exigirJustificante, });
  factory ConfigFlujo.fromJson(Map<String, dynamic> j) => ConfigFlujo(
    flujoEstricto: j['flujo_estricto'] == null ? null : _aBool(j['flujo_estricto']),
    exigirJustificante: j['exigir_justificante'] == null ? null : _aBool(j['exigir_justificante']),
  );
  Map<String, dynamic> toJson() => {
    'flujo_estricto': ?flujoEstricto,
    'exigir_justificante': ?exigirJustificante,
  };
  ConfigFlujo copyWith({bool? flujoEstricto, bool? exigirJustificante, }) => ConfigFlujo(flujoEstricto: flujoEstricto ?? this.flujoEstricto, exigirJustificante: exigirJustificante ?? this.exigirJustificante, );
  @override bool operator ==(Object other) => other is ConfigFlujo && other.flujoEstricto == flujoEstricto && other.exigirJustificante == exigirJustificante;
  @override int get hashCode => Object.hashAll([flujoEstricto, exigirJustificante]);
}

class ConfigRecordatorios {
  final List<int>? diasAntes;
  final List<int>? diasDespues;
  final bool? avisarEquipo;
  final String? asunto;
  final String? cuerpo;
  const ConfigRecordatorios({this.diasAntes, this.diasDespues, this.avisarEquipo, this.asunto, this.cuerpo, });
  factory ConfigRecordatorios.fromJson(Map<String, dynamic> j) => ConfigRecordatorios(
    diasAntes: j['dias_antes'] == null ? null : (j['dias_antes'] as List).map((e) => (e as num).toInt()).toList(),
    diasDespues: j['dias_despues'] == null ? null : (j['dias_despues'] as List).map((e) => (e as num).toInt()).toList(),
    avisarEquipo: j['avisar_equipo'] == null ? null : _aBool(j['avisar_equipo']),
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    cuerpo: j['cuerpo'] == null ? null : j['cuerpo'] as String,
  );
  Map<String, dynamic> toJson() => {
    if (diasAntes != null) 'dias_antes': diasAntes!.map((e) => e).toList(),
    if (diasDespues != null) 'dias_despues': diasDespues!.map((e) => e).toList(),
    'avisar_equipo': ?avisarEquipo,
    'asunto': ?asunto,
    'cuerpo': ?cuerpo,
  };
  ConfigRecordatorios copyWith({List<int>? diasAntes, List<int>? diasDespues, bool? avisarEquipo, String? asunto, String? cuerpo, }) => ConfigRecordatorios(diasAntes: diasAntes ?? this.diasAntes, diasDespues: diasDespues ?? this.diasDespues, avisarEquipo: avisarEquipo ?? this.avisarEquipo, asunto: asunto ?? this.asunto, cuerpo: cuerpo ?? this.cuerpo, );
  @override bool operator ==(Object other) => other is ConfigRecordatorios && other.diasAntes == diasAntes && other.diasDespues == diasDespues && other.avisarEquipo == avisarEquipo && other.asunto == asunto && other.cuerpo == cuerpo;
  @override int get hashCode => Object.hashAll([diasAntes, diasDespues, avisarEquipo, asunto, cuerpo]);
}

class ConsumoIA {
  final String? mes;
  final int? usadas;
  final int? limite;
  final bool? ilimitado;
  final int? restantes;
  final int? pct;
  const ConsumoIA({this.mes, this.usadas, this.limite, this.ilimitado, this.restantes, this.pct, });
  factory ConsumoIA.fromJson(Map<String, dynamic> j) => ConsumoIA(
    mes: j['mes'] == null ? null : j['mes'] as String,
    usadas: j['usadas'] == null ? null : (j['usadas'] as num).toInt(),
    limite: j['limite'] == null ? null : (j['limite'] as num).toInt(),
    ilimitado: j['ilimitado'] == null ? null : _aBool(j['ilimitado']),
    restantes: j['restantes'] == null ? null : (j['restantes'] as num).toInt(),
    pct: j['pct'] == null ? null : (j['pct'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'mes': ?mes,
    'usadas': ?usadas,
    'limite': ?limite,
    'ilimitado': ?ilimitado,
    'restantes': ?restantes,
    'pct': ?pct,
  };
  ConsumoIA copyWith({String? mes, int? usadas, int? limite, bool? ilimitado, int? restantes, int? pct, }) => ConsumoIA(mes: mes ?? this.mes, usadas: usadas ?? this.usadas, limite: limite ?? this.limite, ilimitado: ilimitado ?? this.ilimitado, restantes: restantes ?? this.restantes, pct: pct ?? this.pct, );
  @override bool operator ==(Object other) => other is ConsumoIA && other.mes == mes && other.usadas == usadas && other.limite == limite && other.ilimitado == ilimitado && other.restantes == restantes && other.pct == pct;
  @override int get hashCode => Object.hashAll([mes, usadas, limite, ilimitado, restantes, pct]);
}

class ConversacionCliente {
  final int? clienteFiscalId;
  final String? cliente;
  final int? sinLeer;
  final List<Map<String, dynamic>>? mensajes;
  const ConversacionCliente({this.clienteFiscalId, this.cliente, this.sinLeer, this.mensajes, });
  factory ConversacionCliente.fromJson(Map<String, dynamic> j) => ConversacionCliente(
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    sinLeer: j['sin_leer'] == null ? null : (j['sin_leer'] as num).toInt(),
    mensajes: j['mensajes'] == null ? null : (j['mensajes'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'cliente_fiscal_id': ?clienteFiscalId,
    'cliente': ?cliente,
    'sin_leer': ?sinLeer,
    if (mensajes != null) 'mensajes': mensajes!.map((e) => e).toList(),
  };
  ConversacionCliente copyWith({int? clienteFiscalId, String? cliente, int? sinLeer, List<Map<String, dynamic>>? mensajes, }) => ConversacionCliente(clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, cliente: cliente ?? this.cliente, sinLeer: sinLeer ?? this.sinLeer, mensajes: mensajes ?? this.mensajes, );
  @override bool operator ==(Object other) => other is ConversacionCliente && other.clienteFiscalId == clienteFiscalId && other.cliente == cliente && other.sinLeer == sinLeer && other.mensajes == mensajes;
  @override int get hashCode => Object.hashAll([clienteFiscalId, cliente, sinLeer, mensajes]);
}

class ConversacionIA {
  final int id;
  final int? usuarioId;
  final String? titulo;
  final String? creadaEn;
  final String? actualizadaEn;
  final int? activa;
  const ConversacionIA({required this.id, this.usuarioId, this.titulo, this.creadaEn, this.actualizadaEn, this.activa, });
  factory ConversacionIA.fromJson(Map<String, dynamic> j) => ConversacionIA(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    actualizadaEn: j['actualizada_en'] == null ? null : j['actualizada_en'] as String,
    activa: j['activa'] == null ? null : (j['activa'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'titulo': ?titulo,
    'creada_en': ?creadaEn,
    'actualizada_en': ?actualizadaEn,
    'activa': ?activa,
  };
  ConversacionIA copyWith({int? id, int? usuarioId, String? titulo, String? creadaEn, String? actualizadaEn, int? activa, }) => ConversacionIA(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, titulo: titulo ?? this.titulo, creadaEn: creadaEn ?? this.creadaEn, actualizadaEn: actualizadaEn ?? this.actualizadaEn, activa: activa ?? this.activa, );
  @override bool operator ==(Object other) => other is ConversacionIA && other.id == id && other.usuarioId == usuarioId && other.titulo == titulo && other.creadaEn == creadaEn && other.actualizadaEn == actualizadaEn && other.activa == activa;
  @override int get hashCode => Object.hashAll([id, usuarioId, titulo, creadaEn, actualizadaEn, activa]);
}

class ConversacionesIA {
  final int? activa;
  final List<ConversacionIA>? conversaciones;
  const ConversacionesIA({this.activa, this.conversaciones, });
  factory ConversacionesIA.fromJson(Map<String, dynamic> j) => ConversacionesIA(
    activa: j['activa'] == null ? null : (j['activa'] as num).toInt(),
    conversaciones: j['conversaciones'] == null ? null : (j['conversaciones'] as List).map((e) => ConversacionIA.fromJson(e as Map<String, dynamic>)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'activa': ?activa,
    if (conversaciones != null) 'conversaciones': conversaciones!.map((e) => e.toJson()).toList(),
  };
  ConversacionesIA copyWith({int? activa, List<ConversacionIA>? conversaciones, }) => ConversacionesIA(activa: activa ?? this.activa, conversaciones: conversaciones ?? this.conversaciones, );
  @override bool operator ==(Object other) => other is ConversacionesIA && other.activa == activa && other.conversaciones == conversaciones;
  @override int get hashCode => Object.hashAll([activa, conversaciones]);
}

class ConversionComercial {
  final int? clienteId;
  final int? clienteFiscalId;
  const ConversionComercial({this.clienteId, this.clienteFiscalId, });
  factory ConversionComercial.fromJson(Map<String, dynamic> j) => ConversionComercial(
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'cliente_id': ?clienteId,
    'cliente_fiscal_id': ?clienteFiscalId,
  };
  ConversionComercial copyWith({int? clienteId, int? clienteFiscalId, }) => ConversionComercial(clienteId: clienteId ?? this.clienteId, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, );
  @override bool operator ==(Object other) => other is ConversionComercial && other.clienteId == clienteId && other.clienteFiscalId == clienteFiscalId;
  @override int get hashCode => Object.hashAll([clienteId, clienteFiscalId]);
}

class CruceDemanda {
  final int? puntos;
  final List<String>? motivos;
  final List<dynamic>? faltan;
  final Map<String, dynamic>? inmueble;
  const CruceDemanda({this.puntos, this.motivos, this.faltan, this.inmueble, });
  factory CruceDemanda.fromJson(Map<String, dynamic> j) => CruceDemanda(
    puntos: j['puntos'] == null ? null : (j['puntos'] as num).toInt(),
    motivos: j['motivos'] == null ? null : (j['motivos'] as List).map((e) => e as String).toList(),
    faltan: j['faltan'] == null ? null : (j['faltan'] as List).map((e) => e).toList(),
    inmueble: j['inmueble'] == null ? null : Map<String, dynamic>.from(j['inmueble'] as Map),
  );
  Map<String, dynamic> toJson() => {
    'puntos': ?puntos,
    if (motivos != null) 'motivos': motivos!.map((e) => e).toList(),
    if (faltan != null) 'faltan': faltan!.map((e) => e).toList(),
    'inmueble': ?inmueble,
  };
  CruceDemanda copyWith({int? puntos, List<String>? motivos, List<dynamic>? faltan, Map<String, dynamic>? inmueble, }) => CruceDemanda(puntos: puntos ?? this.puntos, motivos: motivos ?? this.motivos, faltan: faltan ?? this.faltan, inmueble: inmueble ?? this.inmueble, );
  @override bool operator ==(Object other) => other is CruceDemanda && other.puntos == puntos && other.motivos == motivos && other.faltan == faltan && other.inmueble == inmueble;
  @override int get hashCode => Object.hashAll([puntos, motivos, faltan, inmueble]);
}

class Cuadrante {
  final List<String>? dias;
  final List<Map<String, dynamic>>? personas;
  const Cuadrante({this.dias, this.personas, });
  factory Cuadrante.fromJson(Map<String, dynamic> j) => Cuadrante(
    dias: j['dias'] == null ? null : (j['dias'] as List).map((e) => e as String).toList(),
    personas: j['personas'] == null ? null : (j['personas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    if (dias != null) 'dias': dias!.map((e) => e).toList(),
    if (personas != null) 'personas': personas!.map((e) => e).toList(),
  };
  Cuadrante copyWith({List<String>? dias, List<Map<String, dynamic>>? personas, }) => Cuadrante(dias: dias ?? this.dias, personas: personas ?? this.personas, );
  @override bool operator ==(Object other) => other is Cuadrante && other.dias == dias && other.personas == personas;
  @override int get hashCode => Object.hashAll([dias, personas]);
}

class CuentaCorreo {
  final int id;
  final int? usuarioId;
  final String? nombre;
  final String? protocolo;
  final String? host;
  final int? puerto;
  final int? usaTls;
  final String? usuario;
  final String? smtpHost;
  final int? smtpPuerto;
  final int? smtpTls;
  final String? creadaEn;
  final String? ultimaSincronizacion;
  final String? firmaHtml;
  final int? firmaEnNuevos;
  final int? firmaEnRespuestas;
  final String? ultimoErrorSincronizacion;
  final String? ultimoErrorSincronizacionEn;
  final String? authTipo;
  const CuentaCorreo({required this.id, this.usuarioId, this.nombre, this.protocolo, this.host, this.puerto, this.usaTls, this.usuario, this.smtpHost, this.smtpPuerto, this.smtpTls, this.creadaEn, this.ultimaSincronizacion, this.firmaHtml, this.firmaEnNuevos, this.firmaEnRespuestas, this.ultimoErrorSincronizacion, this.ultimoErrorSincronizacionEn, this.authTipo, });
  factory CuentaCorreo.fromJson(Map<String, dynamic> j) => CuentaCorreo(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    protocolo: j['protocolo'] == null ? null : j['protocolo'] as String,
    host: j['host'] == null ? null : j['host'] as String,
    puerto: j['puerto'] == null ? null : (j['puerto'] as num).toInt(),
    usaTls: j['usa_tls'] == null ? null : (j['usa_tls'] as num).toInt(),
    usuario: j['usuario'] == null ? null : j['usuario'] as String,
    smtpHost: j['smtp_host'] == null ? null : j['smtp_host'] as String,
    smtpPuerto: j['smtp_puerto'] == null ? null : (j['smtp_puerto'] as num).toInt(),
    smtpTls: j['smtp_tls'] == null ? null : (j['smtp_tls'] as num).toInt(),
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    ultimaSincronizacion: j['ultima_sincronizacion'] == null ? null : j['ultima_sincronizacion'] as String,
    firmaHtml: j['firma_html'] == null ? null : j['firma_html'] as String,
    firmaEnNuevos: j['firma_en_nuevos'] == null ? null : (j['firma_en_nuevos'] as num).toInt(),
    firmaEnRespuestas: j['firma_en_respuestas'] == null ? null : (j['firma_en_respuestas'] as num).toInt(),
    ultimoErrorSincronizacion: j['ultimo_error_sincronizacion'] == null ? null : j['ultimo_error_sincronizacion'] as String,
    ultimoErrorSincronizacionEn: j['ultimo_error_sincronizacion_en'] == null ? null : j['ultimo_error_sincronizacion_en'] as String,
    authTipo: j['auth_tipo'] == null ? null : j['auth_tipo'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'nombre': ?nombre,
    'protocolo': ?protocolo,
    'host': ?host,
    'puerto': ?puerto,
    'usa_tls': ?usaTls,
    'usuario': ?usuario,
    'smtp_host': ?smtpHost,
    'smtp_puerto': ?smtpPuerto,
    'smtp_tls': ?smtpTls,
    'creada_en': ?creadaEn,
    'ultima_sincronizacion': ?ultimaSincronizacion,
    'firma_html': ?firmaHtml,
    'firma_en_nuevos': ?firmaEnNuevos,
    'firma_en_respuestas': ?firmaEnRespuestas,
    'ultimo_error_sincronizacion': ?ultimoErrorSincronizacion,
    'ultimo_error_sincronizacion_en': ?ultimoErrorSincronizacionEn,
    'auth_tipo': ?authTipo,
  };
  CuentaCorreo copyWith({int? id, int? usuarioId, String? nombre, String? protocolo, String? host, int? puerto, int? usaTls, String? usuario, String? smtpHost, int? smtpPuerto, int? smtpTls, String? creadaEn, String? ultimaSincronizacion, String? firmaHtml, int? firmaEnNuevos, int? firmaEnRespuestas, String? ultimoErrorSincronizacion, String? ultimoErrorSincronizacionEn, String? authTipo, }) => CuentaCorreo(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, nombre: nombre ?? this.nombre, protocolo: protocolo ?? this.protocolo, host: host ?? this.host, puerto: puerto ?? this.puerto, usaTls: usaTls ?? this.usaTls, usuario: usuario ?? this.usuario, smtpHost: smtpHost ?? this.smtpHost, smtpPuerto: smtpPuerto ?? this.smtpPuerto, smtpTls: smtpTls ?? this.smtpTls, creadaEn: creadaEn ?? this.creadaEn, ultimaSincronizacion: ultimaSincronizacion ?? this.ultimaSincronizacion, firmaHtml: firmaHtml ?? this.firmaHtml, firmaEnNuevos: firmaEnNuevos ?? this.firmaEnNuevos, firmaEnRespuestas: firmaEnRespuestas ?? this.firmaEnRespuestas, ultimoErrorSincronizacion: ultimoErrorSincronizacion ?? this.ultimoErrorSincronizacion, ultimoErrorSincronizacionEn: ultimoErrorSincronizacionEn ?? this.ultimoErrorSincronizacionEn, authTipo: authTipo ?? this.authTipo, );
  @override bool operator ==(Object other) => other is CuentaCorreo && other.id == id && other.usuarioId == usuarioId && other.nombre == nombre && other.protocolo == protocolo && other.host == host && other.puerto == puerto && other.usaTls == usaTls && other.usuario == usuario && other.smtpHost == smtpHost && other.smtpPuerto == smtpPuerto && other.smtpTls == smtpTls && other.creadaEn == creadaEn && other.ultimaSincronizacion == ultimaSincronizacion && other.firmaHtml == firmaHtml && other.firmaEnNuevos == firmaEnNuevos && other.firmaEnRespuestas == firmaEnRespuestas && other.ultimoErrorSincronizacion == ultimoErrorSincronizacion && other.ultimoErrorSincronizacionEn == ultimoErrorSincronizacionEn && other.authTipo == authTipo;
  @override int get hashCode => Object.hashAll([id, usuarioId, nombre, protocolo, host, puerto, usaTls, usuario, smtpHost, smtpPuerto, smtpTls, creadaEn, ultimaSincronizacion, firmaHtml, firmaEnNuevos, firmaEnRespuestas, ultimoErrorSincronizacion, ultimoErrorSincronizacionEn, authTipo]);
}

class DespachoDeUsuario {
  final int? id;
  final String? nombre;
  final bool? principal;
  final bool? gestorFichajes;
  final bool? supervisor;
  const DespachoDeUsuario({this.id, this.nombre, this.principal, this.gestorFichajes, this.supervisor, });
  factory DespachoDeUsuario.fromJson(Map<String, dynamic> j) => DespachoDeUsuario(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    principal: j['principal'] == null ? null : _aBool(j['principal']),
    gestorFichajes: j['gestor_fichajes'] == null ? null : _aBool(j['gestor_fichajes']),
    supervisor: j['supervisor'] == null ? null : _aBool(j['supervisor']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
    'principal': ?principal,
    'gestor_fichajes': ?gestorFichajes,
    'supervisor': ?supervisor,
  };
  DespachoDeUsuario copyWith({int? id, String? nombre, bool? principal, bool? gestorFichajes, bool? supervisor, }) => DespachoDeUsuario(id: id ?? this.id, nombre: nombre ?? this.nombre, principal: principal ?? this.principal, gestorFichajes: gestorFichajes ?? this.gestorFichajes, supervisor: supervisor ?? this.supervisor, );
  @override bool operator ==(Object other) => other is DespachoDeUsuario && other.id == id && other.nombre == nombre && other.principal == principal && other.gestorFichajes == gestorFichajes && other.supervisor == supervisor;
  @override int get hashCode => Object.hashAll([id, nombre, principal, gestorFichajes, supervisor]);
}

class DestinatarioReciente {
  final String? email;
  final String? nombre;
  const DestinatarioReciente({this.email, this.nombre, });
  factory DestinatarioReciente.fromJson(Map<String, dynamic> j) => DestinatarioReciente(
    email: j['email'] == null ? null : j['email'] as String,
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
  );
  Map<String, dynamic> toJson() => {
    'email': ?email,
    'nombre': ?nombre,
  };
  DestinatarioReciente copyWith({String? email, String? nombre, }) => DestinatarioReciente(email: email ?? this.email, nombre: nombre ?? this.nombre, );
  @override bool operator ==(Object other) => other is DestinatarioReciente && other.email == email && other.nombre == nombre;
  @override int get hashCode => Object.hashAll([email, nombre]);
}

class DestinoAviso {
  final String? tipo;
  final int? id;
  const DestinoAviso({this.tipo, this.id, });
  factory DestinoAviso.fromJson(Map<String, dynamic> j) => DestinoAviso(
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'tipo': ?tipo,
    'id': ?id,
  };
  DestinoAviso copyWith({String? tipo, int? id, }) => DestinoAviso(tipo: tipo ?? this.tipo, id: id ?? this.id, );
  @override bool operator ==(Object other) => other is DestinoAviso && other.tipo == tipo && other.id == id;
  @override int get hashCode => Object.hashAll([tipo, id]);
}

class DestinoHoy {
  final DestinoHoyTipo? tipo;
  final int? id;
  const DestinoHoy({this.tipo, this.id, });
  factory DestinoHoy.fromJson(Map<String, dynamic> j) => DestinoHoy(
    tipo: j['tipo'] == null ? null : DestinoHoyTipo.desde(j['tipo'] as String),
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    if (tipo != null) 'tipo': tipo!.valor,
    'id': ?id,
  };
  DestinoHoy copyWith({DestinoHoyTipo? tipo, int? id, }) => DestinoHoy(tipo: tipo ?? this.tipo, id: id ?? this.id, );
  @override bool operator ==(Object other) => other is DestinoHoy && other.tipo == tipo && other.id == id;
  @override int get hashCode => Object.hashAll([tipo, id]);
}

class DetalleExpedienteControl {
  final int? id;
  final String? tipo;
  final String? titulo;
  final String? descripcion;
  final String? estado;
  final String? cliente;
  final int? responsableId;
  final String? responsable;
  final String? abiertoEn;
  final String? cerradoEn;
  final Map<String, dynamic>? control;
  final List<Map<String, dynamic>>? lista;
  final List<Map<String, dynamic>>? documentos;
  final int? faltanObligatorios;
  final bool? nuevo;
  const DetalleExpedienteControl({this.id, this.tipo, this.titulo, this.descripcion, this.estado, this.cliente, this.responsableId, this.responsable, this.abiertoEn, this.cerradoEn, this.control, this.lista, this.documentos, this.faltanObligatorios, this.nuevo, });
  factory DetalleExpedienteControl.fromJson(Map<String, dynamic> j) => DetalleExpedienteControl(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    descripcion: j['descripcion'] == null ? null : j['descripcion'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    responsableId: j['responsable_id'] == null ? null : (j['responsable_id'] as num).toInt(),
    responsable: j['responsable'] == null ? null : j['responsable'] as String,
    abiertoEn: j['abierto_en'] == null ? null : j['abierto_en'] as String,
    cerradoEn: j['cerrado_en'] == null ? null : j['cerrado_en'] as String,
    control: j['control'] == null ? null : Map<String, dynamic>.from(j['control'] as Map),
    lista: j['lista'] == null ? null : (j['lista'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    documentos: j['documentos'] == null ? null : (j['documentos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    faltanObligatorios: j['faltan_obligatorios'] == null ? null : (j['faltan_obligatorios'] as num).toInt(),
    nuevo: j['nuevo'] == null ? null : _aBool(j['nuevo']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'tipo': ?tipo,
    'titulo': ?titulo,
    'descripcion': ?descripcion,
    'estado': ?estado,
    'cliente': ?cliente,
    'responsable_id': ?responsableId,
    'responsable': ?responsable,
    'abierto_en': ?abiertoEn,
    'cerrado_en': ?cerradoEn,
    'control': ?control,
    if (lista != null) 'lista': lista!.map((e) => e).toList(),
    if (documentos != null) 'documentos': documentos!.map((e) => e).toList(),
    'faltan_obligatorios': ?faltanObligatorios,
    'nuevo': ?nuevo,
  };
  DetalleExpedienteControl copyWith({int? id, String? tipo, String? titulo, String? descripcion, String? estado, String? cliente, int? responsableId, String? responsable, String? abiertoEn, String? cerradoEn, Map<String, dynamic>? control, List<Map<String, dynamic>>? lista, List<Map<String, dynamic>>? documentos, int? faltanObligatorios, bool? nuevo, }) => DetalleExpedienteControl(id: id ?? this.id, tipo: tipo ?? this.tipo, titulo: titulo ?? this.titulo, descripcion: descripcion ?? this.descripcion, estado: estado ?? this.estado, cliente: cliente ?? this.cliente, responsableId: responsableId ?? this.responsableId, responsable: responsable ?? this.responsable, abiertoEn: abiertoEn ?? this.abiertoEn, cerradoEn: cerradoEn ?? this.cerradoEn, control: control ?? this.control, lista: lista ?? this.lista, documentos: documentos ?? this.documentos, faltanObligatorios: faltanObligatorios ?? this.faltanObligatorios, nuevo: nuevo ?? this.nuevo, );
  @override bool operator ==(Object other) => other is DetalleExpedienteControl && other.id == id && other.tipo == tipo && other.titulo == titulo && other.descripcion == descripcion && other.estado == estado && other.cliente == cliente && other.responsableId == responsableId && other.responsable == responsable && other.abiertoEn == abiertoEn && other.cerradoEn == cerradoEn && other.control == control && other.lista == lista && other.documentos == documentos && other.faltanObligatorios == faltanObligatorios && other.nuevo == nuevo;
  @override int get hashCode => Object.hashAll([id, tipo, titulo, descripcion, estado, cliente, responsableId, responsable, abiertoEn, cerradoEn, control, lista, documentos, faltanObligatorios, nuevo]);
}

class DocumentoCliente {
  final int id;
  final int? tenantId;
  final int? clienteFiscalId;
  final String? nombreArchivo;
  final String? tipoMime;
  final int? tamanoBytes;
  final String? categoria;
  final String? origen;
  final int? mensajeCorreoId;
  final String? asuntoOrigen;
  final int? subidoPor;
  final String? hashSha256;
  final String? creadoEn;
  final int? cifrado;
  final String? nombreCifrado;
  const DocumentoCliente({required this.id, this.tenantId, this.clienteFiscalId, this.nombreArchivo, this.tipoMime, this.tamanoBytes, this.categoria, this.origen, this.mensajeCorreoId, this.asuntoOrigen, this.subidoPor, this.hashSha256, this.creadoEn, this.cifrado, this.nombreCifrado, });
  factory DocumentoCliente.fromJson(Map<String, dynamic> j) => DocumentoCliente(
    id: (j['id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    nombreArchivo: j['nombre_archivo'] == null ? null : j['nombre_archivo'] as String,
    tipoMime: j['tipo_mime'] == null ? null : j['tipo_mime'] as String,
    tamanoBytes: j['tamano_bytes'] == null ? null : (j['tamano_bytes'] as num).toInt(),
    categoria: j['categoria'] == null ? null : j['categoria'] as String,
    origen: j['origen'] == null ? null : j['origen'] as String,
    mensajeCorreoId: j['mensaje_correo_id'] == null ? null : (j['mensaje_correo_id'] as num).toInt(),
    asuntoOrigen: j['asunto_origen'] == null ? null : j['asunto_origen'] as String,
    subidoPor: j['subido_por'] == null ? null : (j['subido_por'] as num).toInt(),
    hashSha256: j['hash_sha256'] == null ? null : j['hash_sha256'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    cifrado: j['cifrado'] == null ? null : (j['cifrado'] as num).toInt(),
    nombreCifrado: j['nombre_cifrado'] == null ? null : j['nombre_cifrado'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tenant_id': ?tenantId,
    'cliente_fiscal_id': ?clienteFiscalId,
    'nombre_archivo': ?nombreArchivo,
    'tipo_mime': ?tipoMime,
    'tamano_bytes': ?tamanoBytes,
    'categoria': ?categoria,
    'origen': ?origen,
    'mensaje_correo_id': ?mensajeCorreoId,
    'asunto_origen': ?asuntoOrigen,
    'subido_por': ?subidoPor,
    'hash_sha256': ?hashSha256,
    'creado_en': ?creadoEn,
    'cifrado': ?cifrado,
    'nombre_cifrado': ?nombreCifrado,
  };
  DocumentoCliente copyWith({int? id, int? tenantId, int? clienteFiscalId, String? nombreArchivo, String? tipoMime, int? tamanoBytes, String? categoria, String? origen, int? mensajeCorreoId, String? asuntoOrigen, int? subidoPor, String? hashSha256, String? creadoEn, int? cifrado, String? nombreCifrado, }) => DocumentoCliente(id: id ?? this.id, tenantId: tenantId ?? this.tenantId, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, nombreArchivo: nombreArchivo ?? this.nombreArchivo, tipoMime: tipoMime ?? this.tipoMime, tamanoBytes: tamanoBytes ?? this.tamanoBytes, categoria: categoria ?? this.categoria, origen: origen ?? this.origen, mensajeCorreoId: mensajeCorreoId ?? this.mensajeCorreoId, asuntoOrigen: asuntoOrigen ?? this.asuntoOrigen, subidoPor: subidoPor ?? this.subidoPor, hashSha256: hashSha256 ?? this.hashSha256, creadoEn: creadoEn ?? this.creadoEn, cifrado: cifrado ?? this.cifrado, nombreCifrado: nombreCifrado ?? this.nombreCifrado, );
  @override bool operator ==(Object other) => other is DocumentoCliente && other.id == id && other.tenantId == tenantId && other.clienteFiscalId == clienteFiscalId && other.nombreArchivo == nombreArchivo && other.tipoMime == tipoMime && other.tamanoBytes == tamanoBytes && other.categoria == categoria && other.origen == origen && other.mensajeCorreoId == mensajeCorreoId && other.asuntoOrigen == asuntoOrigen && other.subidoPor == subidoPor && other.hashSha256 == hashSha256 && other.creadoEn == creadoEn && other.cifrado == cifrado && other.nombreCifrado == nombreCifrado;
  @override int get hashCode => Object.hashAll([id, tenantId, clienteFiscalId, nombreArchivo, tipoMime, tamanoBytes, categoria, origen, mensajeCorreoId, asuntoOrigen, subidoPor, hashSha256, creadoEn, cifrado, nombreCifrado]);
}

class DocumentoDespacho {
  final int id;
  final int? clienteId;
  final int? expedienteId;
  final String? nombreArchivo;
  final String? tipoMime;
  final int? tamanoBytes;
  final String? categoria;
  final int? cifrado;
  final String? origen;
  final String? creadoEn;
  final String? nombreCifrado;
  final int? version;
  final int? reemplazaA;
  final String? conservarHasta;
  final bool? contenidoDisponible;
  const DocumentoDespacho({required this.id, this.clienteId, this.expedienteId, this.nombreArchivo, this.tipoMime, this.tamanoBytes, this.categoria, this.cifrado, this.origen, this.creadoEn, this.nombreCifrado, this.version, this.reemplazaA, this.conservarHasta, this.contenidoDisponible, });
  factory DocumentoDespacho.fromJson(Map<String, dynamic> j) => DocumentoDespacho(
    id: (j['id'] as num).toInt(),
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    expedienteId: j['expediente_id'] == null ? null : (j['expediente_id'] as num).toInt(),
    nombreArchivo: j['nombre_archivo'] == null ? null : j['nombre_archivo'] as String,
    tipoMime: j['tipo_mime'] == null ? null : j['tipo_mime'] as String,
    tamanoBytes: j['tamano_bytes'] == null ? null : (j['tamano_bytes'] as num).toInt(),
    categoria: j['categoria'] == null ? null : j['categoria'] as String,
    cifrado: j['cifrado'] == null ? null : (j['cifrado'] as num).toInt(),
    origen: j['origen'] == null ? null : j['origen'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    nombreCifrado: j['nombre_cifrado'] == null ? null : j['nombre_cifrado'] as String,
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    reemplazaA: j['reemplaza_a'] == null ? null : (j['reemplaza_a'] as num).toInt(),
    conservarHasta: j['conservar_hasta'] == null ? null : j['conservar_hasta'] as String,
    contenidoDisponible: j['contenido_disponible'] == null ? null : _aBool(j['contenido_disponible']),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'cliente_id': ?clienteId,
    'expediente_id': ?expedienteId,
    'nombre_archivo': ?nombreArchivo,
    'tipo_mime': ?tipoMime,
    'tamano_bytes': ?tamanoBytes,
    'categoria': ?categoria,
    'cifrado': ?cifrado,
    'origen': ?origen,
    'creado_en': ?creadoEn,
    'nombre_cifrado': ?nombreCifrado,
    'version': ?version,
    'reemplaza_a': ?reemplazaA,
    'conservar_hasta': ?conservarHasta,
    'contenido_disponible': ?contenidoDisponible,
  };
  DocumentoDespacho copyWith({int? id, int? clienteId, int? expedienteId, String? nombreArchivo, String? tipoMime, int? tamanoBytes, String? categoria, int? cifrado, String? origen, String? creadoEn, String? nombreCifrado, int? version, int? reemplazaA, String? conservarHasta, bool? contenidoDisponible, }) => DocumentoDespacho(id: id ?? this.id, clienteId: clienteId ?? this.clienteId, expedienteId: expedienteId ?? this.expedienteId, nombreArchivo: nombreArchivo ?? this.nombreArchivo, tipoMime: tipoMime ?? this.tipoMime, tamanoBytes: tamanoBytes ?? this.tamanoBytes, categoria: categoria ?? this.categoria, cifrado: cifrado ?? this.cifrado, origen: origen ?? this.origen, creadoEn: creadoEn ?? this.creadoEn, nombreCifrado: nombreCifrado ?? this.nombreCifrado, version: version ?? this.version, reemplazaA: reemplazaA ?? this.reemplazaA, conservarHasta: conservarHasta ?? this.conservarHasta, contenidoDisponible: contenidoDisponible ?? this.contenidoDisponible, );
  @override bool operator ==(Object other) => other is DocumentoDespacho && other.id == id && other.clienteId == clienteId && other.expedienteId == expedienteId && other.nombreArchivo == nombreArchivo && other.tipoMime == tipoMime && other.tamanoBytes == tamanoBytes && other.categoria == categoria && other.cifrado == cifrado && other.origen == origen && other.creadoEn == creadoEn && other.nombreCifrado == nombreCifrado && other.version == version && other.reemplazaA == reemplazaA && other.conservarHasta == conservarHasta && other.contenidoDisponible == contenidoDisponible;
  @override int get hashCode => Object.hashAll([id, clienteId, expedienteId, nombreArchivo, tipoMime, tamanoBytes, categoria, cifrado, origen, creadoEn, nombreCifrado, version, reemplazaA, conservarHasta, contenidoDisponible]);
}

class DocumentoJuridico {
  final int? id;
  final String? fuenteId;
  final String? idExterno;
  final String? coleccion;
  final String? titulo;
  final String? emisor;
  final String? rango;
  final String? tipo;
  final String? ecli;
  final String? eli;
  final String? estadoNormativo;
  final String? fechaPublicacion;
  final String? fechaResolucion;
  final String? urlCanonica;
  final String? atribucion;
  final List<Map<String, dynamic>>? versiones;
  final List<Map<String, dynamic>>? relaciones;
  const DocumentoJuridico({this.id, this.fuenteId, this.idExterno, this.coleccion, this.titulo, this.emisor, this.rango, this.tipo, this.ecli, this.eli, this.estadoNormativo, this.fechaPublicacion, this.fechaResolucion, this.urlCanonica, this.atribucion, this.versiones, this.relaciones, });
  factory DocumentoJuridico.fromJson(Map<String, dynamic> j) => DocumentoJuridico(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    fuenteId: j['fuente_id'] == null ? null : j['fuente_id'] as String,
    idExterno: j['id_externo'] == null ? null : j['id_externo'] as String,
    coleccion: j['coleccion'] == null ? null : j['coleccion'] as String,
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    emisor: j['emisor'] == null ? null : j['emisor'] as String,
    rango: j['rango'] == null ? null : j['rango'] as String,
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    ecli: j['ecli'] == null ? null : j['ecli'] as String,
    eli: j['eli'] == null ? null : j['eli'] as String,
    estadoNormativo: j['estado_normativo'] == null ? null : j['estado_normativo'] as String,
    fechaPublicacion: j['fecha_publicacion'] == null ? null : j['fecha_publicacion'] as String,
    fechaResolucion: j['fecha_resolucion'] == null ? null : j['fecha_resolucion'] as String,
    urlCanonica: j['url_canonica'] == null ? null : j['url_canonica'] as String,
    atribucion: j['atribucion'] == null ? null : j['atribucion'] as String,
    versiones: j['versiones'] == null ? null : (j['versiones'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    relaciones: j['relaciones'] == null ? null : (j['relaciones'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'fuente_id': ?fuenteId,
    'id_externo': ?idExterno,
    'coleccion': ?coleccion,
    'titulo': ?titulo,
    'emisor': ?emisor,
    'rango': ?rango,
    'tipo': ?tipo,
    'ecli': ?ecli,
    'eli': ?eli,
    'estado_normativo': ?estadoNormativo,
    'fecha_publicacion': ?fechaPublicacion,
    'fecha_resolucion': ?fechaResolucion,
    'url_canonica': ?urlCanonica,
    'atribucion': ?atribucion,
    if (versiones != null) 'versiones': versiones!.map((e) => e).toList(),
    if (relaciones != null) 'relaciones': relaciones!.map((e) => e).toList(),
  };
  DocumentoJuridico copyWith({int? id, String? fuenteId, String? idExterno, String? coleccion, String? titulo, String? emisor, String? rango, String? tipo, String? ecli, String? eli, String? estadoNormativo, String? fechaPublicacion, String? fechaResolucion, String? urlCanonica, String? atribucion, List<Map<String, dynamic>>? versiones, List<Map<String, dynamic>>? relaciones, }) => DocumentoJuridico(id: id ?? this.id, fuenteId: fuenteId ?? this.fuenteId, idExterno: idExterno ?? this.idExterno, coleccion: coleccion ?? this.coleccion, titulo: titulo ?? this.titulo, emisor: emisor ?? this.emisor, rango: rango ?? this.rango, tipo: tipo ?? this.tipo, ecli: ecli ?? this.ecli, eli: eli ?? this.eli, estadoNormativo: estadoNormativo ?? this.estadoNormativo, fechaPublicacion: fechaPublicacion ?? this.fechaPublicacion, fechaResolucion: fechaResolucion ?? this.fechaResolucion, urlCanonica: urlCanonica ?? this.urlCanonica, atribucion: atribucion ?? this.atribucion, versiones: versiones ?? this.versiones, relaciones: relaciones ?? this.relaciones, );
  @override bool operator ==(Object other) => other is DocumentoJuridico && other.id == id && other.fuenteId == fuenteId && other.idExterno == idExterno && other.coleccion == coleccion && other.titulo == titulo && other.emisor == emisor && other.rango == rango && other.tipo == tipo && other.ecli == ecli && other.eli == eli && other.estadoNormativo == estadoNormativo && other.fechaPublicacion == fechaPublicacion && other.fechaResolucion == fechaResolucion && other.urlCanonica == urlCanonica && other.atribucion == atribucion && other.versiones == versiones && other.relaciones == relaciones;
  @override int get hashCode => Object.hashAll([id, fuenteId, idExterno, coleccion, titulo, emisor, rango, tipo, ecli, eli, estadoNormativo, fechaPublicacion, fechaResolucion, urlCanonica, atribucion, versiones, relaciones]);
}

class DocumentoVencimiento {
  final int id;
  final int? vencimientoId;
  final String? nombreArchivo;
  final String? tipoMime;
  final int? tamanoBytes;
  final String? rutaNextcloud;
  final String? creadoEn;
  final String? origen;
  const DocumentoVencimiento({required this.id, this.vencimientoId, this.nombreArchivo, this.tipoMime, this.tamanoBytes, this.rutaNextcloud, this.creadoEn, this.origen, });
  factory DocumentoVencimiento.fromJson(Map<String, dynamic> j) => DocumentoVencimiento(
    id: (j['id'] as num).toInt(),
    vencimientoId: j['vencimiento_id'] == null ? null : (j['vencimiento_id'] as num).toInt(),
    nombreArchivo: j['nombre_archivo'] == null ? null : j['nombre_archivo'] as String,
    tipoMime: j['tipo_mime'] == null ? null : j['tipo_mime'] as String,
    tamanoBytes: j['tamano_bytes'] == null ? null : (j['tamano_bytes'] as num).toInt(),
    rutaNextcloud: j['ruta_nextcloud'] == null ? null : j['ruta_nextcloud'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    origen: j['origen'] == null ? null : j['origen'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'vencimiento_id': ?vencimientoId,
    'nombre_archivo': ?nombreArchivo,
    'tipo_mime': ?tipoMime,
    'tamano_bytes': ?tamanoBytes,
    'ruta_nextcloud': ?rutaNextcloud,
    'creado_en': ?creadoEn,
    'origen': ?origen,
  };
  DocumentoVencimiento copyWith({int? id, int? vencimientoId, String? nombreArchivo, String? tipoMime, int? tamanoBytes, String? rutaNextcloud, String? creadoEn, String? origen, }) => DocumentoVencimiento(id: id ?? this.id, vencimientoId: vencimientoId ?? this.vencimientoId, nombreArchivo: nombreArchivo ?? this.nombreArchivo, tipoMime: tipoMime ?? this.tipoMime, tamanoBytes: tamanoBytes ?? this.tamanoBytes, rutaNextcloud: rutaNextcloud ?? this.rutaNextcloud, creadoEn: creadoEn ?? this.creadoEn, origen: origen ?? this.origen, );
  @override bool operator ==(Object other) => other is DocumentoVencimiento && other.id == id && other.vencimientoId == vencimientoId && other.nombreArchivo == nombreArchivo && other.tipoMime == tipoMime && other.tamanoBytes == tamanoBytes && other.rutaNextcloud == rutaNextcloud && other.creadoEn == creadoEn && other.origen == origen;
  @override int get hashCode => Object.hashAll([id, vencimientoId, nombreArchivo, tipoMime, tamanoBytes, rutaNextcloud, creadoEn, origen]);
}

class ElementoHoy {
  final String? titulo;
  final String? detalle;
  final String? fecha;
  final ElementoHoyUrgencia? urgencia;
  final DestinoHoy? destino;
  final List<String>? acciones;
  final String? url;
  final String? seccion;
  final String? clave;
  const ElementoHoy({this.titulo, this.detalle, this.fecha, this.urgencia, this.destino, this.acciones, this.url, this.seccion, this.clave, });
  factory ElementoHoy.fromJson(Map<String, dynamic> j) => ElementoHoy(
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    detalle: j['detalle'] == null ? null : j['detalle'] as String,
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
    urgencia: j['urgencia'] == null ? null : ElementoHoyUrgencia.desde(j['urgencia'] as String),
    destino: j['destino'] == null ? null : DestinoHoy.fromJson(j['destino'] as Map<String, dynamic>),
    acciones: j['acciones'] == null ? null : (j['acciones'] as List).map((e) => e as String).toList(),
    url: j['url'] == null ? null : j['url'] as String,
    seccion: j['seccion'] == null ? null : j['seccion'] as String,
    clave: j['clave'] == null ? null : j['clave'] as String,
  );
  Map<String, dynamic> toJson() => {
    'titulo': ?titulo,
    'detalle': ?detalle,
    'fecha': ?fecha,
    if (urgencia != null) 'urgencia': urgencia!.valor,
    if (destino != null) 'destino': destino!.toJson(),
    if (acciones != null) 'acciones': acciones!.map((e) => e).toList(),
    'url': ?url,
    'seccion': ?seccion,
    'clave': ?clave,
  };
  ElementoHoy copyWith({String? titulo, String? detalle, String? fecha, ElementoHoyUrgencia? urgencia, DestinoHoy? destino, List<String>? acciones, String? url, String? seccion, String? clave, }) => ElementoHoy(titulo: titulo ?? this.titulo, detalle: detalle ?? this.detalle, fecha: fecha ?? this.fecha, urgencia: urgencia ?? this.urgencia, destino: destino ?? this.destino, acciones: acciones ?? this.acciones, url: url ?? this.url, seccion: seccion ?? this.seccion, clave: clave ?? this.clave, );
  @override bool operator ==(Object other) => other is ElementoHoy && other.titulo == titulo && other.detalle == detalle && other.fecha == fecha && other.urgencia == urgencia && other.destino == destino && other.acciones == acciones && other.url == url && other.seccion == seccion && other.clave == clave;
  @override int get hashCode => Object.hashAll([titulo, detalle, fecha, urgencia, destino, acciones, url, seccion, clave]);
}

class EmbudoComercial {
  final Map<String, dynamic>? periodo;
  final List<Map<String, dynamic>>? etapas;
  final Map<String, dynamic>? abiertas;
  final Map<String, dynamic>? ganadas;
  final Map<String, dynamic>? perdidas;
  final double? tasaExito;
  final double? cicloMedioDias;
  final List<Map<String, dynamic>>? motivosPerdida;
  final List<Map<String, dynamic>>? porResponsable;
  final int? estancadas;
  const EmbudoComercial({this.periodo, this.etapas, this.abiertas, this.ganadas, this.perdidas, this.tasaExito, this.cicloMedioDias, this.motivosPerdida, this.porResponsable, this.estancadas, });
  factory EmbudoComercial.fromJson(Map<String, dynamic> j) => EmbudoComercial(
    periodo: j['periodo'] == null ? null : Map<String, dynamic>.from(j['periodo'] as Map),
    etapas: j['etapas'] == null ? null : (j['etapas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    abiertas: j['abiertas'] == null ? null : Map<String, dynamic>.from(j['abiertas'] as Map),
    ganadas: j['ganadas'] == null ? null : Map<String, dynamic>.from(j['ganadas'] as Map),
    perdidas: j['perdidas'] == null ? null : Map<String, dynamic>.from(j['perdidas'] as Map),
    tasaExito: j['tasa_exito'] == null ? null : (j['tasa_exito'] as num).toDouble(),
    cicloMedioDias: j['ciclo_medio_dias'] == null ? null : (j['ciclo_medio_dias'] as num).toDouble(),
    motivosPerdida: j['motivos_perdida'] == null ? null : (j['motivos_perdida'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    porResponsable: j['por_responsable'] == null ? null : (j['por_responsable'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    estancadas: j['estancadas'] == null ? null : (j['estancadas'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'periodo': ?periodo,
    if (etapas != null) 'etapas': etapas!.map((e) => e).toList(),
    'abiertas': ?abiertas,
    'ganadas': ?ganadas,
    'perdidas': ?perdidas,
    'tasa_exito': ?tasaExito,
    'ciclo_medio_dias': ?cicloMedioDias,
    if (motivosPerdida != null) 'motivos_perdida': motivosPerdida!.map((e) => e).toList(),
    if (porResponsable != null) 'por_responsable': porResponsable!.map((e) => e).toList(),
    'estancadas': ?estancadas,
  };
  EmbudoComercial copyWith({Map<String, dynamic>? periodo, List<Map<String, dynamic>>? etapas, Map<String, dynamic>? abiertas, Map<String, dynamic>? ganadas, Map<String, dynamic>? perdidas, double? tasaExito, double? cicloMedioDias, List<Map<String, dynamic>>? motivosPerdida, List<Map<String, dynamic>>? porResponsable, int? estancadas, }) => EmbudoComercial(periodo: periodo ?? this.periodo, etapas: etapas ?? this.etapas, abiertas: abiertas ?? this.abiertas, ganadas: ganadas ?? this.ganadas, perdidas: perdidas ?? this.perdidas, tasaExito: tasaExito ?? this.tasaExito, cicloMedioDias: cicloMedioDias ?? this.cicloMedioDias, motivosPerdida: motivosPerdida ?? this.motivosPerdida, porResponsable: porResponsable ?? this.porResponsable, estancadas: estancadas ?? this.estancadas, );
  @override bool operator ==(Object other) => other is EmbudoComercial && other.periodo == periodo && other.etapas == etapas && other.abiertas == abiertas && other.ganadas == ganadas && other.perdidas == perdidas && other.tasaExito == tasaExito && other.cicloMedioDias == cicloMedioDias && other.motivosPerdida == motivosPerdida && other.porResponsable == porResponsable && other.estancadas == estancadas;
  @override int get hashCode => Object.hashAll([periodo, etapas, abiertas, ganadas, perdidas, tasaExito, cicloMedioDias, motivosPerdida, porResponsable, estancadas]);
}

class EnvioCorreo {
  final int id;
  final int? usuarioId;
  final int? cuentaId;
  final String? destinatarios;
  final String? cc;
  final String? bcc;
  final String? asunto;
  final String? enRespuestaA;
  final String? enviarEn;
  final int? programado;
  final String? estado;
  final String? error;
  final String? creadoEn;
  final String? procesadoEn;
  final int? seguimientoDias;
  final int? identidadId;
  const EnvioCorreo({required this.id, this.usuarioId, this.cuentaId, this.destinatarios, this.cc, this.bcc, this.asunto, this.enRespuestaA, this.enviarEn, this.programado, this.estado, this.error, this.creadoEn, this.procesadoEn, this.seguimientoDias, this.identidadId, });
  factory EnvioCorreo.fromJson(Map<String, dynamic> j) => EnvioCorreo(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    cuentaId: j['cuenta_id'] == null ? null : (j['cuenta_id'] as num).toInt(),
    destinatarios: j['destinatarios'] == null ? null : j['destinatarios'] as String,
    cc: j['cc'] == null ? null : j['cc'] as String,
    bcc: j['bcc'] == null ? null : j['bcc'] as String,
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    enRespuestaA: j['en_respuesta_a'] == null ? null : j['en_respuesta_a'] as String,
    enviarEn: j['enviar_en'] == null ? null : j['enviar_en'] as String,
    programado: j['programado'] == null ? null : (j['programado'] as num).toInt(),
    estado: j['estado'] == null ? null : j['estado'] as String,
    error: j['error'] == null ? null : j['error'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    procesadoEn: j['procesado_en'] == null ? null : j['procesado_en'] as String,
    seguimientoDias: j['seguimiento_dias'] == null ? null : (j['seguimiento_dias'] as num).toInt(),
    identidadId: j['identidad_id'] == null ? null : (j['identidad_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'cuenta_id': ?cuentaId,
    'destinatarios': ?destinatarios,
    'cc': ?cc,
    'bcc': ?bcc,
    'asunto': ?asunto,
    'en_respuesta_a': ?enRespuestaA,
    'enviar_en': ?enviarEn,
    'programado': ?programado,
    'estado': ?estado,
    'error': ?error,
    'creado_en': ?creadoEn,
    'procesado_en': ?procesadoEn,
    'seguimiento_dias': ?seguimientoDias,
    'identidad_id': ?identidadId,
  };
  EnvioCorreo copyWith({int? id, int? usuarioId, int? cuentaId, String? destinatarios, String? cc, String? bcc, String? asunto, String? enRespuestaA, String? enviarEn, int? programado, String? estado, String? error, String? creadoEn, String? procesadoEn, int? seguimientoDias, int? identidadId, }) => EnvioCorreo(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, cuentaId: cuentaId ?? this.cuentaId, destinatarios: destinatarios ?? this.destinatarios, cc: cc ?? this.cc, bcc: bcc ?? this.bcc, asunto: asunto ?? this.asunto, enRespuestaA: enRespuestaA ?? this.enRespuestaA, enviarEn: enviarEn ?? this.enviarEn, programado: programado ?? this.programado, estado: estado ?? this.estado, error: error ?? this.error, creadoEn: creadoEn ?? this.creadoEn, procesadoEn: procesadoEn ?? this.procesadoEn, seguimientoDias: seguimientoDias ?? this.seguimientoDias, identidadId: identidadId ?? this.identidadId, );
  @override bool operator ==(Object other) => other is EnvioCorreo && other.id == id && other.usuarioId == usuarioId && other.cuentaId == cuentaId && other.destinatarios == destinatarios && other.cc == cc && other.bcc == bcc && other.asunto == asunto && other.enRespuestaA == enRespuestaA && other.enviarEn == enviarEn && other.programado == programado && other.estado == estado && other.error == error && other.creadoEn == creadoEn && other.procesadoEn == procesadoEn && other.seguimientoDias == seguimientoDias && other.identidadId == identidadId;
  @override int get hashCode => Object.hashAll([id, usuarioId, cuentaId, destinatarios, cc, bcc, asunto, enRespuestaA, enviarEn, programado, estado, error, creadoEn, procesadoEn, seguimientoDias, identidadId]);
}

class EnvioResultado {
  final bool? enviado;
  final String? messageId;
  final bool? programado;
  final int? envioId;
  final String? enviarEn;
  const EnvioResultado({this.enviado, this.messageId, this.programado, this.envioId, this.enviarEn, });
  factory EnvioResultado.fromJson(Map<String, dynamic> j) => EnvioResultado(
    enviado: j['enviado'] == null ? null : _aBool(j['enviado']),
    messageId: j['message_id'] == null ? null : j['message_id'] as String,
    programado: j['programado'] == null ? null : _aBool(j['programado']),
    envioId: j['envio_id'] == null ? null : (j['envio_id'] as num).toInt(),
    enviarEn: j['enviar_en'] == null ? null : j['enviar_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'enviado': ?enviado,
    'message_id': ?messageId,
    'programado': ?programado,
    'envio_id': ?envioId,
    'enviar_en': ?enviarEn,
  };
  EnvioResultado copyWith({bool? enviado, String? messageId, bool? programado, int? envioId, String? enviarEn, }) => EnvioResultado(enviado: enviado ?? this.enviado, messageId: messageId ?? this.messageId, programado: programado ?? this.programado, envioId: envioId ?? this.envioId, enviarEn: enviarEn ?? this.enviarEn, );
  @override bool operator ==(Object other) => other is EnvioResultado && other.enviado == enviado && other.messageId == messageId && other.programado == programado && other.envioId == envioId && other.enviarEn == enviarEn;
  @override int get hashCode => Object.hashAll([enviado, messageId, programado, envioId, enviarEn]);
}

class Error {
  final bool ok;
  final String error;
  final ErrorCodigo codigo;
  final String? campo;
  final String? requestId;
  const Error({required this.ok, required this.error, required this.codigo, this.campo, this.requestId, });
  factory Error.fromJson(Map<String, dynamic> j) => Error(
    ok: _aBool(j['ok']),
    error: j['error'] as String,
    codigo: ErrorCodigo.desde(j['codigo'] as String),
    campo: j['campo'] == null ? null : j['campo'] as String,
    requestId: j['request_id'] == null ? null : j['request_id'] as String,
  );
  Map<String, dynamic> toJson() => {
    'ok': ok,
    'error': error,
    'codigo': codigo.valor,
    'campo': ?campo,
    'request_id': ?requestId,
  };
  Error copyWith({bool? ok, String? error, ErrorCodigo? codigo, String? campo, String? requestId, }) => Error(ok: ok ?? this.ok, error: error ?? this.error, codigo: codigo ?? this.codigo, campo: campo ?? this.campo, requestId: requestId ?? this.requestId, );
  @override bool operator ==(Object other) => other is Error && other.ok == ok && other.error == error && other.codigo == codigo && other.campo == campo && other.requestId == requestId;
  @override int get hashCode => Object.hashAll([ok, error, codigo, campo, requestId]);
}

class EstadoServicio {
  final EstadoServicioEstado? estado;
  final String? versionApi;
  final EstadoServicioBaseDeDatos? baseDeDatos;
  const EstadoServicio({this.estado, this.versionApi, this.baseDeDatos, });
  factory EstadoServicio.fromJson(Map<String, dynamic> j) => EstadoServicio(
    estado: j['estado'] == null ? null : EstadoServicioEstado.desde(j['estado'] as String),
    versionApi: j['version_api'] == null ? null : j['version_api'] as String,
    baseDeDatos: j['base_de_datos'] == null ? null : EstadoServicioBaseDeDatos.desde(j['base_de_datos'] as String),
  );
  Map<String, dynamic> toJson() => {
    if (estado != null) 'estado': estado!.valor,
    'version_api': ?versionApi,
    if (baseDeDatos != null) 'base_de_datos': baseDeDatos!.valor,
  };
  EstadoServicio copyWith({EstadoServicioEstado? estado, String? versionApi, EstadoServicioBaseDeDatos? baseDeDatos, }) => EstadoServicio(estado: estado ?? this.estado, versionApi: versionApi ?? this.versionApi, baseDeDatos: baseDeDatos ?? this.baseDeDatos, );
  @override bool operator ==(Object other) => other is EstadoServicio && other.estado == estado && other.versionApi == versionApi && other.baseDeDatos == baseDeDatos;
  @override int get hashCode => Object.hashAll([estado, versionApi, baseDeDatos]);
}

class EtapaComercial {
  final String? clave;
  final String? nombre;
  final int? probabilidad;
  final EtapaComercialTipo? tipo;
  final int? orden;
  const EtapaComercial({this.clave, this.nombre, this.probabilidad, this.tipo, this.orden, });
  factory EtapaComercial.fromJson(Map<String, dynamic> j) => EtapaComercial(
    clave: j['clave'] == null ? null : j['clave'] as String,
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    probabilidad: j['probabilidad'] == null ? null : (j['probabilidad'] as num).toInt(),
    tipo: j['tipo'] == null ? null : EtapaComercialTipo.desde(j['tipo'] as String),
    orden: j['orden'] == null ? null : (j['orden'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'clave': ?clave,
    'nombre': ?nombre,
    'probabilidad': ?probabilidad,
    if (tipo != null) 'tipo': tipo!.valor,
    'orden': ?orden,
  };
  EtapaComercial copyWith({String? clave, String? nombre, int? probabilidad, EtapaComercialTipo? tipo, int? orden, }) => EtapaComercial(clave: clave ?? this.clave, nombre: nombre ?? this.nombre, probabilidad: probabilidad ?? this.probabilidad, tipo: tipo ?? this.tipo, orden: orden ?? this.orden, );
  @override bool operator ==(Object other) => other is EtapaComercial && other.clave == clave && other.nombre == nombre && other.probabilidad == probabilidad && other.tipo == tipo && other.orden == orden;
  @override int get hashCode => Object.hashAll([clave, nombre, probabilidad, tipo, orden]);
}

class EventoAuditoria {
  final int id;
  final int? usuarioId;
  final String? accion;
  final String? entidad;
  final String? entidadId;
  final dynamic? detalle;
  final String? correlacion;
  final String? creadoEn;
  final String? actor;
  const EventoAuditoria({required this.id, this.usuarioId, this.accion, this.entidad, this.entidadId, this.detalle, this.correlacion, this.creadoEn, this.actor, });
  factory EventoAuditoria.fromJson(Map<String, dynamic> j) => EventoAuditoria(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    accion: j['accion'] == null ? null : j['accion'] as String,
    entidad: j['entidad'] == null ? null : j['entidad'] as String,
    entidadId: j['entidad_id'] == null ? null : j['entidad_id'] as String,
    detalle: j['detalle'],
    correlacion: j['correlacion'] == null ? null : j['correlacion'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    actor: j['actor'] == null ? null : j['actor'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'accion': ?accion,
    'entidad': ?entidad,
    'entidad_id': ?entidadId,
    'detalle': ?detalle,
    'correlacion': ?correlacion,
    'creado_en': ?creadoEn,
    'actor': ?actor,
  };
  EventoAuditoria copyWith({int? id, int? usuarioId, String? accion, String? entidad, String? entidadId, dynamic detalle, String? correlacion, String? creadoEn, String? actor, }) => EventoAuditoria(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, accion: accion ?? this.accion, entidad: entidad ?? this.entidad, entidadId: entidadId ?? this.entidadId, detalle: detalle ?? this.detalle, correlacion: correlacion ?? this.correlacion, creadoEn: creadoEn ?? this.creadoEn, actor: actor ?? this.actor, );
  @override bool operator ==(Object other) => other is EventoAuditoria && other.id == id && other.usuarioId == usuarioId && other.accion == accion && other.entidad == entidad && other.entidadId == entidadId && other.detalle == detalle && other.correlacion == correlacion && other.creadoEn == creadoEn && other.actor == actor;
  @override int get hashCode => Object.hashAll([id, usuarioId, accion, entidad, entidadId, detalle, correlacion, creadoEn, actor]);
}

class ExpedienteControl {
  final int id;
  final String? tipo;
  final String? titulo;
  final String? descripcion;
  final String? estado;
  final int? responsableId;
  final String? abiertoEn;
  final String? cerradoEn;
  final String? cliente;
  final ExpedienteControlPrioridad? prioridad;
  final String? fechaObjetivo;
  final int? puntos;
  final int? puntosHechos;
  final int? obligatoriosPendientes;
  final String? vinculoTipo;
  final int? vinculoId;
  final int? revisorId;
  final int? oficinaId;
  const ExpedienteControl({required this.id, this.tipo, this.titulo, this.descripcion, this.estado, this.responsableId, this.abiertoEn, this.cerradoEn, this.cliente, this.prioridad, this.fechaObjetivo, this.puntos, this.puntosHechos, this.obligatoriosPendientes, this.vinculoTipo, this.vinculoId, this.revisorId, this.oficinaId, });
  factory ExpedienteControl.fromJson(Map<String, dynamic> j) => ExpedienteControl(
    id: (j['id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    descripcion: j['descripcion'] == null ? null : j['descripcion'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    responsableId: j['responsable_id'] == null ? null : (j['responsable_id'] as num).toInt(),
    abiertoEn: j['abierto_en'] == null ? null : j['abierto_en'] as String,
    cerradoEn: j['cerrado_en'] == null ? null : j['cerrado_en'] as String,
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    prioridad: j['prioridad'] == null ? null : ExpedienteControlPrioridad.desde(j['prioridad'] as String),
    fechaObjetivo: j['fecha_objetivo'] == null ? null : j['fecha_objetivo'] as String,
    puntos: j['puntos'] == null ? null : (j['puntos'] as num).toInt(),
    puntosHechos: j['puntos_hechos'] == null ? null : (j['puntos_hechos'] as num).toInt(),
    obligatoriosPendientes: j['obligatorios_pendientes'] == null ? null : (j['obligatorios_pendientes'] as num).toInt(),
    vinculoTipo: j['vinculo_tipo'] == null ? null : j['vinculo_tipo'] as String,
    vinculoId: j['vinculo_id'] == null ? null : (j['vinculo_id'] as num).toInt(),
    revisorId: j['revisor_id'] == null ? null : (j['revisor_id'] as num).toInt(),
    oficinaId: j['oficina_id'] == null ? null : (j['oficina_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tipo': ?tipo,
    'titulo': ?titulo,
    'descripcion': ?descripcion,
    'estado': ?estado,
    'responsable_id': ?responsableId,
    'abierto_en': ?abiertoEn,
    'cerrado_en': ?cerradoEn,
    'cliente': ?cliente,
    if (prioridad != null) 'prioridad': prioridad!.valor,
    'fecha_objetivo': ?fechaObjetivo,
    'puntos': ?puntos,
    'puntos_hechos': ?puntosHechos,
    'obligatorios_pendientes': ?obligatoriosPendientes,
    'vinculo_tipo': ?vinculoTipo,
    'vinculo_id': ?vinculoId,
    'revisor_id': ?revisorId,
    'oficina_id': ?oficinaId,
  };
  ExpedienteControl copyWith({int? id, String? tipo, String? titulo, String? descripcion, String? estado, int? responsableId, String? abiertoEn, String? cerradoEn, String? cliente, ExpedienteControlPrioridad? prioridad, String? fechaObjetivo, int? puntos, int? puntosHechos, int? obligatoriosPendientes, String? vinculoTipo, int? vinculoId, int? revisorId, int? oficinaId, }) => ExpedienteControl(id: id ?? this.id, tipo: tipo ?? this.tipo, titulo: titulo ?? this.titulo, descripcion: descripcion ?? this.descripcion, estado: estado ?? this.estado, responsableId: responsableId ?? this.responsableId, abiertoEn: abiertoEn ?? this.abiertoEn, cerradoEn: cerradoEn ?? this.cerradoEn, cliente: cliente ?? this.cliente, prioridad: prioridad ?? this.prioridad, fechaObjetivo: fechaObjetivo ?? this.fechaObjetivo, puntos: puntos ?? this.puntos, puntosHechos: puntosHechos ?? this.puntosHechos, obligatoriosPendientes: obligatoriosPendientes ?? this.obligatoriosPendientes, vinculoTipo: vinculoTipo ?? this.vinculoTipo, vinculoId: vinculoId ?? this.vinculoId, revisorId: revisorId ?? this.revisorId, oficinaId: oficinaId ?? this.oficinaId, );
  @override bool operator ==(Object other) => other is ExpedienteControl && other.id == id && other.tipo == tipo && other.titulo == titulo && other.descripcion == descripcion && other.estado == estado && other.responsableId == responsableId && other.abiertoEn == abiertoEn && other.cerradoEn == cerradoEn && other.cliente == cliente && other.prioridad == prioridad && other.fechaObjetivo == fechaObjetivo && other.puntos == puntos && other.puntosHechos == puntosHechos && other.obligatoriosPendientes == obligatoriosPendientes && other.vinculoTipo == vinculoTipo && other.vinculoId == vinculoId && other.revisorId == revisorId && other.oficinaId == oficinaId;
  @override int get hashCode => Object.hashAll([id, tipo, titulo, descripcion, estado, responsableId, abiertoEn, cerradoEn, cliente, prioridad, fechaObjetivo, puntos, puntosHechos, obligatoriosPendientes, vinculoTipo, vinculoId, revisorId, oficinaId]);
}

class ExportacionContable {
  final int? lote;
  final String? cliente;
  final int? facturas;
  final int? registros;
  final List<String>? avisos;
  const ExportacionContable({this.lote, this.cliente, this.facturas, this.registros, this.avisos, });
  factory ExportacionContable.fromJson(Map<String, dynamic> j) => ExportacionContable(
    lote: j['lote'] == null ? null : (j['lote'] as num).toInt(),
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    facturas: j['facturas'] == null ? null : (j['facturas'] as num).toInt(),
    registros: j['registros'] == null ? null : (j['registros'] as num).toInt(),
    avisos: j['avisos'] == null ? null : (j['avisos'] as List).map((e) => e as String).toList(),
  );
  Map<String, dynamic> toJson() => {
    'lote': ?lote,
    'cliente': ?cliente,
    'facturas': ?facturas,
    'registros': ?registros,
    if (avisos != null) 'avisos': avisos!.map((e) => e).toList(),
  };
  ExportacionContable copyWith({int? lote, String? cliente, int? facturas, int? registros, List<String>? avisos, }) => ExportacionContable(lote: lote ?? this.lote, cliente: cliente ?? this.cliente, facturas: facturas ?? this.facturas, registros: registros ?? this.registros, avisos: avisos ?? this.avisos, );
  @override bool operator ==(Object other) => other is ExportacionContable && other.lote == lote && other.cliente == cliente && other.facturas == facturas && other.registros == registros && other.avisos == avisos;
  @override int get hashCode => Object.hashAll([lote, cliente, facturas, registros, avisos]);
}

class FacturaContable {
  final int? id;
  final int? clienteFiscalId;
  final String? cliente;
  final FacturaContableTipo? tipo;
  final bool? abono;
  final String? fecha;
  final String? trimestre;
  final String? numero;
  final String? tercero;
  final String? nif;
  final double? total;
  final FacturaContableEstado? estado;
  final String? origen;
  final String? lectura;
  final bool? tieneArchivo;
  const FacturaContable({this.id, this.clienteFiscalId, this.cliente, this.tipo, this.abono, this.fecha, this.trimestre, this.numero, this.tercero, this.nif, this.total, this.estado, this.origen, this.lectura, this.tieneArchivo, });
  factory FacturaContable.fromJson(Map<String, dynamic> j) => FacturaContable(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    tipo: j['tipo'] == null ? null : FacturaContableTipo.desde(j['tipo'] as String),
    abono: j['abono'] == null ? null : _aBool(j['abono']),
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
    trimestre: j['trimestre'] == null ? null : j['trimestre'] as String,
    numero: j['numero'] == null ? null : j['numero'] as String,
    tercero: j['tercero'] == null ? null : j['tercero'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    total: j['total'] == null ? null : (j['total'] as num).toDouble(),
    estado: j['estado'] == null ? null : FacturaContableEstado.desde(j['estado'] as String),
    origen: j['origen'] == null ? null : j['origen'] as String,
    lectura: j['lectura'] == null ? null : j['lectura'] as String,
    tieneArchivo: j['tiene_archivo'] == null ? null : _aBool(j['tiene_archivo']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'cliente_fiscal_id': ?clienteFiscalId,
    'cliente': ?cliente,
    if (tipo != null) 'tipo': tipo!.valor,
    'abono': ?abono,
    'fecha': ?fecha,
    'trimestre': ?trimestre,
    'numero': ?numero,
    'tercero': ?tercero,
    'nif': ?nif,
    'total': ?total,
    if (estado != null) 'estado': estado!.valor,
    'origen': ?origen,
    'lectura': ?lectura,
    'tiene_archivo': ?tieneArchivo,
  };
  FacturaContable copyWith({int? id, int? clienteFiscalId, String? cliente, FacturaContableTipo? tipo, bool? abono, String? fecha, String? trimestre, String? numero, String? tercero, String? nif, double? total, FacturaContableEstado? estado, String? origen, String? lectura, bool? tieneArchivo, }) => FacturaContable(id: id ?? this.id, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, cliente: cliente ?? this.cliente, tipo: tipo ?? this.tipo, abono: abono ?? this.abono, fecha: fecha ?? this.fecha, trimestre: trimestre ?? this.trimestre, numero: numero ?? this.numero, tercero: tercero ?? this.tercero, nif: nif ?? this.nif, total: total ?? this.total, estado: estado ?? this.estado, origen: origen ?? this.origen, lectura: lectura ?? this.lectura, tieneArchivo: tieneArchivo ?? this.tieneArchivo, );
  @override bool operator ==(Object other) => other is FacturaContable && other.id == id && other.clienteFiscalId == clienteFiscalId && other.cliente == cliente && other.tipo == tipo && other.abono == abono && other.fecha == fecha && other.trimestre == trimestre && other.numero == numero && other.tercero == tercero && other.nif == nif && other.total == total && other.estado == estado && other.origen == origen && other.lectura == lectura && other.tieneArchivo == tieneArchivo;
  @override int get hashCode => Object.hashAll([id, clienteFiscalId, cliente, tipo, abono, fecha, trimestre, numero, tercero, nif, total, estado, origen, lectura, tieneArchivo]);
}

class FacturaContableDetalle {
  final int? id;
  final int? clienteFiscalId;
  final String? cliente;
  final String? tipo;
  final bool? abono;
  final String? fecha;
  final String? trimestre;
  final String? numero;
  final String? tercero;
  final String? nif;
  final double? total;
  final String? estado;
  final String? origen;
  final String? lectura;
  final bool? tieneArchivo;
  final String? fechaOperacion;
  final String? concepto;
  final String? referencia;
  final String? subcuentaTercero;
  final String? rectificaNumero;
  final String? rectificaFecha;
  final bool? criterioCaja;
  final double? suplidos;
  final String? notas;
  final String? lecturaError;
  final List<String>? problemas;
  final String? periodoCerrado;
  final List<Map<String, dynamic>>? lineas;
  final List<String>? avisosDeLaLectura;
  const FacturaContableDetalle({this.id, this.clienteFiscalId, this.cliente, this.tipo, this.abono, this.fecha, this.trimestre, this.numero, this.tercero, this.nif, this.total, this.estado, this.origen, this.lectura, this.tieneArchivo, this.fechaOperacion, this.concepto, this.referencia, this.subcuentaTercero, this.rectificaNumero, this.rectificaFecha, this.criterioCaja, this.suplidos, this.notas, this.lecturaError, this.problemas, this.periodoCerrado, this.lineas, this.avisosDeLaLectura, });
  factory FacturaContableDetalle.fromJson(Map<String, dynamic> j) => FacturaContableDetalle(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    abono: j['abono'] == null ? null : _aBool(j['abono']),
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
    trimestre: j['trimestre'] == null ? null : j['trimestre'] as String,
    numero: j['numero'] == null ? null : j['numero'] as String,
    tercero: j['tercero'] == null ? null : j['tercero'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    total: j['total'] == null ? null : (j['total'] as num).toDouble(),
    estado: j['estado'] == null ? null : j['estado'] as String,
    origen: j['origen'] == null ? null : j['origen'] as String,
    lectura: j['lectura'] == null ? null : j['lectura'] as String,
    tieneArchivo: j['tiene_archivo'] == null ? null : _aBool(j['tiene_archivo']),
    fechaOperacion: j['fecha_operacion'] == null ? null : j['fecha_operacion'] as String,
    concepto: j['concepto'] == null ? null : j['concepto'] as String,
    referencia: j['referencia'] == null ? null : j['referencia'] as String,
    subcuentaTercero: j['subcuenta_tercero'] == null ? null : j['subcuenta_tercero'] as String,
    rectificaNumero: j['rectifica_numero'] == null ? null : j['rectifica_numero'] as String,
    rectificaFecha: j['rectifica_fecha'] == null ? null : j['rectifica_fecha'] as String,
    criterioCaja: j['criterio_caja'] == null ? null : _aBool(j['criterio_caja']),
    suplidos: j['suplidos'] == null ? null : (j['suplidos'] as num).toDouble(),
    notas: j['notas'] == null ? null : j['notas'] as String,
    lecturaError: j['lectura_error'] == null ? null : j['lectura_error'] as String,
    problemas: j['problemas'] == null ? null : (j['problemas'] as List).map((e) => e as String).toList(),
    periodoCerrado: j['periodo_cerrado'] == null ? null : j['periodo_cerrado'] as String,
    lineas: j['lineas'] == null ? null : (j['lineas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    avisosDeLaLectura: j['avisos_de_la_lectura'] == null ? null : (j['avisos_de_la_lectura'] as List).map((e) => e as String).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'cliente_fiscal_id': ?clienteFiscalId,
    'cliente': ?cliente,
    'tipo': ?tipo,
    'abono': ?abono,
    'fecha': ?fecha,
    'trimestre': ?trimestre,
    'numero': ?numero,
    'tercero': ?tercero,
    'nif': ?nif,
    'total': ?total,
    'estado': ?estado,
    'origen': ?origen,
    'lectura': ?lectura,
    'tiene_archivo': ?tieneArchivo,
    'fecha_operacion': ?fechaOperacion,
    'concepto': ?concepto,
    'referencia': ?referencia,
    'subcuenta_tercero': ?subcuentaTercero,
    'rectifica_numero': ?rectificaNumero,
    'rectifica_fecha': ?rectificaFecha,
    'criterio_caja': ?criterioCaja,
    'suplidos': ?suplidos,
    'notas': ?notas,
    'lectura_error': ?lecturaError,
    if (problemas != null) 'problemas': problemas!.map((e) => e).toList(),
    'periodo_cerrado': ?periodoCerrado,
    if (lineas != null) 'lineas': lineas!.map((e) => e).toList(),
    if (avisosDeLaLectura != null) 'avisos_de_la_lectura': avisosDeLaLectura!.map((e) => e).toList(),
  };
  FacturaContableDetalle copyWith({int? id, int? clienteFiscalId, String? cliente, String? tipo, bool? abono, String? fecha, String? trimestre, String? numero, String? tercero, String? nif, double? total, String? estado, String? origen, String? lectura, bool? tieneArchivo, String? fechaOperacion, String? concepto, String? referencia, String? subcuentaTercero, String? rectificaNumero, String? rectificaFecha, bool? criterioCaja, double? suplidos, String? notas, String? lecturaError, List<String>? problemas, String? periodoCerrado, List<Map<String, dynamic>>? lineas, List<String>? avisosDeLaLectura, }) => FacturaContableDetalle(id: id ?? this.id, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, cliente: cliente ?? this.cliente, tipo: tipo ?? this.tipo, abono: abono ?? this.abono, fecha: fecha ?? this.fecha, trimestre: trimestre ?? this.trimestre, numero: numero ?? this.numero, tercero: tercero ?? this.tercero, nif: nif ?? this.nif, total: total ?? this.total, estado: estado ?? this.estado, origen: origen ?? this.origen, lectura: lectura ?? this.lectura, tieneArchivo: tieneArchivo ?? this.tieneArchivo, fechaOperacion: fechaOperacion ?? this.fechaOperacion, concepto: concepto ?? this.concepto, referencia: referencia ?? this.referencia, subcuentaTercero: subcuentaTercero ?? this.subcuentaTercero, rectificaNumero: rectificaNumero ?? this.rectificaNumero, rectificaFecha: rectificaFecha ?? this.rectificaFecha, criterioCaja: criterioCaja ?? this.criterioCaja, suplidos: suplidos ?? this.suplidos, notas: notas ?? this.notas, lecturaError: lecturaError ?? this.lecturaError, problemas: problemas ?? this.problemas, periodoCerrado: periodoCerrado ?? this.periodoCerrado, lineas: lineas ?? this.lineas, avisosDeLaLectura: avisosDeLaLectura ?? this.avisosDeLaLectura, );
  @override bool operator ==(Object other) => other is FacturaContableDetalle && other.id == id && other.clienteFiscalId == clienteFiscalId && other.cliente == cliente && other.tipo == tipo && other.abono == abono && other.fecha == fecha && other.trimestre == trimestre && other.numero == numero && other.tercero == tercero && other.nif == nif && other.total == total && other.estado == estado && other.origen == origen && other.lectura == lectura && other.tieneArchivo == tieneArchivo && other.fechaOperacion == fechaOperacion && other.concepto == concepto && other.referencia == referencia && other.subcuentaTercero == subcuentaTercero && other.rectificaNumero == rectificaNumero && other.rectificaFecha == rectificaFecha && other.criterioCaja == criterioCaja && other.suplidos == suplidos && other.notas == notas && other.lecturaError == lecturaError && other.problemas == problemas && other.periodoCerrado == periodoCerrado && other.lineas == lineas && other.avisosDeLaLectura == avisosDeLaLectura;
  @override int get hashCode => Object.hashAll([id, clienteFiscalId, cliente, tipo, abono, fecha, trimestre, numero, tercero, nif, total, estado, origen, lectura, tieneArchivo, fechaOperacion, concepto, referencia, subcuentaTercero, rectificaNumero, rectificaFecha, criterioCaja, suplidos, notas, lecturaError, problemas, periodoCerrado, lineas, avisosDeLaLectura]);
}

class Fichaje {
  final int id;
  final int? usuarioId;
  final int? tenantId;
  final String? tipo;
  final String? marcaTiempo;
  final String? origen;
  final String? nota;
  final int? corrigeA;
  final int? creadoPor;
  final String? creadoEn;
  final String? clienteUuid;
  final String? hash;
  final double? latitud;
  final double? longitud;
  const Fichaje({required this.id, this.usuarioId, this.tenantId, this.tipo, this.marcaTiempo, this.origen, this.nota, this.corrigeA, this.creadoPor, this.creadoEn, this.clienteUuid, this.hash, this.latitud, this.longitud, });
  factory Fichaje.fromJson(Map<String, dynamic> j) => Fichaje(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    marcaTiempo: j['marca_tiempo'] == null ? null : j['marca_tiempo'] as String,
    origen: j['origen'] == null ? null : j['origen'] as String,
    nota: j['nota'] == null ? null : j['nota'] as String,
    corrigeA: j['corrige_a'] == null ? null : (j['corrige_a'] as num).toInt(),
    creadoPor: j['creado_por'] == null ? null : (j['creado_por'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    clienteUuid: j['cliente_uuid'] == null ? null : j['cliente_uuid'] as String,
    hash: j['hash'] == null ? null : j['hash'] as String,
    latitud: j['latitud'] == null ? null : (j['latitud'] as num).toDouble(),
    longitud: j['longitud'] == null ? null : (j['longitud'] as num).toDouble(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'tenant_id': ?tenantId,
    'tipo': ?tipo,
    'marca_tiempo': ?marcaTiempo,
    'origen': ?origen,
    'nota': ?nota,
    'corrige_a': ?corrigeA,
    'creado_por': ?creadoPor,
    'creado_en': ?creadoEn,
    'cliente_uuid': ?clienteUuid,
    'hash': ?hash,
    'latitud': ?latitud,
    'longitud': ?longitud,
  };
  Fichaje copyWith({int? id, int? usuarioId, int? tenantId, String? tipo, String? marcaTiempo, String? origen, String? nota, int? corrigeA, int? creadoPor, String? creadoEn, String? clienteUuid, String? hash, double? latitud, double? longitud, }) => Fichaje(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, tenantId: tenantId ?? this.tenantId, tipo: tipo ?? this.tipo, marcaTiempo: marcaTiempo ?? this.marcaTiempo, origen: origen ?? this.origen, nota: nota ?? this.nota, corrigeA: corrigeA ?? this.corrigeA, creadoPor: creadoPor ?? this.creadoPor, creadoEn: creadoEn ?? this.creadoEn, clienteUuid: clienteUuid ?? this.clienteUuid, hash: hash ?? this.hash, latitud: latitud ?? this.latitud, longitud: longitud ?? this.longitud, );
  @override bool operator ==(Object other) => other is Fichaje && other.id == id && other.usuarioId == usuarioId && other.tenantId == tenantId && other.tipo == tipo && other.marcaTiempo == marcaTiempo && other.origen == origen && other.nota == nota && other.corrigeA == corrigeA && other.creadoPor == creadoPor && other.creadoEn == creadoEn && other.clienteUuid == clienteUuid && other.hash == hash && other.latitud == latitud && other.longitud == longitud;
  @override int get hashCode => Object.hashAll([id, usuarioId, tenantId, tipo, marcaTiempo, origen, nota, corrigeA, creadoPor, creadoEn, clienteUuid, hash, latitud, longitud]);
}

class FichajeDatos {
  final int? usuarioId;
  final String? nombreCompleto;
  final String? dniNie;
  final String? numeroAfiliacionSs;
  final String? categoriaProfesional;
  final String? tipoContrato;
  final String? fechaAlta;
  final double? jornadaSemanalHoras;
  final String? convenioColectivo;
  final String? actualizadoEn;
  const FichajeDatos({this.usuarioId, this.nombreCompleto, this.dniNie, this.numeroAfiliacionSs, this.categoriaProfesional, this.tipoContrato, this.fechaAlta, this.jornadaSemanalHoras, this.convenioColectivo, this.actualizadoEn, });
  factory FichajeDatos.fromJson(Map<String, dynamic> j) => FichajeDatos(
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombreCompleto: j['nombre_completo'] == null ? null : j['nombre_completo'] as String,
    dniNie: j['dni_nie'] == null ? null : j['dni_nie'] as String,
    numeroAfiliacionSs: j['numero_afiliacion_ss'] == null ? null : j['numero_afiliacion_ss'] as String,
    categoriaProfesional: j['categoria_profesional'] == null ? null : j['categoria_profesional'] as String,
    tipoContrato: j['tipo_contrato'] == null ? null : j['tipo_contrato'] as String,
    fechaAlta: j['fecha_alta'] == null ? null : j['fecha_alta'] as String,
    jornadaSemanalHoras: j['jornada_semanal_horas'] == null ? null : (j['jornada_semanal_horas'] as num).toDouble(),
    convenioColectivo: j['convenio_colectivo'] == null ? null : j['convenio_colectivo'] as String,
    actualizadoEn: j['actualizado_en'] == null ? null : j['actualizado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'usuario_id': ?usuarioId,
    'nombre_completo': ?nombreCompleto,
    'dni_nie': ?dniNie,
    'numero_afiliacion_ss': ?numeroAfiliacionSs,
    'categoria_profesional': ?categoriaProfesional,
    'tipo_contrato': ?tipoContrato,
    'fecha_alta': ?fechaAlta,
    'jornada_semanal_horas': ?jornadaSemanalHoras,
    'convenio_colectivo': ?convenioColectivo,
    'actualizado_en': ?actualizadoEn,
  };
  FichajeDatos copyWith({int? usuarioId, String? nombreCompleto, String? dniNie, String? numeroAfiliacionSs, String? categoriaProfesional, String? tipoContrato, String? fechaAlta, double? jornadaSemanalHoras, String? convenioColectivo, String? actualizadoEn, }) => FichajeDatos(usuarioId: usuarioId ?? this.usuarioId, nombreCompleto: nombreCompleto ?? this.nombreCompleto, dniNie: dniNie ?? this.dniNie, numeroAfiliacionSs: numeroAfiliacionSs ?? this.numeroAfiliacionSs, categoriaProfesional: categoriaProfesional ?? this.categoriaProfesional, tipoContrato: tipoContrato ?? this.tipoContrato, fechaAlta: fechaAlta ?? this.fechaAlta, jornadaSemanalHoras: jornadaSemanalHoras ?? this.jornadaSemanalHoras, convenioColectivo: convenioColectivo ?? this.convenioColectivo, actualizadoEn: actualizadoEn ?? this.actualizadoEn, );
  @override bool operator ==(Object other) => other is FichajeDatos && other.usuarioId == usuarioId && other.nombreCompleto == nombreCompleto && other.dniNie == dniNie && other.numeroAfiliacionSs == numeroAfiliacionSs && other.categoriaProfesional == categoriaProfesional && other.tipoContrato == tipoContrato && other.fechaAlta == fechaAlta && other.jornadaSemanalHoras == jornadaSemanalHoras && other.convenioColectivo == convenioColectivo && other.actualizadoEn == actualizadoEn;
  @override int get hashCode => Object.hashAll([usuarioId, nombreCompleto, dniNie, numeroAfiliacionSs, categoriaProfesional, tipoContrato, fechaAlta, jornadaSemanalHoras, convenioColectivo, actualizadoEn]);
}

class FiscalApunte {
  final int? id;
  final FiscalApunteLibro? libro;
  final String? tipoFactura;
  final String? clave;
  final String? numero;
  final String? fechaExpedicion;
  final String? contraparte;
  final String? nif;
  final double? base_;
  final double? tipoIva;
  final double? cuota;
  final double? cuotaDeducible;
  final int? version;
  final bool? anulado;
  const FiscalApunte({this.id, this.libro, this.tipoFactura, this.clave, this.numero, this.fechaExpedicion, this.contraparte, this.nif, this.base_, this.tipoIva, this.cuota, this.cuotaDeducible, this.version, this.anulado, });
  factory FiscalApunte.fromJson(Map<String, dynamic> j) => FiscalApunte(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    libro: j['libro'] == null ? null : FiscalApunteLibro.desde(j['libro'] as String),
    tipoFactura: j['tipo_factura'] == null ? null : j['tipo_factura'] as String,
    clave: j['clave'] == null ? null : j['clave'] as String,
    numero: j['numero'] == null ? null : j['numero'] as String,
    fechaExpedicion: j['fecha_expedicion'] == null ? null : j['fecha_expedicion'] as String,
    contraparte: j['contraparte'] == null ? null : j['contraparte'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    base_: j['base'] == null ? null : (j['base'] as num).toDouble(),
    tipoIva: j['tipo_iva'] == null ? null : (j['tipo_iva'] as num).toDouble(),
    cuota: j['cuota'] == null ? null : (j['cuota'] as num).toDouble(),
    cuotaDeducible: j['cuota_deducible'] == null ? null : (j['cuota_deducible'] as num).toDouble(),
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    anulado: j['anulado'] == null ? null : _aBool(j['anulado']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    if (libro != null) 'libro': libro!.valor,
    'tipo_factura': ?tipoFactura,
    'clave': ?clave,
    'numero': ?numero,
    'fecha_expedicion': ?fechaExpedicion,
    'contraparte': ?contraparte,
    'nif': ?nif,
    'base': ?base_,
    'tipo_iva': ?tipoIva,
    'cuota': ?cuota,
    'cuota_deducible': ?cuotaDeducible,
    'version': ?version,
    'anulado': ?anulado,
  };
  FiscalApunte copyWith({int? id, FiscalApunteLibro? libro, String? tipoFactura, String? clave, String? numero, String? fechaExpedicion, String? contraparte, String? nif, double? base_, double? tipoIva, double? cuota, double? cuotaDeducible, int? version, bool? anulado, }) => FiscalApunte(id: id ?? this.id, libro: libro ?? this.libro, tipoFactura: tipoFactura ?? this.tipoFactura, clave: clave ?? this.clave, numero: numero ?? this.numero, fechaExpedicion: fechaExpedicion ?? this.fechaExpedicion, contraparte: contraparte ?? this.contraparte, nif: nif ?? this.nif, base_: base_ ?? this.base_, tipoIva: tipoIva ?? this.tipoIva, cuota: cuota ?? this.cuota, cuotaDeducible: cuotaDeducible ?? this.cuotaDeducible, version: version ?? this.version, anulado: anulado ?? this.anulado, );
  @override bool operator ==(Object other) => other is FiscalApunte && other.id == id && other.libro == libro && other.tipoFactura == tipoFactura && other.clave == clave && other.numero == numero && other.fechaExpedicion == fechaExpedicion && other.contraparte == contraparte && other.nif == nif && other.base_ == base_ && other.tipoIva == tipoIva && other.cuota == cuota && other.cuotaDeducible == cuotaDeducible && other.version == version && other.anulado == anulado;
  @override int get hashCode => Object.hashAll([id, libro, tipoFactura, clave, numero, fechaExpedicion, contraparte, nif, base_, tipoIva, cuota, cuotaDeducible, version, anulado]);
}

class FiscalComprobacion {
  final int? apuntes;
  final bool? ok;
  final List<Map<String, dynamic>>? problemas;
  const FiscalComprobacion({this.apuntes, this.ok, this.problemas, });
  factory FiscalComprobacion.fromJson(Map<String, dynamic> j) => FiscalComprobacion(
    apuntes: j['apuntes'] == null ? null : (j['apuntes'] as num).toInt(),
    ok: j['ok'] == null ? null : _aBool(j['ok']),
    problemas: j['problemas'] == null ? null : (j['problemas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'apuntes': ?apuntes,
    'ok': ?ok,
    if (problemas != null) 'problemas': problemas!.map((e) => e).toList(),
  };
  FiscalComprobacion copyWith({int? apuntes, bool? ok, List<Map<String, dynamic>>? problemas, }) => FiscalComprobacion(apuntes: apuntes ?? this.apuntes, ok: ok ?? this.ok, problemas: problemas ?? this.problemas, );
  @override bool operator ==(Object other) => other is FiscalComprobacion && other.apuntes == apuntes && other.ok == ok && other.problemas == problemas;
  @override int get hashCode => Object.hashAll([apuntes, ok, problemas]);
}

class FiscalDeclaracion {
  final int? id;
  final int? clienteFiscalId;
  final String? modelo;
  final int? ejercicio;
  final String? periodo;
  final String? estado;
  final double? resultado;
  final int? instantaneaId;
  final List<String>? bloqueos;
  final Map<String, dynamic>? casillas;
  final Map<String, dynamic>? origen;
  final List<String>? ficheros;
  const FiscalDeclaracion({this.id, this.clienteFiscalId, this.modelo, this.ejercicio, this.periodo, this.estado, this.resultado, this.instantaneaId, this.bloqueos, this.casillas, this.origen, this.ficheros, });
  factory FiscalDeclaracion.fromJson(Map<String, dynamic> j) => FiscalDeclaracion(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    modelo: j['modelo'] == null ? null : j['modelo'] as String,
    ejercicio: j['ejercicio'] == null ? null : (j['ejercicio'] as num).toInt(),
    periodo: j['periodo'] == null ? null : j['periodo'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    resultado: j['resultado'] == null ? null : (j['resultado'] as num).toDouble(),
    instantaneaId: j['instantanea_id'] == null ? null : (j['instantanea_id'] as num).toInt(),
    bloqueos: j['bloqueos'] == null ? null : (j['bloqueos'] as List).map((e) => e as String).toList(),
    casillas: j['casillas'] == null ? null : Map<String, dynamic>.from(j['casillas'] as Map),
    origen: j['origen'] == null ? null : Map<String, dynamic>.from(j['origen'] as Map),
    ficheros: j['ficheros'] == null ? null : (j['ficheros'] as List).map((e) => e as String).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'cliente_fiscal_id': ?clienteFiscalId,
    'modelo': ?modelo,
    'ejercicio': ?ejercicio,
    'periodo': ?periodo,
    'estado': ?estado,
    'resultado': ?resultado,
    'instantanea_id': ?instantaneaId,
    if (bloqueos != null) 'bloqueos': bloqueos!.map((e) => e).toList(),
    'casillas': ?casillas,
    'origen': ?origen,
    if (ficheros != null) 'ficheros': ficheros!.map((e) => e).toList(),
  };
  FiscalDeclaracion copyWith({int? id, int? clienteFiscalId, String? modelo, int? ejercicio, String? periodo, String? estado, double? resultado, int? instantaneaId, List<String>? bloqueos, Map<String, dynamic>? casillas, Map<String, dynamic>? origen, List<String>? ficheros, }) => FiscalDeclaracion(id: id ?? this.id, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, modelo: modelo ?? this.modelo, ejercicio: ejercicio ?? this.ejercicio, periodo: periodo ?? this.periodo, estado: estado ?? this.estado, resultado: resultado ?? this.resultado, instantaneaId: instantaneaId ?? this.instantaneaId, bloqueos: bloqueos ?? this.bloqueos, casillas: casillas ?? this.casillas, origen: origen ?? this.origen, ficheros: ficheros ?? this.ficheros, );
  @override bool operator ==(Object other) => other is FiscalDeclaracion && other.id == id && other.clienteFiscalId == clienteFiscalId && other.modelo == modelo && other.ejercicio == ejercicio && other.periodo == periodo && other.estado == estado && other.resultado == resultado && other.instantaneaId == instantaneaId && other.bloqueos == bloqueos && other.casillas == casillas && other.origen == origen && other.ficheros == ficheros;
  @override int get hashCode => Object.hashAll([id, clienteFiscalId, modelo, ejercicio, periodo, estado, resultado, instantaneaId, bloqueos, casillas, origen, ficheros]);
}

class FiscalDeclaracionResumen {
  final int? id;
  final String? modelo;
  final int? ejercicio;
  final String? periodo;
  final FiscalDeclaracionResumenEstado? estado;
  final String? tipoDeclaracion;
  final double? resultado;
  final String? presentadaEn;
  const FiscalDeclaracionResumen({this.id, this.modelo, this.ejercicio, this.periodo, this.estado, this.tipoDeclaracion, this.resultado, this.presentadaEn, });
  factory FiscalDeclaracionResumen.fromJson(Map<String, dynamic> j) => FiscalDeclaracionResumen(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    modelo: j['modelo'] == null ? null : j['modelo'] as String,
    ejercicio: j['ejercicio'] == null ? null : (j['ejercicio'] as num).toInt(),
    periodo: j['periodo'] == null ? null : j['periodo'] as String,
    estado: j['estado'] == null ? null : FiscalDeclaracionResumenEstado.desde(j['estado'] as String),
    tipoDeclaracion: j['tipo_declaracion'] == null ? null : j['tipo_declaracion'] as String,
    resultado: j['resultado'] == null ? null : (j['resultado'] as num).toDouble(),
    presentadaEn: j['presentada_en'] == null ? null : j['presentada_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'modelo': ?modelo,
    'ejercicio': ?ejercicio,
    'periodo': ?periodo,
    if (estado != null) 'estado': estado!.valor,
    'tipo_declaracion': ?tipoDeclaracion,
    'resultado': ?resultado,
    'presentada_en': ?presentadaEn,
  };
  FiscalDeclaracionResumen copyWith({int? id, String? modelo, int? ejercicio, String? periodo, FiscalDeclaracionResumenEstado? estado, String? tipoDeclaracion, double? resultado, String? presentadaEn, }) => FiscalDeclaracionResumen(id: id ?? this.id, modelo: modelo ?? this.modelo, ejercicio: ejercicio ?? this.ejercicio, periodo: periodo ?? this.periodo, estado: estado ?? this.estado, tipoDeclaracion: tipoDeclaracion ?? this.tipoDeclaracion, resultado: resultado ?? this.resultado, presentadaEn: presentadaEn ?? this.presentadaEn, );
  @override bool operator ==(Object other) => other is FiscalDeclaracionResumen && other.id == id && other.modelo == modelo && other.ejercicio == ejercicio && other.periodo == periodo && other.estado == estado && other.tipoDeclaracion == tipoDeclaracion && other.resultado == resultado && other.presentadaEn == presentadaEn;
  @override int get hashCode => Object.hashAll([id, modelo, ejercicio, periodo, estado, tipoDeclaracion, resultado, presentadaEn]);
}

class FiscalPerfil {
  final Map<String, dynamic>? vigente;
  final List<Map<String, dynamic>>? historial;
  const FiscalPerfil({this.vigente, this.historial, });
  factory FiscalPerfil.fromJson(Map<String, dynamic> j) => FiscalPerfil(
    vigente: j['vigente'] == null ? null : Map<String, dynamic>.from(j['vigente'] as Map),
    historial: j['historial'] == null ? null : (j['historial'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'vigente': ?vigente,
    if (historial != null) 'historial': historial!.map((e) => e).toList(),
  };
  FiscalPerfil copyWith({Map<String, dynamic>? vigente, List<Map<String, dynamic>>? historial, }) => FiscalPerfil(vigente: vigente ?? this.vigente, historial: historial ?? this.historial, );
  @override bool operator ==(Object other) => other is FiscalPerfil && other.vigente == vigente && other.historial == historial;
  @override int get hashCode => Object.hashAll([vigente, historial]);
}

class FiscalPropuestaApunte {
  final int? facturaId;
  final String? libro;
  final String? tipoFactura;
  final String? numero;
  final double? base_;
  final double? tipoIva;
  final double? cuota;
  final bool? aprobado;
  const FiscalPropuestaApunte({this.facturaId, this.libro, this.tipoFactura, this.numero, this.base_, this.tipoIva, this.cuota, this.aprobado, });
  factory FiscalPropuestaApunte.fromJson(Map<String, dynamic> j) => FiscalPropuestaApunte(
    facturaId: j['factura_id'] == null ? null : (j['factura_id'] as num).toInt(),
    libro: j['libro'] == null ? null : j['libro'] as String,
    tipoFactura: j['tipo_factura'] == null ? null : j['tipo_factura'] as String,
    numero: j['numero'] == null ? null : j['numero'] as String,
    base_: j['base'] == null ? null : (j['base'] as num).toDouble(),
    tipoIva: j['tipo_iva'] == null ? null : (j['tipo_iva'] as num).toDouble(),
    cuota: j['cuota'] == null ? null : (j['cuota'] as num).toDouble(),
    aprobado: j['aprobado'] == null ? null : _aBool(j['aprobado']),
  );
  Map<String, dynamic> toJson() => {
    'factura_id': ?facturaId,
    'libro': ?libro,
    'tipo_factura': ?tipoFactura,
    'numero': ?numero,
    'base': ?base_,
    'tipo_iva': ?tipoIva,
    'cuota': ?cuota,
    'aprobado': ?aprobado,
  };
  FiscalPropuestaApunte copyWith({int? facturaId, String? libro, String? tipoFactura, String? numero, double? base_, double? tipoIva, double? cuota, bool? aprobado, }) => FiscalPropuestaApunte(facturaId: facturaId ?? this.facturaId, libro: libro ?? this.libro, tipoFactura: tipoFactura ?? this.tipoFactura, numero: numero ?? this.numero, base_: base_ ?? this.base_, tipoIva: tipoIva ?? this.tipoIva, cuota: cuota ?? this.cuota, aprobado: aprobado ?? this.aprobado, );
  @override bool operator ==(Object other) => other is FiscalPropuestaApunte && other.facturaId == facturaId && other.libro == libro && other.tipoFactura == tipoFactura && other.numero == numero && other.base_ == base_ && other.tipoIva == tipoIva && other.cuota == cuota && other.aprobado == aprobado;
  @override int get hashCode => Object.hashAll([facturaId, libro, tipoFactura, numero, base_, tipoIva, cuota, aprobado]);
}

class FiscalSimulacion {
  final bool? simulacion;
  final int? ejercicio;
  final String? periodo;
  final List<String>? bloqueos;
  final String? tipoDeclaracion;
  final double? resultado;
  final Map<String, dynamic>? casillas;
  final String? aviso;
  const FiscalSimulacion({this.simulacion, this.ejercicio, this.periodo, this.bloqueos, this.tipoDeclaracion, this.resultado, this.casillas, this.aviso, });
  factory FiscalSimulacion.fromJson(Map<String, dynamic> j) => FiscalSimulacion(
    simulacion: j['simulacion'] == null ? null : _aBool(j['simulacion']),
    ejercicio: j['ejercicio'] == null ? null : (j['ejercicio'] as num).toInt(),
    periodo: j['periodo'] == null ? null : j['periodo'] as String,
    bloqueos: j['bloqueos'] == null ? null : (j['bloqueos'] as List).map((e) => e as String).toList(),
    tipoDeclaracion: j['tipo_declaracion'] == null ? null : j['tipo_declaracion'] as String,
    resultado: j['resultado'] == null ? null : (j['resultado'] as num).toDouble(),
    casillas: j['casillas'] == null ? null : Map<String, dynamic>.from(j['casillas'] as Map),
    aviso: j['aviso'] == null ? null : j['aviso'] as String,
  );
  Map<String, dynamic> toJson() => {
    'simulacion': ?simulacion,
    'ejercicio': ?ejercicio,
    'periodo': ?periodo,
    if (bloqueos != null) 'bloqueos': bloqueos!.map((e) => e).toList(),
    'tipo_declaracion': ?tipoDeclaracion,
    'resultado': ?resultado,
    'casillas': ?casillas,
    'aviso': ?aviso,
  };
  FiscalSimulacion copyWith({bool? simulacion, int? ejercicio, String? periodo, List<String>? bloqueos, String? tipoDeclaracion, double? resultado, Map<String, dynamic>? casillas, String? aviso, }) => FiscalSimulacion(simulacion: simulacion ?? this.simulacion, ejercicio: ejercicio ?? this.ejercicio, periodo: periodo ?? this.periodo, bloqueos: bloqueos ?? this.bloqueos, tipoDeclaracion: tipoDeclaracion ?? this.tipoDeclaracion, resultado: resultado ?? this.resultado, casillas: casillas ?? this.casillas, aviso: aviso ?? this.aviso, );
  @override bool operator ==(Object other) => other is FiscalSimulacion && other.simulacion == simulacion && other.ejercicio == ejercicio && other.periodo == periodo && other.bloqueos == bloqueos && other.tipoDeclaracion == tipoDeclaracion && other.resultado == resultado && other.casillas == casillas && other.aviso == aviso;
  @override int get hashCode => Object.hashAll([simulacion, ejercicio, periodo, bloqueos, tipoDeclaracion, resultado, casillas, aviso]);
}

class FiscalTitular {
  final int? clienteFiscalId;
  final String? nombre;
  final String? nif;
  final Map<String, dynamic>? perfil;
  final int? apuntesDelAnio;
  final Map<String, dynamic>? ultimaDeclaracion;
  const FiscalTitular({this.clienteFiscalId, this.nombre, this.nif, this.perfil, this.apuntesDelAnio, this.ultimaDeclaracion, });
  factory FiscalTitular.fromJson(Map<String, dynamic> j) => FiscalTitular(
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    perfil: j['perfil'] == null ? null : Map<String, dynamic>.from(j['perfil'] as Map),
    apuntesDelAnio: j['apuntes_del_anio'] == null ? null : (j['apuntes_del_anio'] as num).toInt(),
    ultimaDeclaracion: j['ultima_declaracion'] == null ? null : Map<String, dynamic>.from(j['ultima_declaracion'] as Map),
  );
  Map<String, dynamic> toJson() => {
    'cliente_fiscal_id': ?clienteFiscalId,
    'nombre': ?nombre,
    'nif': ?nif,
    'perfil': ?perfil,
    'apuntes_del_anio': ?apuntesDelAnio,
    'ultima_declaracion': ?ultimaDeclaracion,
  };
  FiscalTitular copyWith({int? clienteFiscalId, String? nombre, String? nif, Map<String, dynamic>? perfil, int? apuntesDelAnio, Map<String, dynamic>? ultimaDeclaracion, }) => FiscalTitular(clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, nombre: nombre ?? this.nombre, nif: nif ?? this.nif, perfil: perfil ?? this.perfil, apuntesDelAnio: apuntesDelAnio ?? this.apuntesDelAnio, ultimaDeclaracion: ultimaDeclaracion ?? this.ultimaDeclaracion, );
  @override bool operator ==(Object other) => other is FiscalTitular && other.clienteFiscalId == clienteFiscalId && other.nombre == nombre && other.nif == nif && other.perfil == perfil && other.apuntesDelAnio == apuntesDelAnio && other.ultimaDeclaracion == ultimaDeclaracion;
  @override int get hashCode => Object.hashAll([clienteFiscalId, nombre, nif, perfil, apuntesDelAnio, ultimaDeclaracion]);
}

class FlujoObligacion {
  final FlujoObligacionFase? fase;
  final int? version;
  final Map<String, dynamic>? indicadores;
  final List<String>? destinos;
  final List<Map<String, dynamic>>? evidencias;
  final ConfigFlujo? config;
  final String? motivo;
  final String? bloqueoMotivo;
  const FlujoObligacion({this.fase, this.version, this.indicadores, this.destinos, this.evidencias, this.config, this.motivo, this.bloqueoMotivo, });
  factory FlujoObligacion.fromJson(Map<String, dynamic> j) => FlujoObligacion(
    fase: j['fase'] == null ? null : FlujoObligacionFase.desde(j['fase'] as String),
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    indicadores: j['indicadores'] == null ? null : Map<String, dynamic>.from(j['indicadores'] as Map),
    destinos: j['destinos'] == null ? null : (j['destinos'] as List).map((e) => e as String).toList(),
    evidencias: j['evidencias'] == null ? null : (j['evidencias'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    config: j['config'] == null ? null : ConfigFlujo.fromJson(j['config'] as Map<String, dynamic>),
    motivo: j['motivo'] == null ? null : j['motivo'] as String,
    bloqueoMotivo: j['bloqueo_motivo'] == null ? null : j['bloqueo_motivo'] as String,
  );
  Map<String, dynamic> toJson() => {
    if (fase != null) 'fase': fase!.valor,
    'version': ?version,
    'indicadores': ?indicadores,
    if (destinos != null) 'destinos': destinos!.map((e) => e).toList(),
    if (evidencias != null) 'evidencias': evidencias!.map((e) => e).toList(),
    if (config != null) 'config': config!.toJson(),
    'motivo': ?motivo,
    'bloqueo_motivo': ?bloqueoMotivo,
  };
  FlujoObligacion copyWith({FlujoObligacionFase? fase, int? version, Map<String, dynamic>? indicadores, List<String>? destinos, List<Map<String, dynamic>>? evidencias, ConfigFlujo? config, String? motivo, String? bloqueoMotivo, }) => FlujoObligacion(fase: fase ?? this.fase, version: version ?? this.version, indicadores: indicadores ?? this.indicadores, destinos: destinos ?? this.destinos, evidencias: evidencias ?? this.evidencias, config: config ?? this.config, motivo: motivo ?? this.motivo, bloqueoMotivo: bloqueoMotivo ?? this.bloqueoMotivo, );
  @override bool operator ==(Object other) => other is FlujoObligacion && other.fase == fase && other.version == version && other.indicadores == indicadores && other.destinos == destinos && other.evidencias == evidencias && other.config == config && other.motivo == motivo && other.bloqueoMotivo == bloqueoMotivo;
  @override int get hashCode => Object.hashAll([fase, version, indicadores, destinos, evidencias, config, motivo, bloqueoMotivo]);
}

class FuenteJuridica {
  final String? id;
  final String? nombre;
  final String? estado;
  final bool? habilitada;
  final Map<String, dynamic>? cobertura;
  final Map<String, dynamic>? politica;
  final String? verificacion;
  final List<Map<String, dynamic>>? ejecuciones;
  final List<Map<String, dynamic>>? problemas;
  const FuenteJuridica({this.id, this.nombre, this.estado, this.habilitada, this.cobertura, this.politica, this.verificacion, this.ejecuciones, this.problemas, });
  factory FuenteJuridica.fromJson(Map<String, dynamic> j) => FuenteJuridica(
    id: j['id'] == null ? null : j['id'] as String,
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    habilitada: j['habilitada'] == null ? null : _aBool(j['habilitada']),
    cobertura: j['cobertura'] == null ? null : Map<String, dynamic>.from(j['cobertura'] as Map),
    politica: j['politica'] == null ? null : Map<String, dynamic>.from(j['politica'] as Map),
    verificacion: j['verificacion'] == null ? null : j['verificacion'] as String,
    ejecuciones: j['ejecuciones'] == null ? null : (j['ejecuciones'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    problemas: j['problemas'] == null ? null : (j['problemas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
    'estado': ?estado,
    'habilitada': ?habilitada,
    'cobertura': ?cobertura,
    'politica': ?politica,
    'verificacion': ?verificacion,
    if (ejecuciones != null) 'ejecuciones': ejecuciones!.map((e) => e).toList(),
    if (problemas != null) 'problemas': problemas!.map((e) => e).toList(),
  };
  FuenteJuridica copyWith({String? id, String? nombre, String? estado, bool? habilitada, Map<String, dynamic>? cobertura, Map<String, dynamic>? politica, String? verificacion, List<Map<String, dynamic>>? ejecuciones, List<Map<String, dynamic>>? problemas, }) => FuenteJuridica(id: id ?? this.id, nombre: nombre ?? this.nombre, estado: estado ?? this.estado, habilitada: habilitada ?? this.habilitada, cobertura: cobertura ?? this.cobertura, politica: politica ?? this.politica, verificacion: verificacion ?? this.verificacion, ejecuciones: ejecuciones ?? this.ejecuciones, problemas: problemas ?? this.problemas, );
  @override bool operator ==(Object other) => other is FuenteJuridica && other.id == id && other.nombre == nombre && other.estado == estado && other.habilitada == habilitada && other.cobertura == cobertura && other.politica == politica && other.verificacion == verificacion && other.ejecuciones == ejecuciones && other.problemas == problemas;
  @override int get hashCode => Object.hashAll([id, nombre, estado, habilitada, cobertura, politica, verificacion, ejecuciones, problemas]);
}

class Herramienta {
  final String? id;
  final String? nombre;
  final String? url;
  final bool? activa;
  const Herramienta({this.id, this.nombre, this.url, this.activa, });
  factory Herramienta.fromJson(Map<String, dynamic> j) => Herramienta(
    id: j['id'] == null ? null : j['id'] as String,
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    url: j['url'] == null ? null : j['url'] as String,
    activa: j['activa'] == null ? null : _aBool(j['activa']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
    'url': ?url,
    'activa': ?activa,
  };
  Herramienta copyWith({String? id, String? nombre, String? url, bool? activa, }) => Herramienta(id: id ?? this.id, nombre: nombre ?? this.nombre, url: url ?? this.url, activa: activa ?? this.activa, );
  @override bool operator ==(Object other) => other is Herramienta && other.id == id && other.nombre == nombre && other.url == url && other.activa == activa;
  @override int get hashCode => Object.hashAll([id, nombre, url, activa]);
}

class HiloMensajes {
  final String? expediente;
  final bool? admiteRespuesta;
  final int? sinLeer;
  final List<Map<String, dynamic>>? mensajes;
  const HiloMensajes({this.expediente, this.admiteRespuesta, this.sinLeer, this.mensajes, });
  factory HiloMensajes.fromJson(Map<String, dynamic> j) => HiloMensajes(
    expediente: j['expediente'] == null ? null : j['expediente'] as String,
    admiteRespuesta: j['admite_respuesta'] == null ? null : _aBool(j['admite_respuesta']),
    sinLeer: j['sin_leer'] == null ? null : (j['sin_leer'] as num).toInt(),
    mensajes: j['mensajes'] == null ? null : (j['mensajes'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'expediente': ?expediente,
    'admite_respuesta': ?admiteRespuesta,
    'sin_leer': ?sinLeer,
    if (mensajes != null) 'mensajes': mensajes!.map((e) => e).toList(),
  };
  HiloMensajes copyWith({String? expediente, bool? admiteRespuesta, int? sinLeer, List<Map<String, dynamic>>? mensajes, }) => HiloMensajes(expediente: expediente ?? this.expediente, admiteRespuesta: admiteRespuesta ?? this.admiteRespuesta, sinLeer: sinLeer ?? this.sinLeer, mensajes: mensajes ?? this.mensajes, );
  @override bool operator ==(Object other) => other is HiloMensajes && other.expediente == expediente && other.admiteRespuesta == admiteRespuesta && other.sinLeer == sinLeer && other.mensajes == mensajes;
  @override int get hashCode => Object.hashAll([expediente, admiteRespuesta, sinLeer, mensajes]);
}

class Historial {
  final HistorialOrigen? origen;
  final int? id;
  final String? texto;
  final String? fecha;
  const Historial({this.origen, this.id, this.texto, this.fecha, });
  factory Historial.fromJson(Map<String, dynamic> j) => Historial(
    origen: j['origen'] == null ? null : HistorialOrigen.desde(j['origen'] as String),
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    texto: j['texto'] == null ? null : j['texto'] as String,
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
  );
  Map<String, dynamic> toJson() => {
    if (origen != null) 'origen': origen!.valor,
    'id': ?id,
    'texto': ?texto,
    'fecha': ?fecha,
  };
  Historial copyWith({HistorialOrigen? origen, int? id, String? texto, String? fecha, }) => Historial(origen: origen ?? this.origen, id: id ?? this.id, texto: texto ?? this.texto, fecha: fecha ?? this.fecha, );
  @override bool operator ==(Object other) => other is Historial && other.origen == origen && other.id == id && other.texto == texto && other.fecha == fecha;
  @override int get hashCode => Object.hashAll([origen, id, texto, fecha]);
}

class Identificador {
  final int? id;
  const Identificador({this.id, });
  factory Identificador.fromJson(Map<String, dynamic> j) => Identificador(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
  };
  Identificador copyWith({int? id, }) => Identificador(id: id ?? this.id, );
  @override bool operator ==(Object other) => other is Identificador && other.id == id;
  @override int get hashCode => Object.hashAll([id]);
}

class InfoAppMovil {
  final String? versionMinima;
  final String? versionRecomendada;
  final String? urlTienda;
  const InfoAppMovil({this.versionMinima, this.versionRecomendada, this.urlTienda, });
  factory InfoAppMovil.fromJson(Map<String, dynamic> j) => InfoAppMovil(
    versionMinima: j['version_minima'] == null ? null : j['version_minima'] as String,
    versionRecomendada: j['version_recomendada'] == null ? null : j['version_recomendada'] as String,
    urlTienda: j['url_tienda'] == null ? null : j['url_tienda'] as String,
  );
  Map<String, dynamic> toJson() => {
    'version_minima': ?versionMinima,
    'version_recomendada': ?versionRecomendada,
    'url_tienda': ?urlTienda,
  };
  InfoAppMovil copyWith({String? versionMinima, String? versionRecomendada, String? urlTienda, }) => InfoAppMovil(versionMinima: versionMinima ?? this.versionMinima, versionRecomendada: versionRecomendada ?? this.versionRecomendada, urlTienda: urlTienda ?? this.urlTienda, );
  @override bool operator ==(Object other) => other is InfoAppMovil && other.versionMinima == versionMinima && other.versionRecomendada == versionRecomendada && other.urlTienda == urlTienda;
  @override int get hashCode => Object.hashAll([versionMinima, versionRecomendada, urlTienda]);
}

class InformeJuridico {
  final int? id;
  final int? ejecucionId;
  final int? clienteId;
  final int? expedienteId;
  final String? titulo;
  final InformeJuridicoEstado? estado;
  final int? creadoPor;
  final int? revisadoPor;
  final String? revisadoEn;
  final String? creadoEn;
  final String? avisoFuente;
  const InformeJuridico({this.id, this.ejecucionId, this.clienteId, this.expedienteId, this.titulo, this.estado, this.creadoPor, this.revisadoPor, this.revisadoEn, this.creadoEn, this.avisoFuente, });
  factory InformeJuridico.fromJson(Map<String, dynamic> j) => InformeJuridico(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    ejecucionId: j['ejecucion_id'] == null ? null : (j['ejecucion_id'] as num).toInt(),
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    expedienteId: j['expediente_id'] == null ? null : (j['expediente_id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    estado: j['estado'] == null ? null : InformeJuridicoEstado.desde(j['estado'] as String),
    creadoPor: j['creado_por'] == null ? null : (j['creado_por'] as num).toInt(),
    revisadoPor: j['revisado_por'] == null ? null : (j['revisado_por'] as num).toInt(),
    revisadoEn: j['revisado_en'] == null ? null : j['revisado_en'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    avisoFuente: j['aviso_fuente'] == null ? null : j['aviso_fuente'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'ejecucion_id': ?ejecucionId,
    'cliente_id': ?clienteId,
    'expediente_id': ?expedienteId,
    'titulo': ?titulo,
    if (estado != null) 'estado': estado!.valor,
    'creado_por': ?creadoPor,
    'revisado_por': ?revisadoPor,
    'revisado_en': ?revisadoEn,
    'creado_en': ?creadoEn,
    'aviso_fuente': ?avisoFuente,
  };
  InformeJuridico copyWith({int? id, int? ejecucionId, int? clienteId, int? expedienteId, String? titulo, InformeJuridicoEstado? estado, int? creadoPor, int? revisadoPor, String? revisadoEn, String? creadoEn, String? avisoFuente, }) => InformeJuridico(id: id ?? this.id, ejecucionId: ejecucionId ?? this.ejecucionId, clienteId: clienteId ?? this.clienteId, expedienteId: expedienteId ?? this.expedienteId, titulo: titulo ?? this.titulo, estado: estado ?? this.estado, creadoPor: creadoPor ?? this.creadoPor, revisadoPor: revisadoPor ?? this.revisadoPor, revisadoEn: revisadoEn ?? this.revisadoEn, creadoEn: creadoEn ?? this.creadoEn, avisoFuente: avisoFuente ?? this.avisoFuente, );
  @override bool operator ==(Object other) => other is InformeJuridico && other.id == id && other.ejecucionId == ejecucionId && other.clienteId == clienteId && other.expedienteId == expedienteId && other.titulo == titulo && other.estado == estado && other.creadoPor == creadoPor && other.revisadoPor == revisadoPor && other.revisadoEn == revisadoEn && other.creadoEn == creadoEn && other.avisoFuente == avisoFuente;
  @override int get hashCode => Object.hashAll([id, ejecucionId, clienteId, expedienteId, titulo, estado, creadoPor, revisadoPor, revisadoEn, creadoEn, avisoFuente]);
}

class InformeJuridicoDetalle {
  final int? id;
  final int? ejecucionId;
  final int? clienteId;
  final int? expedienteId;
  final String? titulo;
  final InformeJuridicoDetalleEstado? estado;
  final int? creadoPor;
  final int? revisadoPor;
  final String? revisadoEn;
  final String? creadoEn;
  final String? avisoFuente;
  const InformeJuridicoDetalle({this.id, this.ejecucionId, this.clienteId, this.expedienteId, this.titulo, this.estado, this.creadoPor, this.revisadoPor, this.revisadoEn, this.creadoEn, this.avisoFuente, });
  factory InformeJuridicoDetalle.fromJson(Map<String, dynamic> j) => InformeJuridicoDetalle(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    ejecucionId: j['ejecucion_id'] == null ? null : (j['ejecucion_id'] as num).toInt(),
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    expedienteId: j['expediente_id'] == null ? null : (j['expediente_id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    estado: j['estado'] == null ? null : InformeJuridicoDetalleEstado.desde(j['estado'] as String),
    creadoPor: j['creado_por'] == null ? null : (j['creado_por'] as num).toInt(),
    revisadoPor: j['revisado_por'] == null ? null : (j['revisado_por'] as num).toInt(),
    revisadoEn: j['revisado_en'] == null ? null : j['revisado_en'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    avisoFuente: j['aviso_fuente'] == null ? null : j['aviso_fuente'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'ejecucion_id': ?ejecucionId,
    'cliente_id': ?clienteId,
    'expediente_id': ?expedienteId,
    'titulo': ?titulo,
    if (estado != null) 'estado': estado!.valor,
    'creado_por': ?creadoPor,
    'revisado_por': ?revisadoPor,
    'revisado_en': ?revisadoEn,
    'creado_en': ?creadoEn,
    'aviso_fuente': ?avisoFuente,
  };
  InformeJuridicoDetalle copyWith({int? id, int? ejecucionId, int? clienteId, int? expedienteId, String? titulo, InformeJuridicoDetalleEstado? estado, int? creadoPor, int? revisadoPor, String? revisadoEn, String? creadoEn, String? avisoFuente, }) => InformeJuridicoDetalle(id: id ?? this.id, ejecucionId: ejecucionId ?? this.ejecucionId, clienteId: clienteId ?? this.clienteId, expedienteId: expedienteId ?? this.expedienteId, titulo: titulo ?? this.titulo, estado: estado ?? this.estado, creadoPor: creadoPor ?? this.creadoPor, revisadoPor: revisadoPor ?? this.revisadoPor, revisadoEn: revisadoEn ?? this.revisadoEn, creadoEn: creadoEn ?? this.creadoEn, avisoFuente: avisoFuente ?? this.avisoFuente, );
  @override bool operator ==(Object other) => other is InformeJuridicoDetalle && other.id == id && other.ejecucionId == ejecucionId && other.clienteId == clienteId && other.expedienteId == expedienteId && other.titulo == titulo && other.estado == estado && other.creadoPor == creadoPor && other.revisadoPor == revisadoPor && other.revisadoEn == revisadoEn && other.creadoEn == creadoEn && other.avisoFuente == avisoFuente;
  @override int get hashCode => Object.hashAll([id, ejecucionId, clienteId, expedienteId, titulo, estado, creadoPor, revisadoPor, revisadoEn, creadoEn, avisoFuente]);
}

class InformeTareas {
  final Map<String, dynamic>? ventana;
  final String? hoy;
  final String? alcance;
  final int? creadasEnVentana;
  final Map<String, dynamic>? ahora;
  final Map<String, dynamic>? enVentana;
  final List<Map<String, dynamic>>? porResponsable;
  final List<Map<String, dynamic>>? porCliente;
  final List<Map<String, dynamic>>? bloqueadas;
  final Map<String, dynamic>? proximas;
  const InformeTareas({this.ventana, this.hoy, this.alcance, this.creadasEnVentana, this.ahora, this.enVentana, this.porResponsable, this.porCliente, this.bloqueadas, this.proximas, });
  factory InformeTareas.fromJson(Map<String, dynamic> j) => InformeTareas(
    ventana: j['ventana'] == null ? null : Map<String, dynamic>.from(j['ventana'] as Map),
    hoy: j['hoy'] == null ? null : j['hoy'] as String,
    alcance: j['alcance'] == null ? null : j['alcance'] as String,
    creadasEnVentana: j['creadas_en_ventana'] == null ? null : (j['creadas_en_ventana'] as num).toInt(),
    ahora: j['ahora'] == null ? null : Map<String, dynamic>.from(j['ahora'] as Map),
    enVentana: j['en_ventana'] == null ? null : Map<String, dynamic>.from(j['en_ventana'] as Map),
    porResponsable: j['por_responsable'] == null ? null : (j['por_responsable'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    porCliente: j['por_cliente'] == null ? null : (j['por_cliente'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    bloqueadas: j['bloqueadas'] == null ? null : (j['bloqueadas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    proximas: j['proximas'] == null ? null : Map<String, dynamic>.from(j['proximas'] as Map),
  );
  Map<String, dynamic> toJson() => {
    'ventana': ?ventana,
    'hoy': ?hoy,
    'alcance': ?alcance,
    'creadas_en_ventana': ?creadasEnVentana,
    'ahora': ?ahora,
    'en_ventana': ?enVentana,
    if (porResponsable != null) 'por_responsable': porResponsable!.map((e) => e).toList(),
    if (porCliente != null) 'por_cliente': porCliente!.map((e) => e).toList(),
    if (bloqueadas != null) 'bloqueadas': bloqueadas!.map((e) => e).toList(),
    'proximas': ?proximas,
  };
  InformeTareas copyWith({Map<String, dynamic>? ventana, String? hoy, String? alcance, int? creadasEnVentana, Map<String, dynamic>? ahora, Map<String, dynamic>? enVentana, List<Map<String, dynamic>>? porResponsable, List<Map<String, dynamic>>? porCliente, List<Map<String, dynamic>>? bloqueadas, Map<String, dynamic>? proximas, }) => InformeTareas(ventana: ventana ?? this.ventana, hoy: hoy ?? this.hoy, alcance: alcance ?? this.alcance, creadasEnVentana: creadasEnVentana ?? this.creadasEnVentana, ahora: ahora ?? this.ahora, enVentana: enVentana ?? this.enVentana, porResponsable: porResponsable ?? this.porResponsable, porCliente: porCliente ?? this.porCliente, bloqueadas: bloqueadas ?? this.bloqueadas, proximas: proximas ?? this.proximas, );
  @override bool operator ==(Object other) => other is InformeTareas && other.ventana == ventana && other.hoy == hoy && other.alcance == alcance && other.creadasEnVentana == creadasEnVentana && other.ahora == ahora && other.enVentana == enVentana && other.porResponsable == porResponsable && other.porCliente == porCliente && other.bloqueadas == bloqueadas && other.proximas == proximas;
  @override int get hashCode => Object.hashAll([ventana, hoy, alcance, creadasEnVentana, ahora, enVentana, porResponsable, porCliente, bloqueadas, proximas]);
}

class InmuebleResumen {
  final int? id;
  final int? expedienteId;
  final String? direccion;
  final String? municipio;
  final String? referencia;
  final String? tipo;
  final String? estado;
  final double? superficieM2;
  final int? habitaciones;
  final String? propietarioNombre;
  final int? visitasRealizadas;
  final String? precio;
  const InmuebleResumen({this.id, this.expedienteId, this.direccion, this.municipio, this.referencia, this.tipo, this.estado, this.superficieM2, this.habitaciones, this.propietarioNombre, this.visitasRealizadas, this.precio, });
  factory InmuebleResumen.fromJson(Map<String, dynamic> j) => InmuebleResumen(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    expedienteId: j['expediente_id'] == null ? null : (j['expediente_id'] as num).toInt(),
    direccion: j['direccion'] == null ? null : j['direccion'] as String,
    municipio: j['municipio'] == null ? null : j['municipio'] as String,
    referencia: j['referencia'] == null ? null : j['referencia'] as String,
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    superficieM2: j['superficie_m2'] == null ? null : (j['superficie_m2'] as num).toDouble(),
    habitaciones: j['habitaciones'] == null ? null : (j['habitaciones'] as num).toInt(),
    propietarioNombre: j['propietario_nombre'] == null ? null : j['propietario_nombre'] as String,
    visitasRealizadas: j['visitas_realizadas'] == null ? null : (j['visitas_realizadas'] as num).toInt(),
    precio: j['precio'] == null ? null : j['precio'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'expediente_id': ?expedienteId,
    'direccion': ?direccion,
    'municipio': ?municipio,
    'referencia': ?referencia,
    'tipo': ?tipo,
    'estado': ?estado,
    'superficie_m2': ?superficieM2,
    'habitaciones': ?habitaciones,
    'propietario_nombre': ?propietarioNombre,
    'visitas_realizadas': ?visitasRealizadas,
    'precio': ?precio,
  };
  InmuebleResumen copyWith({int? id, int? expedienteId, String? direccion, String? municipio, String? referencia, String? tipo, String? estado, double? superficieM2, int? habitaciones, String? propietarioNombre, int? visitasRealizadas, String? precio, }) => InmuebleResumen(id: id ?? this.id, expedienteId: expedienteId ?? this.expedienteId, direccion: direccion ?? this.direccion, municipio: municipio ?? this.municipio, referencia: referencia ?? this.referencia, tipo: tipo ?? this.tipo, estado: estado ?? this.estado, superficieM2: superficieM2 ?? this.superficieM2, habitaciones: habitaciones ?? this.habitaciones, propietarioNombre: propietarioNombre ?? this.propietarioNombre, visitasRealizadas: visitasRealizadas ?? this.visitasRealizadas, precio: precio ?? this.precio, );
  @override bool operator ==(Object other) => other is InmuebleResumen && other.id == id && other.expedienteId == expedienteId && other.direccion == direccion && other.municipio == municipio && other.referencia == referencia && other.tipo == tipo && other.estado == estado && other.superficieM2 == superficieM2 && other.habitaciones == habitaciones && other.propietarioNombre == propietarioNombre && other.visitasRealizadas == visitasRealizadas && other.precio == precio;
  @override int get hashCode => Object.hashAll([id, expedienteId, direccion, municipio, referencia, tipo, estado, superficieM2, habitaciones, propietarioNombre, visitasRealizadas, precio]);
}

class Integridad {
  final bool? integra;
  final int? total;
  final int? filaRota;
  const Integridad({this.integra, this.total, this.filaRota, });
  factory Integridad.fromJson(Map<String, dynamic> j) => Integridad(
    integra: j['integra'] == null ? null : _aBool(j['integra']),
    total: j['total'] == null ? null : (j['total'] as num).toInt(),
    filaRota: j['fila_rota'] == null ? null : (j['fila_rota'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'integra': ?integra,
    'total': ?total,
    'fila_rota': ?filaRota,
  };
  Integridad copyWith({bool? integra, int? total, int? filaRota, }) => Integridad(integra: integra ?? this.integra, total: total ?? this.total, filaRota: filaRota ?? this.filaRota, );
  @override bool operator ==(Object other) => other is Integridad && other.integra == integra && other.total == total && other.filaRota == filaRota;
  @override int get hashCode => Object.hashAll([integra, total, filaRota]);
}

class Membresia {
  final int id;
  final int? usuarioId;
  final String? rol;
  final String? alcanceTipo;
  final int? alcanceId;
  final String? vigenteDesde;
  final String? vigenteHasta;
  final int? creadoPor;
  final String? creadoEn;
  final String? revocadaEn;
  final String? persona;
  final String? oficina;
  final String? cliente;
  const Membresia({required this.id, this.usuarioId, this.rol, this.alcanceTipo, this.alcanceId, this.vigenteDesde, this.vigenteHasta, this.creadoPor, this.creadoEn, this.revocadaEn, this.persona, this.oficina, this.cliente, });
  factory Membresia.fromJson(Map<String, dynamic> j) => Membresia(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    rol: j['rol'] == null ? null : j['rol'] as String,
    alcanceTipo: j['alcance_tipo'] == null ? null : j['alcance_tipo'] as String,
    alcanceId: j['alcance_id'] == null ? null : (j['alcance_id'] as num).toInt(),
    vigenteDesde: j['vigente_desde'] == null ? null : j['vigente_desde'] as String,
    vigenteHasta: j['vigente_hasta'] == null ? null : j['vigente_hasta'] as String,
    creadoPor: j['creado_por'] == null ? null : (j['creado_por'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    revocadaEn: j['revocada_en'] == null ? null : j['revocada_en'] as String,
    persona: j['persona'] == null ? null : j['persona'] as String,
    oficina: j['oficina'] == null ? null : j['oficina'] as String,
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'rol': ?rol,
    'alcance_tipo': ?alcanceTipo,
    'alcance_id': ?alcanceId,
    'vigente_desde': ?vigenteDesde,
    'vigente_hasta': ?vigenteHasta,
    'creado_por': ?creadoPor,
    'creado_en': ?creadoEn,
    'revocada_en': ?revocadaEn,
    'persona': ?persona,
    'oficina': ?oficina,
    'cliente': ?cliente,
  };
  Membresia copyWith({int? id, int? usuarioId, String? rol, String? alcanceTipo, int? alcanceId, String? vigenteDesde, String? vigenteHasta, int? creadoPor, String? creadoEn, String? revocadaEn, String? persona, String? oficina, String? cliente, }) => Membresia(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, rol: rol ?? this.rol, alcanceTipo: alcanceTipo ?? this.alcanceTipo, alcanceId: alcanceId ?? this.alcanceId, vigenteDesde: vigenteDesde ?? this.vigenteDesde, vigenteHasta: vigenteHasta ?? this.vigenteHasta, creadoPor: creadoPor ?? this.creadoPor, creadoEn: creadoEn ?? this.creadoEn, revocadaEn: revocadaEn ?? this.revocadaEn, persona: persona ?? this.persona, oficina: oficina ?? this.oficina, cliente: cliente ?? this.cliente, );
  @override bool operator ==(Object other) => other is Membresia && other.id == id && other.usuarioId == usuarioId && other.rol == rol && other.alcanceTipo == alcanceTipo && other.alcanceId == alcanceId && other.vigenteDesde == vigenteDesde && other.vigenteHasta == vigenteHasta && other.creadoPor == creadoPor && other.creadoEn == creadoEn && other.revocadaEn == revocadaEn && other.persona == persona && other.oficina == oficina && other.cliente == cliente;
  @override int get hashCode => Object.hashAll([id, usuarioId, rol, alcanceTipo, alcanceId, vigenteDesde, vigenteHasta, creadoPor, creadoEn, revocadaEn, persona, oficina, cliente]);
}

class MensajeCorreo {
  final int id;
  final int? cuentaId;
  final String? carpeta;
  final String? uid;
  final String? asunto;
  final String? remitente;
  final String? destinatarios;
  final String? cc;
  final String? fecha;
  final String? cuerpoTexto;
  final String? messageId;
  final int? leido;
  final int? categoriaId;
  final int? destacado;
  final String? fechaAviso;
  final String? pospuestoHasta;
  final String? descargadoEn;
  final String? inReplyTo;
  final String? referencias;
  final String? hiloClave;
  final int? cifrado;
  final String? cifradoNivel;
  final String? sobre;
  final String? datos;
  final int? clienteFiscalId;
  const MensajeCorreo({required this.id, this.cuentaId, this.carpeta, this.uid, this.asunto, this.remitente, this.destinatarios, this.cc, this.fecha, this.cuerpoTexto, this.messageId, this.leido, this.categoriaId, this.destacado, this.fechaAviso, this.pospuestoHasta, this.descargadoEn, this.inReplyTo, this.referencias, this.hiloClave, this.cifrado, this.cifradoNivel, this.sobre, this.datos, this.clienteFiscalId, });
  factory MensajeCorreo.fromJson(Map<String, dynamic> j) => MensajeCorreo(
    id: (j['id'] as num).toInt(),
    cuentaId: j['cuenta_id'] == null ? null : (j['cuenta_id'] as num).toInt(),
    carpeta: j['carpeta'] == null ? null : j['carpeta'] as String,
    uid: j['uid'] == null ? null : j['uid'] as String,
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    remitente: j['remitente'] == null ? null : j['remitente'] as String,
    destinatarios: j['destinatarios'] == null ? null : j['destinatarios'] as String,
    cc: j['cc'] == null ? null : j['cc'] as String,
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
    cuerpoTexto: j['cuerpo_texto'] == null ? null : j['cuerpo_texto'] as String,
    messageId: j['message_id'] == null ? null : j['message_id'] as String,
    leido: j['leido'] == null ? null : (j['leido'] as num).toInt(),
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    destacado: j['destacado'] == null ? null : (j['destacado'] as num).toInt(),
    fechaAviso: j['fecha_aviso'] == null ? null : j['fecha_aviso'] as String,
    pospuestoHasta: j['pospuesto_hasta'] == null ? null : j['pospuesto_hasta'] as String,
    descargadoEn: j['descargado_en'] == null ? null : j['descargado_en'] as String,
    inReplyTo: j['in_reply_to'] == null ? null : j['in_reply_to'] as String,
    referencias: j['referencias'] == null ? null : j['referencias'] as String,
    hiloClave: j['hilo_clave'] == null ? null : j['hilo_clave'] as String,
    cifrado: j['cifrado'] == null ? null : (j['cifrado'] as num).toInt(),
    cifradoNivel: j['cifrado_nivel'] == null ? null : j['cifrado_nivel'] as String,
    sobre: j['sobre'] == null ? null : j['sobre'] as String,
    datos: j['datos'] == null ? null : j['datos'] as String,
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'cuenta_id': ?cuentaId,
    'carpeta': ?carpeta,
    'uid': ?uid,
    'asunto': ?asunto,
    'remitente': ?remitente,
    'destinatarios': ?destinatarios,
    'cc': ?cc,
    'fecha': ?fecha,
    'cuerpo_texto': ?cuerpoTexto,
    'message_id': ?messageId,
    'leido': ?leido,
    'categoria_id': ?categoriaId,
    'destacado': ?destacado,
    'fecha_aviso': ?fechaAviso,
    'pospuesto_hasta': ?pospuestoHasta,
    'descargado_en': ?descargadoEn,
    'in_reply_to': ?inReplyTo,
    'referencias': ?referencias,
    'hilo_clave': ?hiloClave,
    'cifrado': ?cifrado,
    'cifrado_nivel': ?cifradoNivel,
    'sobre': ?sobre,
    'datos': ?datos,
    'cliente_fiscal_id': ?clienteFiscalId,
  };
  MensajeCorreo copyWith({int? id, int? cuentaId, String? carpeta, String? uid, String? asunto, String? remitente, String? destinatarios, String? cc, String? fecha, String? cuerpoTexto, String? messageId, int? leido, int? categoriaId, int? destacado, String? fechaAviso, String? pospuestoHasta, String? descargadoEn, String? inReplyTo, String? referencias, String? hiloClave, int? cifrado, String? cifradoNivel, String? sobre, String? datos, int? clienteFiscalId, }) => MensajeCorreo(id: id ?? this.id, cuentaId: cuentaId ?? this.cuentaId, carpeta: carpeta ?? this.carpeta, uid: uid ?? this.uid, asunto: asunto ?? this.asunto, remitente: remitente ?? this.remitente, destinatarios: destinatarios ?? this.destinatarios, cc: cc ?? this.cc, fecha: fecha ?? this.fecha, cuerpoTexto: cuerpoTexto ?? this.cuerpoTexto, messageId: messageId ?? this.messageId, leido: leido ?? this.leido, categoriaId: categoriaId ?? this.categoriaId, destacado: destacado ?? this.destacado, fechaAviso: fechaAviso ?? this.fechaAviso, pospuestoHasta: pospuestoHasta ?? this.pospuestoHasta, descargadoEn: descargadoEn ?? this.descargadoEn, inReplyTo: inReplyTo ?? this.inReplyTo, referencias: referencias ?? this.referencias, hiloClave: hiloClave ?? this.hiloClave, cifrado: cifrado ?? this.cifrado, cifradoNivel: cifradoNivel ?? this.cifradoNivel, sobre: sobre ?? this.sobre, datos: datos ?? this.datos, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, );
  @override bool operator ==(Object other) => other is MensajeCorreo && other.id == id && other.cuentaId == cuentaId && other.carpeta == carpeta && other.uid == uid && other.asunto == asunto && other.remitente == remitente && other.destinatarios == destinatarios && other.cc == cc && other.fecha == fecha && other.cuerpoTexto == cuerpoTexto && other.messageId == messageId && other.leido == leido && other.categoriaId == categoriaId && other.destacado == destacado && other.fechaAviso == fechaAviso && other.pospuestoHasta == pospuestoHasta && other.descargadoEn == descargadoEn && other.inReplyTo == inReplyTo && other.referencias == referencias && other.hiloClave == hiloClave && other.cifrado == cifrado && other.cifradoNivel == cifradoNivel && other.sobre == sobre && other.datos == datos && other.clienteFiscalId == clienteFiscalId;
  @override int get hashCode => Object.hashAll([id, cuentaId, carpeta, uid, asunto, remitente, destinatarios, cc, fecha, cuerpoTexto, messageId, leido, categoriaId, destacado, fechaAviso, pospuestoHasta, descargadoEn, inReplyTo, referencias, hiloClave, cifrado, cifradoNivel, sobre, datos, clienteFiscalId]);
}

class MensajeCorreoDetalle {
  final int id;
  final int? cuentaId;
  final String? carpeta;
  final String? uid;
  final String? asunto;
  final String? remitente;
  final String? destinatarios;
  final String? cc;
  final String? fecha;
  final String? cuerpoTexto;
  final String? messageId;
  final int? leido;
  final int? categoriaId;
  final int? destacado;
  final String? fechaAviso;
  final String? pospuestoHasta;
  final String? descargadoEn;
  final String? inReplyTo;
  final String? referencias;
  final String? hiloClave;
  final int? cifrado;
  final String? cifradoNivel;
  final String? sobre;
  final String? datos;
  final int? clienteFiscalId;
  final String? cuerpoHtml;
  final List<Map<String, dynamic>>? adjuntos;
  const MensajeCorreoDetalle({required this.id, this.cuentaId, this.carpeta, this.uid, this.asunto, this.remitente, this.destinatarios, this.cc, this.fecha, this.cuerpoTexto, this.messageId, this.leido, this.categoriaId, this.destacado, this.fechaAviso, this.pospuestoHasta, this.descargadoEn, this.inReplyTo, this.referencias, this.hiloClave, this.cifrado, this.cifradoNivel, this.sobre, this.datos, this.clienteFiscalId, this.cuerpoHtml, this.adjuntos, });
  factory MensajeCorreoDetalle.fromJson(Map<String, dynamic> j) => MensajeCorreoDetalle(
    id: (j['id'] as num).toInt(),
    cuentaId: j['cuenta_id'] == null ? null : (j['cuenta_id'] as num).toInt(),
    carpeta: j['carpeta'] == null ? null : j['carpeta'] as String,
    uid: j['uid'] == null ? null : j['uid'] as String,
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    remitente: j['remitente'] == null ? null : j['remitente'] as String,
    destinatarios: j['destinatarios'] == null ? null : j['destinatarios'] as String,
    cc: j['cc'] == null ? null : j['cc'] as String,
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
    cuerpoTexto: j['cuerpo_texto'] == null ? null : j['cuerpo_texto'] as String,
    messageId: j['message_id'] == null ? null : j['message_id'] as String,
    leido: j['leido'] == null ? null : (j['leido'] as num).toInt(),
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    destacado: j['destacado'] == null ? null : (j['destacado'] as num).toInt(),
    fechaAviso: j['fecha_aviso'] == null ? null : j['fecha_aviso'] as String,
    pospuestoHasta: j['pospuesto_hasta'] == null ? null : j['pospuesto_hasta'] as String,
    descargadoEn: j['descargado_en'] == null ? null : j['descargado_en'] as String,
    inReplyTo: j['in_reply_to'] == null ? null : j['in_reply_to'] as String,
    referencias: j['referencias'] == null ? null : j['referencias'] as String,
    hiloClave: j['hilo_clave'] == null ? null : j['hilo_clave'] as String,
    cifrado: j['cifrado'] == null ? null : (j['cifrado'] as num).toInt(),
    cifradoNivel: j['cifrado_nivel'] == null ? null : j['cifrado_nivel'] as String,
    sobre: j['sobre'] == null ? null : j['sobre'] as String,
    datos: j['datos'] == null ? null : j['datos'] as String,
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    cuerpoHtml: j['cuerpo_html'] == null ? null : j['cuerpo_html'] as String,
    adjuntos: j['adjuntos'] == null ? null : (j['adjuntos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'cuenta_id': ?cuentaId,
    'carpeta': ?carpeta,
    'uid': ?uid,
    'asunto': ?asunto,
    'remitente': ?remitente,
    'destinatarios': ?destinatarios,
    'cc': ?cc,
    'fecha': ?fecha,
    'cuerpo_texto': ?cuerpoTexto,
    'message_id': ?messageId,
    'leido': ?leido,
    'categoria_id': ?categoriaId,
    'destacado': ?destacado,
    'fecha_aviso': ?fechaAviso,
    'pospuesto_hasta': ?pospuestoHasta,
    'descargado_en': ?descargadoEn,
    'in_reply_to': ?inReplyTo,
    'referencias': ?referencias,
    'hilo_clave': ?hiloClave,
    'cifrado': ?cifrado,
    'cifrado_nivel': ?cifradoNivel,
    'sobre': ?sobre,
    'datos': ?datos,
    'cliente_fiscal_id': ?clienteFiscalId,
    'cuerpo_html': ?cuerpoHtml,
    if (adjuntos != null) 'adjuntos': adjuntos!.map((e) => e).toList(),
  };
  MensajeCorreoDetalle copyWith({int? id, int? cuentaId, String? carpeta, String? uid, String? asunto, String? remitente, String? destinatarios, String? cc, String? fecha, String? cuerpoTexto, String? messageId, int? leido, int? categoriaId, int? destacado, String? fechaAviso, String? pospuestoHasta, String? descargadoEn, String? inReplyTo, String? referencias, String? hiloClave, int? cifrado, String? cifradoNivel, String? sobre, String? datos, int? clienteFiscalId, String? cuerpoHtml, List<Map<String, dynamic>>? adjuntos, }) => MensajeCorreoDetalle(id: id ?? this.id, cuentaId: cuentaId ?? this.cuentaId, carpeta: carpeta ?? this.carpeta, uid: uid ?? this.uid, asunto: asunto ?? this.asunto, remitente: remitente ?? this.remitente, destinatarios: destinatarios ?? this.destinatarios, cc: cc ?? this.cc, fecha: fecha ?? this.fecha, cuerpoTexto: cuerpoTexto ?? this.cuerpoTexto, messageId: messageId ?? this.messageId, leido: leido ?? this.leido, categoriaId: categoriaId ?? this.categoriaId, destacado: destacado ?? this.destacado, fechaAviso: fechaAviso ?? this.fechaAviso, pospuestoHasta: pospuestoHasta ?? this.pospuestoHasta, descargadoEn: descargadoEn ?? this.descargadoEn, inReplyTo: inReplyTo ?? this.inReplyTo, referencias: referencias ?? this.referencias, hiloClave: hiloClave ?? this.hiloClave, cifrado: cifrado ?? this.cifrado, cifradoNivel: cifradoNivel ?? this.cifradoNivel, sobre: sobre ?? this.sobre, datos: datos ?? this.datos, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, cuerpoHtml: cuerpoHtml ?? this.cuerpoHtml, adjuntos: adjuntos ?? this.adjuntos, );
  @override bool operator ==(Object other) => other is MensajeCorreoDetalle && other.id == id && other.cuentaId == cuentaId && other.carpeta == carpeta && other.uid == uid && other.asunto == asunto && other.remitente == remitente && other.destinatarios == destinatarios && other.cc == cc && other.fecha == fecha && other.cuerpoTexto == cuerpoTexto && other.messageId == messageId && other.leido == leido && other.categoriaId == categoriaId && other.destacado == destacado && other.fechaAviso == fechaAviso && other.pospuestoHasta == pospuestoHasta && other.descargadoEn == descargadoEn && other.inReplyTo == inReplyTo && other.referencias == referencias && other.hiloClave == hiloClave && other.cifrado == cifrado && other.cifradoNivel == cifradoNivel && other.sobre == sobre && other.datos == datos && other.clienteFiscalId == clienteFiscalId && other.cuerpoHtml == cuerpoHtml && other.adjuntos == adjuntos;
  @override int get hashCode => Object.hashAll([id, cuentaId, carpeta, uid, asunto, remitente, destinatarios, cc, fecha, cuerpoTexto, messageId, leido, categoriaId, destacado, fechaAviso, pospuestoHasta, descargadoEn, inReplyTo, referencias, hiloClave, cifrado, cifradoNivel, sobre, datos, clienteFiscalId, cuerpoHtml, adjuntos]);
}

class MensajeIA {
  final int id;
  final int? usuarioId;
  final String? rol;
  final String? contenido;
  final String? toolCallsJson;
  final String? toolCallId;
  final String? nombreHerramienta;
  final String? creadoEn;
  final int? conversacionId;
  final String? fuentesJson;
  const MensajeIA({required this.id, this.usuarioId, this.rol, this.contenido, this.toolCallsJson, this.toolCallId, this.nombreHerramienta, this.creadoEn, this.conversacionId, this.fuentesJson, });
  factory MensajeIA.fromJson(Map<String, dynamic> j) => MensajeIA(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    rol: j['rol'] == null ? null : j['rol'] as String,
    contenido: j['contenido'] == null ? null : j['contenido'] as String,
    toolCallsJson: j['tool_calls_json'] == null ? null : j['tool_calls_json'] as String,
    toolCallId: j['tool_call_id'] == null ? null : j['tool_call_id'] as String,
    nombreHerramienta: j['nombre_herramienta'] == null ? null : j['nombre_herramienta'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    conversacionId: j['conversacion_id'] == null ? null : (j['conversacion_id'] as num).toInt(),
    fuentesJson: j['fuentes_json'] == null ? null : j['fuentes_json'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'rol': ?rol,
    'contenido': ?contenido,
    'tool_calls_json': ?toolCallsJson,
    'tool_call_id': ?toolCallId,
    'nombre_herramienta': ?nombreHerramienta,
    'creado_en': ?creadoEn,
    'conversacion_id': ?conversacionId,
    'fuentes_json': ?fuentesJson,
  };
  MensajeIA copyWith({int? id, int? usuarioId, String? rol, String? contenido, String? toolCallsJson, String? toolCallId, String? nombreHerramienta, String? creadoEn, int? conversacionId, String? fuentesJson, }) => MensajeIA(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, rol: rol ?? this.rol, contenido: contenido ?? this.contenido, toolCallsJson: toolCallsJson ?? this.toolCallsJson, toolCallId: toolCallId ?? this.toolCallId, nombreHerramienta: nombreHerramienta ?? this.nombreHerramienta, creadoEn: creadoEn ?? this.creadoEn, conversacionId: conversacionId ?? this.conversacionId, fuentesJson: fuentesJson ?? this.fuentesJson, );
  @override bool operator ==(Object other) => other is MensajeIA && other.id == id && other.usuarioId == usuarioId && other.rol == rol && other.contenido == contenido && other.toolCallsJson == toolCallsJson && other.toolCallId == toolCallId && other.nombreHerramienta == nombreHerramienta && other.creadoEn == creadoEn && other.conversacionId == conversacionId && other.fuentesJson == fuentesJson;
  @override int get hashCode => Object.hashAll([id, usuarioId, rol, contenido, toolCallsJson, toolCallId, nombreHerramienta, creadoEn, conversacionId, fuentesJson]);
}

class MensajeVencimiento {
  final int id;
  final int? vencimientoId;
  final String? autor;
  final int? usuarioId;
  final String? texto;
  final String? creadoEn;
  final String? leidoEn;
  const MensajeVencimiento({required this.id, this.vencimientoId, this.autor, this.usuarioId, this.texto, this.creadoEn, this.leidoEn, });
  factory MensajeVencimiento.fromJson(Map<String, dynamic> j) => MensajeVencimiento(
    id: (j['id'] as num).toInt(),
    vencimientoId: j['vencimiento_id'] == null ? null : (j['vencimiento_id'] as num).toInt(),
    autor: j['autor'] == null ? null : j['autor'] as String,
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    texto: j['texto'] == null ? null : j['texto'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    leidoEn: j['leido_en'] == null ? null : j['leido_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'vencimiento_id': ?vencimientoId,
    'autor': ?autor,
    'usuario_id': ?usuarioId,
    'texto': ?texto,
    'creado_en': ?creadoEn,
    'leido_en': ?leidoEn,
  };
  MensajeVencimiento copyWith({int? id, int? vencimientoId, String? autor, int? usuarioId, String? texto, String? creadoEn, String? leidoEn, }) => MensajeVencimiento(id: id ?? this.id, vencimientoId: vencimientoId ?? this.vencimientoId, autor: autor ?? this.autor, usuarioId: usuarioId ?? this.usuarioId, texto: texto ?? this.texto, creadoEn: creadoEn ?? this.creadoEn, leidoEn: leidoEn ?? this.leidoEn, );
  @override bool operator ==(Object other) => other is MensajeVencimiento && other.id == id && other.vencimientoId == vencimientoId && other.autor == autor && other.usuarioId == usuarioId && other.texto == texto && other.creadoEn == creadoEn && other.leidoEn == leidoEn;
  @override int get hashCode => Object.hashAll([id, vencimientoId, autor, usuarioId, texto, creadoEn, leidoEn]);
}

class MetricasAvisos {
  final int? dias;
  final int? creadas;
  final int? abiertas;
  final int? acusadas;
  final int? resueltas;
  final int? sinAcusarMasDe24h;
  final int? escaladas;
  final int? fallosDeEntrega;
  final int? duplicados;
  final double? horasHastaAcuseMediana;
  final int? muestraAcuses;
  const MetricasAvisos({this.dias, this.creadas, this.abiertas, this.acusadas, this.resueltas, this.sinAcusarMasDe24h, this.escaladas, this.fallosDeEntrega, this.duplicados, this.horasHastaAcuseMediana, this.muestraAcuses, });
  factory MetricasAvisos.fromJson(Map<String, dynamic> j) => MetricasAvisos(
    dias: j['dias'] == null ? null : (j['dias'] as num).toInt(),
    creadas: j['creadas'] == null ? null : (j['creadas'] as num).toInt(),
    abiertas: j['abiertas'] == null ? null : (j['abiertas'] as num).toInt(),
    acusadas: j['acusadas'] == null ? null : (j['acusadas'] as num).toInt(),
    resueltas: j['resueltas'] == null ? null : (j['resueltas'] as num).toInt(),
    sinAcusarMasDe24h: j['sin_acusar_mas_de_24h'] == null ? null : (j['sin_acusar_mas_de_24h'] as num).toInt(),
    escaladas: j['escaladas'] == null ? null : (j['escaladas'] as num).toInt(),
    fallosDeEntrega: j['fallos_de_entrega'] == null ? null : (j['fallos_de_entrega'] as num).toInt(),
    duplicados: j['duplicados'] == null ? null : (j['duplicados'] as num).toInt(),
    horasHastaAcuseMediana: j['horas_hasta_acuse_mediana'] == null ? null : (j['horas_hasta_acuse_mediana'] as num).toDouble(),
    muestraAcuses: j['muestra_acuses'] == null ? null : (j['muestra_acuses'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'dias': ?dias,
    'creadas': ?creadas,
    'abiertas': ?abiertas,
    'acusadas': ?acusadas,
    'resueltas': ?resueltas,
    'sin_acusar_mas_de_24h': ?sinAcusarMasDe24h,
    'escaladas': ?escaladas,
    'fallos_de_entrega': ?fallosDeEntrega,
    'duplicados': ?duplicados,
    'horas_hasta_acuse_mediana': ?horasHastaAcuseMediana,
    'muestra_acuses': ?muestraAcuses,
  };
  MetricasAvisos copyWith({int? dias, int? creadas, int? abiertas, int? acusadas, int? resueltas, int? sinAcusarMasDe24h, int? escaladas, int? fallosDeEntrega, int? duplicados, double? horasHastaAcuseMediana, int? muestraAcuses, }) => MetricasAvisos(dias: dias ?? this.dias, creadas: creadas ?? this.creadas, abiertas: abiertas ?? this.abiertas, acusadas: acusadas ?? this.acusadas, resueltas: resueltas ?? this.resueltas, sinAcusarMasDe24h: sinAcusarMasDe24h ?? this.sinAcusarMasDe24h, escaladas: escaladas ?? this.escaladas, fallosDeEntrega: fallosDeEntrega ?? this.fallosDeEntrega, duplicados: duplicados ?? this.duplicados, horasHastaAcuseMediana: horasHastaAcuseMediana ?? this.horasHastaAcuseMediana, muestraAcuses: muestraAcuses ?? this.muestraAcuses, );
  @override bool operator ==(Object other) => other is MetricasAvisos && other.dias == dias && other.creadas == creadas && other.abiertas == abiertas && other.acusadas == acusadas && other.resueltas == resueltas && other.sinAcusarMasDe24h == sinAcusarMasDe24h && other.escaladas == escaladas && other.fallosDeEntrega == fallosDeEntrega && other.duplicados == duplicados && other.horasHastaAcuseMediana == horasHastaAcuseMediana && other.muestraAcuses == muestraAcuses;
  @override int get hashCode => Object.hashAll([dias, creadas, abiertas, acusadas, resueltas, sinAcusarMasDe24h, escaladas, fallosDeEntrega, duplicados, horasHastaAcuseMediana, muestraAcuses]);
}

class ModeloIA {
  final String? id;
  final String? nombre;
  const ModeloIA({this.id, this.nombre, });
  factory ModeloIA.fromJson(Map<String, dynamic> j) => ModeloIA(
    id: j['id'] == null ? null : j['id'] as String,
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
  };
  ModeloIA copyWith({String? id, String? nombre, }) => ModeloIA(id: id ?? this.id, nombre: nombre ?? this.nombre, );
  @override bool operator ==(Object other) => other is ModeloIA && other.id == id && other.nombre == nombre;
  @override int get hashCode => Object.hashAll([id, nombre]);
}

class Nota {
  final int id;
  final int? usuarioId;
  final String? texto;
  final int? categoriaId;
  final int? tareaId;
  final String? creadaEn;
  final String? papeleraEn;
  final String? referenciaExterna;
  final String? titulo;
  final int? fijada;
  final int? clienteFiscalId;
  final int? tareaOutlookId;
  final int? mensajeCorreoId;
  final String? clienteUuid;
  final String? categoriaNombre;
  final String? duenoNombre;
  const Nota({required this.id, this.usuarioId, this.texto, this.categoriaId, this.tareaId, this.creadaEn, this.papeleraEn, this.referenciaExterna, this.titulo, this.fijada, this.clienteFiscalId, this.tareaOutlookId, this.mensajeCorreoId, this.clienteUuid, this.categoriaNombre, this.duenoNombre, });
  factory Nota.fromJson(Map<String, dynamic> j) => Nota(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    texto: j['texto'] == null ? null : j['texto'] as String,
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    tareaId: j['tarea_id'] == null ? null : (j['tarea_id'] as num).toInt(),
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
    referenciaExterna: j['referencia_externa'] == null ? null : j['referencia_externa'] as String,
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    fijada: j['fijada'] == null ? null : (j['fijada'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    tareaOutlookId: j['tarea_outlook_id'] == null ? null : (j['tarea_outlook_id'] as num).toInt(),
    mensajeCorreoId: j['mensaje_correo_id'] == null ? null : (j['mensaje_correo_id'] as num).toInt(),
    clienteUuid: j['cliente_uuid'] == null ? null : j['cliente_uuid'] as String,
    categoriaNombre: j['categoria_nombre'] == null ? null : j['categoria_nombre'] as String,
    duenoNombre: j['dueno_nombre'] == null ? null : j['dueno_nombre'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'texto': ?texto,
    'categoria_id': ?categoriaId,
    'tarea_id': ?tareaId,
    'creada_en': ?creadaEn,
    'papelera_en': ?papeleraEn,
    'referencia_externa': ?referenciaExterna,
    'titulo': ?titulo,
    'fijada': ?fijada,
    'cliente_fiscal_id': ?clienteFiscalId,
    'tarea_outlook_id': ?tareaOutlookId,
    'mensaje_correo_id': ?mensajeCorreoId,
    'cliente_uuid': ?clienteUuid,
    'categoria_nombre': ?categoriaNombre,
    'dueno_nombre': ?duenoNombre,
  };
  Nota copyWith({int? id, int? usuarioId, String? texto, int? categoriaId, int? tareaId, String? creadaEn, String? papeleraEn, String? referenciaExterna, String? titulo, int? fijada, int? clienteFiscalId, int? tareaOutlookId, int? mensajeCorreoId, String? clienteUuid, String? categoriaNombre, String? duenoNombre, }) => Nota(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, texto: texto ?? this.texto, categoriaId: categoriaId ?? this.categoriaId, tareaId: tareaId ?? this.tareaId, creadaEn: creadaEn ?? this.creadaEn, papeleraEn: papeleraEn ?? this.papeleraEn, referenciaExterna: referenciaExterna ?? this.referenciaExterna, titulo: titulo ?? this.titulo, fijada: fijada ?? this.fijada, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, tareaOutlookId: tareaOutlookId ?? this.tareaOutlookId, mensajeCorreoId: mensajeCorreoId ?? this.mensajeCorreoId, clienteUuid: clienteUuid ?? this.clienteUuid, categoriaNombre: categoriaNombre ?? this.categoriaNombre, duenoNombre: duenoNombre ?? this.duenoNombre, );
  @override bool operator ==(Object other) => other is Nota && other.id == id && other.usuarioId == usuarioId && other.texto == texto && other.categoriaId == categoriaId && other.tareaId == tareaId && other.creadaEn == creadaEn && other.papeleraEn == papeleraEn && other.referenciaExterna == referenciaExterna && other.titulo == titulo && other.fijada == fijada && other.clienteFiscalId == clienteFiscalId && other.tareaOutlookId == tareaOutlookId && other.mensajeCorreoId == mensajeCorreoId && other.clienteUuid == clienteUuid && other.categoriaNombre == categoriaNombre && other.duenoNombre == duenoNombre;
  @override int get hashCode => Object.hashAll([id, usuarioId, texto, categoriaId, tareaId, creadaEn, papeleraEn, referenciaExterna, titulo, fijada, clienteFiscalId, tareaOutlookId, mensajeCorreoId, clienteUuid, categoriaNombre, duenoNombre]);
}

class Notificacion {
  final int id;
  final int? usuarioId;
  final String? tipo;
  final String? titulo;
  final String? cuerpo;
  final String? url;
  final String? creadoEn;
  final String? leidoEn;
  final DestinoAviso? destino;
  final NotificacionCanal? canal;
  const Notificacion({required this.id, this.usuarioId, this.tipo, this.titulo, this.cuerpo, this.url, this.creadoEn, this.leidoEn, this.destino, this.canal, });
  factory Notificacion.fromJson(Map<String, dynamic> j) => Notificacion(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    cuerpo: j['cuerpo'] == null ? null : j['cuerpo'] as String,
    url: j['url'] == null ? null : j['url'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    leidoEn: j['leido_en'] == null ? null : j['leido_en'] as String,
    destino: j['destino'] == null ? null : DestinoAviso.fromJson(j['destino'] as Map<String, dynamic>),
    canal: j['canal'] == null ? null : NotificacionCanal.desde(j['canal'] as String),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'tipo': ?tipo,
    'titulo': ?titulo,
    'cuerpo': ?cuerpo,
    'url': ?url,
    'creado_en': ?creadoEn,
    'leido_en': ?leidoEn,
    if (destino != null) 'destino': destino!.toJson(),
    if (canal != null) 'canal': canal!.valor,
  };
  Notificacion copyWith({int? id, int? usuarioId, String? tipo, String? titulo, String? cuerpo, String? url, String? creadoEn, String? leidoEn, DestinoAviso? destino, NotificacionCanal? canal, }) => Notificacion(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, tipo: tipo ?? this.tipo, titulo: titulo ?? this.titulo, cuerpo: cuerpo ?? this.cuerpo, url: url ?? this.url, creadoEn: creadoEn ?? this.creadoEn, leidoEn: leidoEn ?? this.leidoEn, destino: destino ?? this.destino, canal: canal ?? this.canal, );
  @override bool operator ==(Object other) => other is Notificacion && other.id == id && other.usuarioId == usuarioId && other.tipo == tipo && other.titulo == titulo && other.cuerpo == cuerpo && other.url == url && other.creadoEn == creadoEn && other.leidoEn == leidoEn && other.destino == destino && other.canal == canal;
  @override int get hashCode => Object.hashAll([id, usuarioId, tipo, titulo, cuerpo, url, creadoEn, leidoEn, destino, canal]);
}

class NotificacionesRespuesta {
  final int? noLeidas;
  final List<Notificacion>? notificaciones;
  const NotificacionesRespuesta({this.noLeidas, this.notificaciones, });
  factory NotificacionesRespuesta.fromJson(Map<String, dynamic> j) => NotificacionesRespuesta(
    noLeidas: j['no_leidas'] == null ? null : (j['no_leidas'] as num).toInt(),
    notificaciones: j['notificaciones'] == null ? null : (j['notificaciones'] as List).map((e) => Notificacion.fromJson(e as Map<String, dynamic>)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'no_leidas': ?noLeidas,
    if (notificaciones != null) 'notificaciones': notificaciones!.map((e) => e.toJson()).toList(),
  };
  NotificacionesRespuesta copyWith({int? noLeidas, List<Notificacion>? notificaciones, }) => NotificacionesRespuesta(noLeidas: noLeidas ?? this.noLeidas, notificaciones: notificaciones ?? this.notificaciones, );
  @override bool operator ==(Object other) => other is NotificacionesRespuesta && other.noLeidas == noLeidas && other.notificaciones == notificaciones;
  @override int get hashCode => Object.hashAll([noLeidas, notificaciones]);
}

class Oficina {
  final int id;
  final String? nombre;
  final int? activa;
  final String? creadoEn;
  final int? clientes;
  final int? personas;
  const Oficina({required this.id, this.nombre, this.activa, this.creadoEn, this.clientes, this.personas, });
  factory Oficina.fromJson(Map<String, dynamic> j) => Oficina(
    id: (j['id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    activa: j['activa'] == null ? null : (j['activa'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    clientes: j['clientes'] == null ? null : (j['clientes'] as num).toInt(),
    personas: j['personas'] == null ? null : (j['personas'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'nombre': ?nombre,
    'activa': ?activa,
    'creado_en': ?creadoEn,
    'clientes': ?clientes,
    'personas': ?personas,
  };
  Oficina copyWith({int? id, String? nombre, int? activa, String? creadoEn, int? clientes, int? personas, }) => Oficina(id: id ?? this.id, nombre: nombre ?? this.nombre, activa: activa ?? this.activa, creadoEn: creadoEn ?? this.creadoEn, clientes: clientes ?? this.clientes, personas: personas ?? this.personas, );
  @override bool operator ==(Object other) => other is Oficina && other.id == id && other.nombre == nombre && other.activa == activa && other.creadoEn == creadoEn && other.clientes == clientes && other.personas == personas;
  @override int get hashCode => Object.hashAll([id, nombre, activa, creadoEn, clientes, personas]);
}

class OportunidadComercial {
  final int? id;
  final String? titulo;
  final String? etapa;
  final String? etapaNombre;
  final OportunidadComercialEstado? estado;
  final int? probabilidad;
  final String? cierrePrevisto;
  final String? responsable;
  final int? responsableId;
  final String? origen;
  final String? motivoPerdida;
  final String? contacto;
  final int? clienteId;
  final String? contactoEmail;
  final String? contactoTelefono;
  final String? empresa;
  final String? notas;
  final double? importe;
  final int? importeCentimos;
  final double? ponderado;
  final String? creadaEn;
  final String? actualizadaEn;
  final String? cerradaEn;
  const OportunidadComercial({this.id, this.titulo, this.etapa, this.etapaNombre, this.estado, this.probabilidad, this.cierrePrevisto, this.responsable, this.responsableId, this.origen, this.motivoPerdida, this.contacto, this.clienteId, this.contactoEmail, this.contactoTelefono, this.empresa, this.notas, this.importe, this.importeCentimos, this.ponderado, this.creadaEn, this.actualizadaEn, this.cerradaEn, });
  factory OportunidadComercial.fromJson(Map<String, dynamic> j) => OportunidadComercial(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    etapa: j['etapa'] == null ? null : j['etapa'] as String,
    etapaNombre: j['etapa_nombre'] == null ? null : j['etapa_nombre'] as String,
    estado: j['estado'] == null ? null : OportunidadComercialEstado.desde(j['estado'] as String),
    probabilidad: j['probabilidad'] == null ? null : (j['probabilidad'] as num).toInt(),
    cierrePrevisto: j['cierre_previsto'] == null ? null : j['cierre_previsto'] as String,
    responsable: j['responsable'] == null ? null : j['responsable'] as String,
    responsableId: j['responsable_id'] == null ? null : (j['responsable_id'] as num).toInt(),
    origen: j['origen'] == null ? null : j['origen'] as String,
    motivoPerdida: j['motivo_perdida'] == null ? null : j['motivo_perdida'] as String,
    contacto: j['contacto'] == null ? null : j['contacto'] as String,
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    contactoEmail: j['contacto_email'] == null ? null : j['contacto_email'] as String,
    contactoTelefono: j['contacto_telefono'] == null ? null : j['contacto_telefono'] as String,
    empresa: j['empresa'] == null ? null : j['empresa'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    importe: j['importe'] == null ? null : (j['importe'] as num).toDouble(),
    importeCentimos: j['importe_centimos'] == null ? null : (j['importe_centimos'] as num).toInt(),
    ponderado: j['ponderado'] == null ? null : (j['ponderado'] as num).toDouble(),
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    actualizadaEn: j['actualizada_en'] == null ? null : j['actualizada_en'] as String,
    cerradaEn: j['cerrada_en'] == null ? null : j['cerrada_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'titulo': ?titulo,
    'etapa': ?etapa,
    'etapa_nombre': ?etapaNombre,
    if (estado != null) 'estado': estado!.valor,
    'probabilidad': ?probabilidad,
    'cierre_previsto': ?cierrePrevisto,
    'responsable': ?responsable,
    'responsable_id': ?responsableId,
    'origen': ?origen,
    'motivo_perdida': ?motivoPerdida,
    'contacto': ?contacto,
    'cliente_id': ?clienteId,
    'contacto_email': ?contactoEmail,
    'contacto_telefono': ?contactoTelefono,
    'empresa': ?empresa,
    'notas': ?notas,
    'importe': ?importe,
    'importe_centimos': ?importeCentimos,
    'ponderado': ?ponderado,
    'creada_en': ?creadaEn,
    'actualizada_en': ?actualizadaEn,
    'cerrada_en': ?cerradaEn,
  };
  OportunidadComercial copyWith({int? id, String? titulo, String? etapa, String? etapaNombre, OportunidadComercialEstado? estado, int? probabilidad, String? cierrePrevisto, String? responsable, int? responsableId, String? origen, String? motivoPerdida, String? contacto, int? clienteId, String? contactoEmail, String? contactoTelefono, String? empresa, String? notas, double? importe, int? importeCentimos, double? ponderado, String? creadaEn, String? actualizadaEn, String? cerradaEn, }) => OportunidadComercial(id: id ?? this.id, titulo: titulo ?? this.titulo, etapa: etapa ?? this.etapa, etapaNombre: etapaNombre ?? this.etapaNombre, estado: estado ?? this.estado, probabilidad: probabilidad ?? this.probabilidad, cierrePrevisto: cierrePrevisto ?? this.cierrePrevisto, responsable: responsable ?? this.responsable, responsableId: responsableId ?? this.responsableId, origen: origen ?? this.origen, motivoPerdida: motivoPerdida ?? this.motivoPerdida, contacto: contacto ?? this.contacto, clienteId: clienteId ?? this.clienteId, contactoEmail: contactoEmail ?? this.contactoEmail, contactoTelefono: contactoTelefono ?? this.contactoTelefono, empresa: empresa ?? this.empresa, notas: notas ?? this.notas, importe: importe ?? this.importe, importeCentimos: importeCentimos ?? this.importeCentimos, ponderado: ponderado ?? this.ponderado, creadaEn: creadaEn ?? this.creadaEn, actualizadaEn: actualizadaEn ?? this.actualizadaEn, cerradaEn: cerradaEn ?? this.cerradaEn, );
  @override bool operator ==(Object other) => other is OportunidadComercial && other.id == id && other.titulo == titulo && other.etapa == etapa && other.etapaNombre == etapaNombre && other.estado == estado && other.probabilidad == probabilidad && other.cierrePrevisto == cierrePrevisto && other.responsable == responsable && other.responsableId == responsableId && other.origen == origen && other.motivoPerdida == motivoPerdida && other.contacto == contacto && other.clienteId == clienteId && other.contactoEmail == contactoEmail && other.contactoTelefono == contactoTelefono && other.empresa == empresa && other.notas == notas && other.importe == importe && other.importeCentimos == importeCentimos && other.ponderado == ponderado && other.creadaEn == creadaEn && other.actualizadaEn == actualizadaEn && other.cerradaEn == cerradaEn;
  @override int get hashCode => Object.hashAll([id, titulo, etapa, etapaNombre, estado, probabilidad, cierrePrevisto, responsable, responsableId, origen, motivoPerdida, contacto, clienteId, contactoEmail, contactoTelefono, empresa, notas, importe, importeCentimos, ponderado, creadaEn, actualizadaEn, cerradaEn]);
}

class OportunidadComercialDetalle {
  final int? id;
  final String? titulo;
  final String? etapa;
  final String? etapaNombre;
  final OportunidadComercialDetalleEstado? estado;
  final int? probabilidad;
  final String? cierrePrevisto;
  final String? responsable;
  final int? responsableId;
  final String? origen;
  final String? motivoPerdida;
  final String? contacto;
  final int? clienteId;
  final String? contactoEmail;
  final String? contactoTelefono;
  final String? empresa;
  final String? notas;
  final double? importe;
  final int? importeCentimos;
  final double? ponderado;
  final String? creadaEn;
  final String? actualizadaEn;
  final String? cerradaEn;
  const OportunidadComercialDetalle({this.id, this.titulo, this.etapa, this.etapaNombre, this.estado, this.probabilidad, this.cierrePrevisto, this.responsable, this.responsableId, this.origen, this.motivoPerdida, this.contacto, this.clienteId, this.contactoEmail, this.contactoTelefono, this.empresa, this.notas, this.importe, this.importeCentimos, this.ponderado, this.creadaEn, this.actualizadaEn, this.cerradaEn, });
  factory OportunidadComercialDetalle.fromJson(Map<String, dynamic> j) => OportunidadComercialDetalle(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    etapa: j['etapa'] == null ? null : j['etapa'] as String,
    etapaNombre: j['etapa_nombre'] == null ? null : j['etapa_nombre'] as String,
    estado: j['estado'] == null ? null : OportunidadComercialDetalleEstado.desde(j['estado'] as String),
    probabilidad: j['probabilidad'] == null ? null : (j['probabilidad'] as num).toInt(),
    cierrePrevisto: j['cierre_previsto'] == null ? null : j['cierre_previsto'] as String,
    responsable: j['responsable'] == null ? null : j['responsable'] as String,
    responsableId: j['responsable_id'] == null ? null : (j['responsable_id'] as num).toInt(),
    origen: j['origen'] == null ? null : j['origen'] as String,
    motivoPerdida: j['motivo_perdida'] == null ? null : j['motivo_perdida'] as String,
    contacto: j['contacto'] == null ? null : j['contacto'] as String,
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    contactoEmail: j['contacto_email'] == null ? null : j['contacto_email'] as String,
    contactoTelefono: j['contacto_telefono'] == null ? null : j['contacto_telefono'] as String,
    empresa: j['empresa'] == null ? null : j['empresa'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    importe: j['importe'] == null ? null : (j['importe'] as num).toDouble(),
    importeCentimos: j['importe_centimos'] == null ? null : (j['importe_centimos'] as num).toInt(),
    ponderado: j['ponderado'] == null ? null : (j['ponderado'] as num).toDouble(),
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    actualizadaEn: j['actualizada_en'] == null ? null : j['actualizada_en'] as String,
    cerradaEn: j['cerrada_en'] == null ? null : j['cerrada_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'titulo': ?titulo,
    'etapa': ?etapa,
    'etapa_nombre': ?etapaNombre,
    if (estado != null) 'estado': estado!.valor,
    'probabilidad': ?probabilidad,
    'cierre_previsto': ?cierrePrevisto,
    'responsable': ?responsable,
    'responsable_id': ?responsableId,
    'origen': ?origen,
    'motivo_perdida': ?motivoPerdida,
    'contacto': ?contacto,
    'cliente_id': ?clienteId,
    'contacto_email': ?contactoEmail,
    'contacto_telefono': ?contactoTelefono,
    'empresa': ?empresa,
    'notas': ?notas,
    'importe': ?importe,
    'importe_centimos': ?importeCentimos,
    'ponderado': ?ponderado,
    'creada_en': ?creadaEn,
    'actualizada_en': ?actualizadaEn,
    'cerrada_en': ?cerradaEn,
  };
  OportunidadComercialDetalle copyWith({int? id, String? titulo, String? etapa, String? etapaNombre, OportunidadComercialDetalleEstado? estado, int? probabilidad, String? cierrePrevisto, String? responsable, int? responsableId, String? origen, String? motivoPerdida, String? contacto, int? clienteId, String? contactoEmail, String? contactoTelefono, String? empresa, String? notas, double? importe, int? importeCentimos, double? ponderado, String? creadaEn, String? actualizadaEn, String? cerradaEn, }) => OportunidadComercialDetalle(id: id ?? this.id, titulo: titulo ?? this.titulo, etapa: etapa ?? this.etapa, etapaNombre: etapaNombre ?? this.etapaNombre, estado: estado ?? this.estado, probabilidad: probabilidad ?? this.probabilidad, cierrePrevisto: cierrePrevisto ?? this.cierrePrevisto, responsable: responsable ?? this.responsable, responsableId: responsableId ?? this.responsableId, origen: origen ?? this.origen, motivoPerdida: motivoPerdida ?? this.motivoPerdida, contacto: contacto ?? this.contacto, clienteId: clienteId ?? this.clienteId, contactoEmail: contactoEmail ?? this.contactoEmail, contactoTelefono: contactoTelefono ?? this.contactoTelefono, empresa: empresa ?? this.empresa, notas: notas ?? this.notas, importe: importe ?? this.importe, importeCentimos: importeCentimos ?? this.importeCentimos, ponderado: ponderado ?? this.ponderado, creadaEn: creadaEn ?? this.creadaEn, actualizadaEn: actualizadaEn ?? this.actualizadaEn, cerradaEn: cerradaEn ?? this.cerradaEn, );
  @override bool operator ==(Object other) => other is OportunidadComercialDetalle && other.id == id && other.titulo == titulo && other.etapa == etapa && other.etapaNombre == etapaNombre && other.estado == estado && other.probabilidad == probabilidad && other.cierrePrevisto == cierrePrevisto && other.responsable == responsable && other.responsableId == responsableId && other.origen == origen && other.motivoPerdida == motivoPerdida && other.contacto == contacto && other.clienteId == clienteId && other.contactoEmail == contactoEmail && other.contactoTelefono == contactoTelefono && other.empresa == empresa && other.notas == notas && other.importe == importe && other.importeCentimos == importeCentimos && other.ponderado == ponderado && other.creadaEn == creadaEn && other.actualizadaEn == actualizadaEn && other.cerradaEn == cerradaEn;
  @override int get hashCode => Object.hashAll([id, titulo, etapa, etapaNombre, estado, probabilidad, cierrePrevisto, responsable, responsableId, origen, motivoPerdida, contacto, clienteId, contactoEmail, contactoTelefono, empresa, notas, importe, importeCentimos, ponderado, creadaEn, actualizadaEn, cerradaEn]);
}

class PanelFiscal {
  final String? generadoEn;
  final String? hoy;
  final PanelFiscalAmbito? ambito;
  final Map<String, dynamic>? totales;
  final Map<String, dynamic>? hoyLista;
  final List<Map<String, dynamic>>? bloqueadas;
  final List<Traspaso>? traspasos;
  final List<RiesgoCertificado>? riesgosCertificados;
  final Map<String, dynamic>? certificados;
  final List<Map<String, dynamic>>? cargaPorResponsable;
  final List<Map<String, dynamic>>? cargaPorOficina;
  final Map<String, dynamic>? indicadores;
  const PanelFiscal({this.generadoEn, this.hoy, this.ambito, this.totales, this.hoyLista, this.bloqueadas, this.traspasos, this.riesgosCertificados, this.certificados, this.cargaPorResponsable, this.cargaPorOficina, this.indicadores, });
  factory PanelFiscal.fromJson(Map<String, dynamic> j) => PanelFiscal(
    generadoEn: j['generado_en'] == null ? null : j['generado_en'] as String,
    hoy: j['hoy'] == null ? null : j['hoy'] as String,
    ambito: j['ambito'] == null ? null : PanelFiscalAmbito.desde(j['ambito'] as String),
    totales: j['totales'] == null ? null : Map<String, dynamic>.from(j['totales'] as Map),
    hoyLista: j['hoy_lista'] == null ? null : Map<String, dynamic>.from(j['hoy_lista'] as Map),
    bloqueadas: j['bloqueadas'] == null ? null : (j['bloqueadas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    traspasos: j['traspasos'] == null ? null : (j['traspasos'] as List).map((e) => Traspaso.fromJson(e as Map<String, dynamic>)).toList(),
    riesgosCertificados: j['riesgos_certificados'] == null ? null : (j['riesgos_certificados'] as List).map((e) => RiesgoCertificado.fromJson(e as Map<String, dynamic>)).toList(),
    certificados: j['certificados'] == null ? null : Map<String, dynamic>.from(j['certificados'] as Map),
    cargaPorResponsable: j['carga_por_responsable'] == null ? null : (j['carga_por_responsable'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    cargaPorOficina: j['carga_por_oficina'] == null ? null : (j['carga_por_oficina'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    indicadores: j['indicadores'] == null ? null : Map<String, dynamic>.from(j['indicadores'] as Map),
  );
  Map<String, dynamic> toJson() => {
    'generado_en': ?generadoEn,
    'hoy': ?hoy,
    if (ambito != null) 'ambito': ambito!.valor,
    'totales': ?totales,
    'hoy_lista': ?hoyLista,
    if (bloqueadas != null) 'bloqueadas': bloqueadas!.map((e) => e).toList(),
    if (traspasos != null) 'traspasos': traspasos!.map((e) => e.toJson()).toList(),
    if (riesgosCertificados != null) 'riesgos_certificados': riesgosCertificados!.map((e) => e.toJson()).toList(),
    'certificados': ?certificados,
    if (cargaPorResponsable != null) 'carga_por_responsable': cargaPorResponsable!.map((e) => e).toList(),
    if (cargaPorOficina != null) 'carga_por_oficina': cargaPorOficina!.map((e) => e).toList(),
    'indicadores': ?indicadores,
  };
  PanelFiscal copyWith({String? generadoEn, String? hoy, PanelFiscalAmbito? ambito, Map<String, dynamic>? totales, Map<String, dynamic>? hoyLista, List<Map<String, dynamic>>? bloqueadas, List<Traspaso>? traspasos, List<RiesgoCertificado>? riesgosCertificados, Map<String, dynamic>? certificados, List<Map<String, dynamic>>? cargaPorResponsable, List<Map<String, dynamic>>? cargaPorOficina, Map<String, dynamic>? indicadores, }) => PanelFiscal(generadoEn: generadoEn ?? this.generadoEn, hoy: hoy ?? this.hoy, ambito: ambito ?? this.ambito, totales: totales ?? this.totales, hoyLista: hoyLista ?? this.hoyLista, bloqueadas: bloqueadas ?? this.bloqueadas, traspasos: traspasos ?? this.traspasos, riesgosCertificados: riesgosCertificados ?? this.riesgosCertificados, certificados: certificados ?? this.certificados, cargaPorResponsable: cargaPorResponsable ?? this.cargaPorResponsable, cargaPorOficina: cargaPorOficina ?? this.cargaPorOficina, indicadores: indicadores ?? this.indicadores, );
  @override bool operator ==(Object other) => other is PanelFiscal && other.generadoEn == generadoEn && other.hoy == hoy && other.ambito == ambito && other.totales == totales && other.hoyLista == hoyLista && other.bloqueadas == bloqueadas && other.traspasos == traspasos && other.riesgosCertificados == riesgosCertificados && other.certificados == certificados && other.cargaPorResponsable == cargaPorResponsable && other.cargaPorOficina == cargaPorOficina && other.indicadores == indicadores;
  @override int get hashCode => Object.hashAll([generadoEn, hoy, ambito, totales, hoyLista, bloqueadas, traspasos, riesgosCertificados, certificados, cargaPorResponsable, cargaPorOficina, indicadores]);
}

class Papelera {
  final String? origen;
  final int? id;
  final String? texto;
  final String? papeleraEn;
  const Papelera({this.origen, this.id, this.texto, this.papeleraEn, });
  factory Papelera.fromJson(Map<String, dynamic> j) => Papelera(
    origen: j['origen'] == null ? null : j['origen'] as String,
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    texto: j['texto'] == null ? null : j['texto'] as String,
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'origen': ?origen,
    'id': ?id,
    'texto': ?texto,
    'papelera_en': ?papeleraEn,
  };
  Papelera copyWith({String? origen, int? id, String? texto, String? papeleraEn, }) => Papelera(origen: origen ?? this.origen, id: id ?? this.id, texto: texto ?? this.texto, papeleraEn: papeleraEn ?? this.papeleraEn, );
  @override bool operator ==(Object other) => other is Papelera && other.origen == origen && other.id == id && other.texto == texto && other.papeleraEn == papeleraEn;
  @override int get hashCode => Object.hashAll([origen, id, texto, papeleraEn]);
}

class ParteAsunto {
  final int? id;
  final String? rol;
  final String? nombre;
  final String? nif;
  final String? notas;
  const ParteAsunto({this.id, this.rol, this.nombre, this.nif, this.notas, });
  factory ParteAsunto.fromJson(Map<String, dynamic> j) => ParteAsunto(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    rol: j['rol'] == null ? null : j['rol'] as String,
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    nif: j['nif'] == null ? null : j['nif'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'rol': ?rol,
    'nombre': ?nombre,
    'nif': ?nif,
    'notas': ?notas,
  };
  ParteAsunto copyWith({int? id, String? rol, String? nombre, String? nif, String? notas, }) => ParteAsunto(id: id ?? this.id, rol: rol ?? this.rol, nombre: nombre ?? this.nombre, nif: nif ?? this.nif, notas: notas ?? this.notas, );
  @override bool operator ==(Object other) => other is ParteAsunto && other.id == id && other.rol == rol && other.nombre == nombre && other.nif == nif && other.notas == notas;
  @override int get hashCode => Object.hashAll([id, rol, nombre, nif, notas]);
}

class Perfil {
  final String? nombreMostrado;
  final bool? tieneAvatar;
  final String? avatarUrl;
  final Apariencia? apariencia;
  const Perfil({this.nombreMostrado, this.tieneAvatar, this.avatarUrl, this.apariencia, });
  factory Perfil.fromJson(Map<String, dynamic> j) => Perfil(
    nombreMostrado: j['nombre_mostrado'] == null ? null : j['nombre_mostrado'] as String,
    tieneAvatar: j['tiene_avatar'] == null ? null : _aBool(j['tiene_avatar']),
    avatarUrl: j['avatar_url'] == null ? null : j['avatar_url'] as String,
    apariencia: j['apariencia'] == null ? null : Apariencia.fromJson(j['apariencia'] as Map<String, dynamic>),
  );
  Map<String, dynamic> toJson() => {
    'nombre_mostrado': ?nombreMostrado,
    'tiene_avatar': ?tieneAvatar,
    'avatar_url': ?avatarUrl,
    if (apariencia != null) 'apariencia': apariencia!.toJson(),
  };
  Perfil copyWith({String? nombreMostrado, bool? tieneAvatar, String? avatarUrl, Apariencia? apariencia, }) => Perfil(nombreMostrado: nombreMostrado ?? this.nombreMostrado, tieneAvatar: tieneAvatar ?? this.tieneAvatar, avatarUrl: avatarUrl ?? this.avatarUrl, apariencia: apariencia ?? this.apariencia, );
  @override bool operator ==(Object other) => other is Perfil && other.nombreMostrado == nombreMostrado && other.tieneAvatar == tieneAvatar && other.avatarUrl == avatarUrl && other.apariencia == apariencia;
  @override int get hashCode => Object.hashAll([nombreMostrado, tieneAvatar, avatarUrl, apariencia]);
}

class PlantillaCorreo {
  final int id;
  final int? usuarioId;
  final String? nombre;
  final String? asunto;
  final String? cuerpo;
  final String? creadaEn;
  final String? modelo;
  const PlantillaCorreo({required this.id, this.usuarioId, this.nombre, this.asunto, this.cuerpo, this.creadaEn, this.modelo, });
  factory PlantillaCorreo.fromJson(Map<String, dynamic> j) => PlantillaCorreo(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    cuerpo: j['cuerpo'] == null ? null : j['cuerpo'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    modelo: j['modelo'] == null ? null : j['modelo'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'nombre': ?nombre,
    'asunto': ?asunto,
    'cuerpo': ?cuerpo,
    'creada_en': ?creadaEn,
    'modelo': ?modelo,
  };
  PlantillaCorreo copyWith({int? id, int? usuarioId, String? nombre, String? asunto, String? cuerpo, String? creadaEn, String? modelo, }) => PlantillaCorreo(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, nombre: nombre ?? this.nombre, asunto: asunto ?? this.asunto, cuerpo: cuerpo ?? this.cuerpo, creadaEn: creadaEn ?? this.creadaEn, modelo: modelo ?? this.modelo, );
  @override bool operator ==(Object other) => other is PlantillaCorreo && other.id == id && other.usuarioId == usuarioId && other.nombre == nombre && other.asunto == asunto && other.cuerpo == cuerpo && other.creadaEn == creadaEn && other.modelo == modelo;
  @override int get hashCode => Object.hashAll([id, usuarioId, nombre, asunto, cuerpo, creadaEn, modelo]);
}

class PlantillaTareas {
  final int id;
  final int? usuarioId;
  final String? nombre;
  final String? descripcion;
  final int? compartida;
  final String? creadaEn;
  final List<Map<String, dynamic>>? items;
  const PlantillaTareas({required this.id, this.usuarioId, this.nombre, this.descripcion, this.compartida, this.creadaEn, this.items, });
  factory PlantillaTareas.fromJson(Map<String, dynamic> j) => PlantillaTareas(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    descripcion: j['descripcion'] == null ? null : j['descripcion'] as String,
    compartida: j['compartida'] == null ? null : (j['compartida'] as num).toInt(),
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    items: j['items'] == null ? null : (j['items'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'nombre': ?nombre,
    'descripcion': ?descripcion,
    'compartida': ?compartida,
    'creada_en': ?creadaEn,
    if (items != null) 'items': items!.map((e) => e).toList(),
  };
  PlantillaTareas copyWith({int? id, int? usuarioId, String? nombre, String? descripcion, int? compartida, String? creadaEn, List<Map<String, dynamic>>? items, }) => PlantillaTareas(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, nombre: nombre ?? this.nombre, descripcion: descripcion ?? this.descripcion, compartida: compartida ?? this.compartida, creadaEn: creadaEn ?? this.creadaEn, items: items ?? this.items, );
  @override bool operator ==(Object other) => other is PlantillaTareas && other.id == id && other.usuarioId == usuarioId && other.nombre == nombre && other.descripcion == descripcion && other.compartida == compartida && other.creadaEn == creadaEn && other.items == items;
  @override int get hashCode => Object.hashAll([id, usuarioId, nombre, descripcion, compartida, creadaEn, items]);
}

class PreferenciasCorreo {
  final int? usuarioId;
  final String? densidad;
  final int? marcarLeidoAutomatico;
  final int? limiteMensajes;
  final int? deshacerSegundos;
  final String? tamLetra;
  final String? disposicion;
  final int? anchoLista;
  final int? vistaPrevia;
  const PreferenciasCorreo({this.usuarioId, this.densidad, this.marcarLeidoAutomatico, this.limiteMensajes, this.deshacerSegundos, this.tamLetra, this.disposicion, this.anchoLista, this.vistaPrevia, });
  factory PreferenciasCorreo.fromJson(Map<String, dynamic> j) => PreferenciasCorreo(
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    densidad: j['densidad'] == null ? null : j['densidad'] as String,
    marcarLeidoAutomatico: j['marcar_leido_automatico'] == null ? null : (j['marcar_leido_automatico'] as num).toInt(),
    limiteMensajes: j['limite_mensajes'] == null ? null : (j['limite_mensajes'] as num).toInt(),
    deshacerSegundos: j['deshacer_segundos'] == null ? null : (j['deshacer_segundos'] as num).toInt(),
    tamLetra: j['tam_letra'] == null ? null : j['tam_letra'] as String,
    disposicion: j['disposicion'] == null ? null : j['disposicion'] as String,
    anchoLista: j['ancho_lista'] == null ? null : (j['ancho_lista'] as num).toInt(),
    vistaPrevia: j['vista_previa'] == null ? null : (j['vista_previa'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'usuario_id': ?usuarioId,
    'densidad': ?densidad,
    'marcar_leido_automatico': ?marcarLeidoAutomatico,
    'limite_mensajes': ?limiteMensajes,
    'deshacer_segundos': ?deshacerSegundos,
    'tam_letra': ?tamLetra,
    'disposicion': ?disposicion,
    'ancho_lista': ?anchoLista,
    'vista_previa': ?vistaPrevia,
  };
  PreferenciasCorreo copyWith({int? usuarioId, String? densidad, int? marcarLeidoAutomatico, int? limiteMensajes, int? deshacerSegundos, String? tamLetra, String? disposicion, int? anchoLista, int? vistaPrevia, }) => PreferenciasCorreo(usuarioId: usuarioId ?? this.usuarioId, densidad: densidad ?? this.densidad, marcarLeidoAutomatico: marcarLeidoAutomatico ?? this.marcarLeidoAutomatico, limiteMensajes: limiteMensajes ?? this.limiteMensajes, deshacerSegundos: deshacerSegundos ?? this.deshacerSegundos, tamLetra: tamLetra ?? this.tamLetra, disposicion: disposicion ?? this.disposicion, anchoLista: anchoLista ?? this.anchoLista, vistaPrevia: vistaPrevia ?? this.vistaPrevia, );
  @override bool operator ==(Object other) => other is PreferenciasCorreo && other.usuarioId == usuarioId && other.densidad == densidad && other.marcarLeidoAutomatico == marcarLeidoAutomatico && other.limiteMensajes == limiteMensajes && other.deshacerSegundos == deshacerSegundos && other.tamLetra == tamLetra && other.disposicion == disposicion && other.anchoLista == anchoLista && other.vistaPrevia == vistaPrevia;
  @override int get hashCode => Object.hashAll([usuarioId, densidad, marcarLeidoAutomatico, limiteMensajes, deshacerSegundos, tamLetra, disposicion, anchoLista, vistaPrevia]);
}

class PreferenciasIA {
  final int? usuarioId;
  final String? modelo;
  final int? modoAutonomo;
  final String? proveedorLocal;
  final String? modeloLocal;
  final int? soloLectura;
  final int? apiKeysConfiguradas;
  const PreferenciasIA({this.usuarioId, this.modelo, this.modoAutonomo, this.proveedorLocal, this.modeloLocal, this.soloLectura, this.apiKeysConfiguradas, });
  factory PreferenciasIA.fromJson(Map<String, dynamic> j) => PreferenciasIA(
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    modelo: j['modelo'] == null ? null : j['modelo'] as String,
    modoAutonomo: j['modo_autonomo'] == null ? null : (j['modo_autonomo'] as num).toInt(),
    proveedorLocal: j['proveedor_local'] == null ? null : j['proveedor_local'] as String,
    modeloLocal: j['modelo_local'] == null ? null : j['modelo_local'] as String,
    soloLectura: j['solo_lectura'] == null ? null : (j['solo_lectura'] as num).toInt(),
    apiKeysConfiguradas: j['api_keys_configuradas'] == null ? null : (j['api_keys_configuradas'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'usuario_id': ?usuarioId,
    'modelo': ?modelo,
    'modo_autonomo': ?modoAutonomo,
    'proveedor_local': ?proveedorLocal,
    'modelo_local': ?modeloLocal,
    'solo_lectura': ?soloLectura,
    'api_keys_configuradas': ?apiKeysConfiguradas,
  };
  PreferenciasIA copyWith({int? usuarioId, String? modelo, int? modoAutonomo, String? proveedorLocal, String? modeloLocal, int? soloLectura, int? apiKeysConfiguradas, }) => PreferenciasIA(usuarioId: usuarioId ?? this.usuarioId, modelo: modelo ?? this.modelo, modoAutonomo: modoAutonomo ?? this.modoAutonomo, proveedorLocal: proveedorLocal ?? this.proveedorLocal, modeloLocal: modeloLocal ?? this.modeloLocal, soloLectura: soloLectura ?? this.soloLectura, apiKeysConfiguradas: apiKeysConfiguradas ?? this.apiKeysConfiguradas, );
  @override bool operator ==(Object other) => other is PreferenciasIA && other.usuarioId == usuarioId && other.modelo == modelo && other.modoAutonomo == modoAutonomo && other.proveedorLocal == proveedorLocal && other.modeloLocal == modeloLocal && other.soloLectura == soloLectura && other.apiKeysConfiguradas == apiKeysConfiguradas;
  @override int get hashCode => Object.hashAll([usuarioId, modelo, modoAutonomo, proveedorLocal, modeloLocal, soloLectura, apiKeysConfiguradas]);
}

class Presentacion {
  final int? id;
  final PresentacionEstado? estado;
  const Presentacion({this.id, this.estado, });
  factory Presentacion.fromJson(Map<String, dynamic> j) => Presentacion(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    estado: j['estado'] == null ? null : PresentacionEstado.desde(j['estado'] as String),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    if (estado != null) 'estado': estado!.valor,
  };
  Presentacion copyWith({int? id, PresentacionEstado? estado, }) => Presentacion(id: id ?? this.id, estado: estado ?? this.estado, );
  @override bool operator ==(Object other) => other is Presentacion && other.id == id && other.estado == estado;
  @override int get hashCode => Object.hashAll([id, estado]);
}

class ProvisionAsunto {
  final String? expediente;
  final String? provisiones;
  final String? suplidos;
  final String? honorarios;
  final String? devoluciones;
  final String? saldo;
  final int? saldoCentimos;
  final String? provisionMinima;
  final bool? porDebajoDeLaMinima;
  final List<Map<String, dynamic>>? ultimosMovimientos;
  const ProvisionAsunto({this.expediente, this.provisiones, this.suplidos, this.honorarios, this.devoluciones, this.saldo, this.saldoCentimos, this.provisionMinima, this.porDebajoDeLaMinima, this.ultimosMovimientos, });
  factory ProvisionAsunto.fromJson(Map<String, dynamic> j) => ProvisionAsunto(
    expediente: j['expediente'] == null ? null : j['expediente'] as String,
    provisiones: j['provisiones'] == null ? null : j['provisiones'] as String,
    suplidos: j['suplidos'] == null ? null : j['suplidos'] as String,
    honorarios: j['honorarios'] == null ? null : j['honorarios'] as String,
    devoluciones: j['devoluciones'] == null ? null : j['devoluciones'] as String,
    saldo: j['saldo'] == null ? null : j['saldo'] as String,
    saldoCentimos: j['saldo_centimos'] == null ? null : (j['saldo_centimos'] as num).toInt(),
    provisionMinima: j['provision_minima'] == null ? null : j['provision_minima'] as String,
    porDebajoDeLaMinima: j['por_debajo_de_la_minima'] == null ? null : _aBool(j['por_debajo_de_la_minima']),
    ultimosMovimientos: j['ultimos_movimientos'] == null ? null : (j['ultimos_movimientos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'expediente': ?expediente,
    'provisiones': ?provisiones,
    'suplidos': ?suplidos,
    'honorarios': ?honorarios,
    'devoluciones': ?devoluciones,
    'saldo': ?saldo,
    'saldo_centimos': ?saldoCentimos,
    'provision_minima': ?provisionMinima,
    'por_debajo_de_la_minima': ?porDebajoDeLaMinima,
    if (ultimosMovimientos != null) 'ultimos_movimientos': ultimosMovimientos!.map((e) => e).toList(),
  };
  ProvisionAsunto copyWith({String? expediente, String? provisiones, String? suplidos, String? honorarios, String? devoluciones, String? saldo, int? saldoCentimos, String? provisionMinima, bool? porDebajoDeLaMinima, List<Map<String, dynamic>>? ultimosMovimientos, }) => ProvisionAsunto(expediente: expediente ?? this.expediente, provisiones: provisiones ?? this.provisiones, suplidos: suplidos ?? this.suplidos, honorarios: honorarios ?? this.honorarios, devoluciones: devoluciones ?? this.devoluciones, saldo: saldo ?? this.saldo, saldoCentimos: saldoCentimos ?? this.saldoCentimos, provisionMinima: provisionMinima ?? this.provisionMinima, porDebajoDeLaMinima: porDebajoDeLaMinima ?? this.porDebajoDeLaMinima, ultimosMovimientos: ultimosMovimientos ?? this.ultimosMovimientos, );
  @override bool operator ==(Object other) => other is ProvisionAsunto && other.expediente == expediente && other.provisiones == provisiones && other.suplidos == suplidos && other.honorarios == honorarios && other.devoluciones == devoluciones && other.saldo == saldo && other.saldoCentimos == saldoCentimos && other.provisionMinima == provisionMinima && other.porDebajoDeLaMinima == porDebajoDeLaMinima && other.ultimosMovimientos == ultimosMovimientos;
  @override int get hashCode => Object.hashAll([expediente, provisiones, suplidos, honorarios, devoluciones, saldo, saldoCentimos, provisionMinima, porDebajoDeLaMinima, ultimosMovimientos]);
}

class Proyecto {
  final int id;
  final int? usuarioId;
  final String? nombre;
  final String? color;
  final String? creadaEn;
  final String? papeleraEn;
  final int? orden;
  final int? favorito;
  final String? icono;
  final int? proyCompartido;
  final String? proyEstado;
  final String? proyDescripcion;
  final String? proyFechaObjetivo;
  final int? proyResponsableId;
  final int? proyClienteId;
  const Proyecto({required this.id, this.usuarioId, this.nombre, this.color, this.creadaEn, this.papeleraEn, this.orden, this.favorito, this.icono, this.proyCompartido, this.proyEstado, this.proyDescripcion, this.proyFechaObjetivo, this.proyResponsableId, this.proyClienteId, });
  factory Proyecto.fromJson(Map<String, dynamic> j) => Proyecto(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    color: j['color'] == null ? null : j['color'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
    orden: j['orden'] == null ? null : (j['orden'] as num).toInt(),
    favorito: j['favorito'] == null ? null : (j['favorito'] as num).toInt(),
    icono: j['icono'] == null ? null : j['icono'] as String,
    proyCompartido: j['proy_compartido'] == null ? null : (j['proy_compartido'] as num).toInt(),
    proyEstado: j['proy_estado'] == null ? null : j['proy_estado'] as String,
    proyDescripcion: j['proy_descripcion'] == null ? null : j['proy_descripcion'] as String,
    proyFechaObjetivo: j['proy_fecha_objetivo'] == null ? null : j['proy_fecha_objetivo'] as String,
    proyResponsableId: j['proy_responsable_id'] == null ? null : (j['proy_responsable_id'] as num).toInt(),
    proyClienteId: j['proy_cliente_id'] == null ? null : (j['proy_cliente_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'nombre': ?nombre,
    'color': ?color,
    'creada_en': ?creadaEn,
    'papelera_en': ?papeleraEn,
    'orden': ?orden,
    'favorito': ?favorito,
    'icono': ?icono,
    'proy_compartido': ?proyCompartido,
    'proy_estado': ?proyEstado,
    'proy_descripcion': ?proyDescripcion,
    'proy_fecha_objetivo': ?proyFechaObjetivo,
    'proy_responsable_id': ?proyResponsableId,
    'proy_cliente_id': ?proyClienteId,
  };
  Proyecto copyWith({int? id, int? usuarioId, String? nombre, String? color, String? creadaEn, String? papeleraEn, int? orden, int? favorito, String? icono, int? proyCompartido, String? proyEstado, String? proyDescripcion, String? proyFechaObjetivo, int? proyResponsableId, int? proyClienteId, }) => Proyecto(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, nombre: nombre ?? this.nombre, color: color ?? this.color, creadaEn: creadaEn ?? this.creadaEn, papeleraEn: papeleraEn ?? this.papeleraEn, orden: orden ?? this.orden, favorito: favorito ?? this.favorito, icono: icono ?? this.icono, proyCompartido: proyCompartido ?? this.proyCompartido, proyEstado: proyEstado ?? this.proyEstado, proyDescripcion: proyDescripcion ?? this.proyDescripcion, proyFechaObjetivo: proyFechaObjetivo ?? this.proyFechaObjetivo, proyResponsableId: proyResponsableId ?? this.proyResponsableId, proyClienteId: proyClienteId ?? this.proyClienteId, );
  @override bool operator ==(Object other) => other is Proyecto && other.id == id && other.usuarioId == usuarioId && other.nombre == nombre && other.color == color && other.creadaEn == creadaEn && other.papeleraEn == papeleraEn && other.orden == orden && other.favorito == favorito && other.icono == icono && other.proyCompartido == proyCompartido && other.proyEstado == proyEstado && other.proyDescripcion == proyDescripcion && other.proyFechaObjetivo == proyFechaObjetivo && other.proyResponsableId == proyResponsableId && other.proyClienteId == proyClienteId;
  @override int get hashCode => Object.hashAll([id, usuarioId, nombre, color, creadaEn, papeleraEn, orden, favorito, icono, proyCompartido, proyEstado, proyDescripcion, proyFechaObjetivo, proyResponsableId, proyClienteId]);
}

class PuntoLista {
  final int? id;
  final bool? hecho;
  const PuntoLista({this.id, this.hecho, });
  factory PuntoLista.fromJson(Map<String, dynamic> j) => PuntoLista(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    hecho: j['hecho'] == null ? null : _aBool(j['hecho']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'hecho': ?hecho,
  };
  PuntoLista copyWith({int? id, bool? hecho, }) => PuntoLista(id: id ?? this.id, hecho: hecho ?? this.hecho, );
  @override bool operator ==(Object other) => other is PuntoLista && other.id == id && other.hecho == hecho;
  @override int get hashCode => Object.hashAll([id, hecho]);
}

class RecordatorioTarea {
  final int id;
  final int? tareaId;
  final int? usuarioId;
  final String? avisarEn;
  final String? canales;
  final String? enviadoEn;
  final String? creadoEn;
  const RecordatorioTarea({required this.id, this.tareaId, this.usuarioId, this.avisarEn, this.canales, this.enviadoEn, this.creadoEn, });
  factory RecordatorioTarea.fromJson(Map<String, dynamic> j) => RecordatorioTarea(
    id: (j['id'] as num).toInt(),
    tareaId: j['tarea_id'] == null ? null : (j['tarea_id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    avisarEn: j['avisar_en'] == null ? null : j['avisar_en'] as String,
    canales: j['canales'] == null ? null : j['canales'] as String,
    enviadoEn: j['enviado_en'] == null ? null : j['enviado_en'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tarea_id': ?tareaId,
    'usuario_id': ?usuarioId,
    'avisar_en': ?avisarEn,
    'canales': ?canales,
    'enviado_en': ?enviadoEn,
    'creado_en': ?creadoEn,
  };
  RecordatorioTarea copyWith({int? id, int? tareaId, int? usuarioId, String? avisarEn, String? canales, String? enviadoEn, String? creadoEn, }) => RecordatorioTarea(id: id ?? this.id, tareaId: tareaId ?? this.tareaId, usuarioId: usuarioId ?? this.usuarioId, avisarEn: avisarEn ?? this.avisarEn, canales: canales ?? this.canales, enviadoEn: enviadoEn ?? this.enviadoEn, creadoEn: creadoEn ?? this.creadoEn, );
  @override bool operator ==(Object other) => other is RecordatorioTarea && other.id == id && other.tareaId == tareaId && other.usuarioId == usuarioId && other.avisarEn == avisarEn && other.canales == canales && other.enviadoEn == enviadoEn && other.creadoEn == creadoEn;
  @override int get hashCode => Object.hashAll([id, tareaId, usuarioId, avisarEn, canales, enviadoEn, creadoEn]);
}

class ReglaCategoriaCorreo {
  final int id;
  final int? usuarioId;
  final String? remitentePatron;
  final int? categoriaId;
  final String? creadaEn;
  const ReglaCategoriaCorreo({required this.id, this.usuarioId, this.remitentePatron, this.categoriaId, this.creadaEn, });
  factory ReglaCategoriaCorreo.fromJson(Map<String, dynamic> j) => ReglaCategoriaCorreo(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    remitentePatron: j['remitente_patron'] == null ? null : j['remitente_patron'] as String,
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'remitente_patron': ?remitentePatron,
    'categoria_id': ?categoriaId,
    'creada_en': ?creadaEn,
  };
  ReglaCategoriaCorreo copyWith({int? id, int? usuarioId, String? remitentePatron, int? categoriaId, String? creadaEn, }) => ReglaCategoriaCorreo(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, remitentePatron: remitentePatron ?? this.remitentePatron, categoriaId: categoriaId ?? this.categoriaId, creadaEn: creadaEn ?? this.creadaEn, );
  @override bool operator ==(Object other) => other is ReglaCategoriaCorreo && other.id == id && other.usuarioId == usuarioId && other.remitentePatron == remitentePatron && other.categoriaId == categoriaId && other.creadaEn == creadaEn;
  @override int get hashCode => Object.hashAll([id, usuarioId, remitentePatron, categoriaId, creadaEn]);
}

class ReglaRecurrente {
  final int id;
  final int? usuarioId;
  final int? categoriaId;
  final String? asunto;
  final String? periodicidad;
  final int? dia;
  final int? mes;
  final int? activa;
  final String? creadoEn;
  const ReglaRecurrente({required this.id, this.usuarioId, this.categoriaId, this.asunto, this.periodicidad, this.dia, this.mes, this.activa, this.creadoEn, });
  factory ReglaRecurrente.fromJson(Map<String, dynamic> j) => ReglaRecurrente(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    periodicidad: j['periodicidad'] == null ? null : j['periodicidad'] as String,
    dia: j['dia'] == null ? null : (j['dia'] as num).toInt(),
    mes: j['mes'] == null ? null : (j['mes'] as num).toInt(),
    activa: j['activa'] == null ? null : (j['activa'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'categoria_id': ?categoriaId,
    'asunto': ?asunto,
    'periodicidad': ?periodicidad,
    'dia': ?dia,
    'mes': ?mes,
    'activa': ?activa,
    'creado_en': ?creadoEn,
  };
  ReglaRecurrente copyWith({int? id, int? usuarioId, int? categoriaId, String? asunto, String? periodicidad, int? dia, int? mes, int? activa, String? creadoEn, }) => ReglaRecurrente(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, categoriaId: categoriaId ?? this.categoriaId, asunto: asunto ?? this.asunto, periodicidad: periodicidad ?? this.periodicidad, dia: dia ?? this.dia, mes: mes ?? this.mes, activa: activa ?? this.activa, creadoEn: creadoEn ?? this.creadoEn, );
  @override bool operator ==(Object other) => other is ReglaRecurrente && other.id == id && other.usuarioId == usuarioId && other.categoriaId == categoriaId && other.asunto == asunto && other.periodicidad == periodicidad && other.dia == dia && other.mes == mes && other.activa == activa && other.creadoEn == creadoEn;
  @override int get hashCode => Object.hashAll([id, usuarioId, categoriaId, asunto, periodicidad, dia, mes, activa, creadoEn]);
}

class ReglaVencimiento {
  final int id;
  final int? usuarioId;
  final int? tenantId;
  final String? modelo;
  final String? asunto;
  final int? crearDiasAntes;
  final int? venceDiasAntes;
  final int? categoriaId;
  final int? asignarResponsable;
  final int? estimacionMin;
  final String? prioridad;
  final int? activa;
  final String? creadaEn;
  final int? generadas;
  const ReglaVencimiento({required this.id, this.usuarioId, this.tenantId, this.modelo, this.asunto, this.crearDiasAntes, this.venceDiasAntes, this.categoriaId, this.asignarResponsable, this.estimacionMin, this.prioridad, this.activa, this.creadaEn, this.generadas, });
  factory ReglaVencimiento.fromJson(Map<String, dynamic> j) => ReglaVencimiento(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    modelo: j['modelo'] == null ? null : j['modelo'] as String,
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    crearDiasAntes: j['crear_dias_antes'] == null ? null : (j['crear_dias_antes'] as num).toInt(),
    venceDiasAntes: j['vence_dias_antes'] == null ? null : (j['vence_dias_antes'] as num).toInt(),
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    asignarResponsable: j['asignar_responsable'] == null ? null : (j['asignar_responsable'] as num).toInt(),
    estimacionMin: j['estimacion_min'] == null ? null : (j['estimacion_min'] as num).toInt(),
    prioridad: j['prioridad'] == null ? null : j['prioridad'] as String,
    activa: j['activa'] == null ? null : (j['activa'] as num).toInt(),
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    generadas: j['generadas'] == null ? null : (j['generadas'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'tenant_id': ?tenantId,
    'modelo': ?modelo,
    'asunto': ?asunto,
    'crear_dias_antes': ?crearDiasAntes,
    'vence_dias_antes': ?venceDiasAntes,
    'categoria_id': ?categoriaId,
    'asignar_responsable': ?asignarResponsable,
    'estimacion_min': ?estimacionMin,
    'prioridad': ?prioridad,
    'activa': ?activa,
    'creada_en': ?creadaEn,
    'generadas': ?generadas,
  };
  ReglaVencimiento copyWith({int? id, int? usuarioId, int? tenantId, String? modelo, String? asunto, int? crearDiasAntes, int? venceDiasAntes, int? categoriaId, int? asignarResponsable, int? estimacionMin, String? prioridad, int? activa, String? creadaEn, int? generadas, }) => ReglaVencimiento(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, tenantId: tenantId ?? this.tenantId, modelo: modelo ?? this.modelo, asunto: asunto ?? this.asunto, crearDiasAntes: crearDiasAntes ?? this.crearDiasAntes, venceDiasAntes: venceDiasAntes ?? this.venceDiasAntes, categoriaId: categoriaId ?? this.categoriaId, asignarResponsable: asignarResponsable ?? this.asignarResponsable, estimacionMin: estimacionMin ?? this.estimacionMin, prioridad: prioridad ?? this.prioridad, activa: activa ?? this.activa, creadaEn: creadaEn ?? this.creadaEn, generadas: generadas ?? this.generadas, );
  @override bool operator ==(Object other) => other is ReglaVencimiento && other.id == id && other.usuarioId == usuarioId && other.tenantId == tenantId && other.modelo == modelo && other.asunto == asunto && other.crearDiasAntes == crearDiasAntes && other.venceDiasAntes == venceDiasAntes && other.categoriaId == categoriaId && other.asignarResponsable == asignarResponsable && other.estimacionMin == estimacionMin && other.prioridad == prioridad && other.activa == activa && other.creadaEn == creadaEn && other.generadas == generadas;
  @override int get hashCode => Object.hashAll([id, usuarioId, tenantId, modelo, asunto, crearDiasAntes, venceDiasAntes, categoriaId, asignarResponsable, estimacionMin, prioridad, activa, creadaEn, generadas]);
}

class RemitenteConfiable {
  final int id;
  final int? usuarioId;
  final String? direccion;
  final String? creadaEn;
  const RemitenteConfiable({required this.id, this.usuarioId, this.direccion, this.creadaEn, });
  factory RemitenteConfiable.fromJson(Map<String, dynamic> j) => RemitenteConfiable(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    direccion: j['direccion'] == null ? null : j['direccion'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'direccion': ?direccion,
    'creada_en': ?creadaEn,
  };
  RemitenteConfiable copyWith({int? id, int? usuarioId, String? direccion, String? creadaEn, }) => RemitenteConfiable(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, direccion: direccion ?? this.direccion, creadaEn: creadaEn ?? this.creadaEn, );
  @override bool operator ==(Object other) => other is RemitenteConfiable && other.id == id && other.usuarioId == usuarioId && other.direccion == direccion && other.creadaEn == creadaEn;
  @override int get hashCode => Object.hashAll([id, usuarioId, direccion, creadaEn]);
}

class ResponsableAsignado {
  final int? clienteId;
  final int? responsableId;
  const ResponsableAsignado({this.clienteId, this.responsableId, });
  factory ResponsableAsignado.fromJson(Map<String, dynamic> j) => ResponsableAsignado(
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    responsableId: j['responsable_id'] == null ? null : (j['responsable_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'cliente_id': ?clienteId,
    'responsable_id': ?responsableId,
  };
  ResponsableAsignado copyWith({int? clienteId, int? responsableId, }) => ResponsableAsignado(clienteId: clienteId ?? this.clienteId, responsableId: responsableId ?? this.responsableId, );
  @override bool operator ==(Object other) => other is ResponsableAsignado && other.clienteId == clienteId && other.responsableId == responsableId;
  @override int get hashCode => Object.hashAll([clienteId, responsableId]);
}

class RespuestaAlCliente {
  final int? id;
  final int? clienteFiscalId;
  final bool? clienteAvisadoPorCorreo;
  const RespuestaAlCliente({this.id, this.clienteFiscalId, this.clienteAvisadoPorCorreo, });
  factory RespuestaAlCliente.fromJson(Map<String, dynamic> j) => RespuestaAlCliente(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    clienteAvisadoPorCorreo: j['cliente_avisado_por_correo'] == null ? null : _aBool(j['cliente_avisado_por_correo']),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'cliente_fiscal_id': ?clienteFiscalId,
    'cliente_avisado_por_correo': ?clienteAvisadoPorCorreo,
  };
  RespuestaAlCliente copyWith({int? id, int? clienteFiscalId, bool? clienteAvisadoPorCorreo, }) => RespuestaAlCliente(id: id ?? this.id, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, clienteAvisadoPorCorreo: clienteAvisadoPorCorreo ?? this.clienteAvisadoPorCorreo, );
  @override bool operator ==(Object other) => other is RespuestaAlCliente && other.id == id && other.clienteFiscalId == clienteFiscalId && other.clienteAvisadoPorCorreo == clienteAvisadoPorCorreo;
  @override int get hashCode => Object.hashAll([id, clienteFiscalId, clienteAvisadoPorCorreo]);
}

class RespuestaIA {
  final List<MensajeIA>? mensajesNuevos;
  final Map<String, dynamic>? pendiente;
  const RespuestaIA({this.mensajesNuevos, this.pendiente, });
  factory RespuestaIA.fromJson(Map<String, dynamic> j) => RespuestaIA(
    mensajesNuevos: j['mensajes_nuevos'] == null ? null : (j['mensajes_nuevos'] as List).map((e) => MensajeIA.fromJson(e as Map<String, dynamic>)).toList(),
    pendiente: j['pendiente'] == null ? null : Map<String, dynamic>.from(j['pendiente'] as Map),
  );
  Map<String, dynamic> toJson() => {
    if (mensajesNuevos != null) 'mensajes_nuevos': mensajesNuevos!.map((e) => e.toJson()).toList(),
    'pendiente': ?pendiente,
  };
  RespuestaIA copyWith({List<MensajeIA>? mensajesNuevos, Map<String, dynamic>? pendiente, }) => RespuestaIA(mensajesNuevos: mensajesNuevos ?? this.mensajesNuevos, pendiente: pendiente ?? this.pendiente, );
  @override bool operator ==(Object other) => other is RespuestaIA && other.mensajesNuevos == mensajesNuevos && other.pendiente == pendiente;
  @override int get hashCode => Object.hashAll([mensajesNuevos, pendiente]);
}

class RespuestaJuridica {
  final int? runId;
  final RespuestaJuridicaStatus? status;
  final List<String>? facts;
  final List<String>? missingFacts;
  final String? conclusion;
  final List<Map<String, dynamic>>? claims;
  final List<Map<String, dynamic>>? citations;
  final List<String>? limitations;
  final List<String>? suggestedNextSteps;
  final Map<String, dynamic>? coverage;
  const RespuestaJuridica({this.runId, this.status, this.facts, this.missingFacts, this.conclusion, this.claims, this.citations, this.limitations, this.suggestedNextSteps, this.coverage, });
  factory RespuestaJuridica.fromJson(Map<String, dynamic> j) => RespuestaJuridica(
    runId: j['runId'] == null ? null : (j['runId'] as num).toInt(),
    status: j['status'] == null ? null : RespuestaJuridicaStatus.desde(j['status'] as String),
    facts: j['facts'] == null ? null : (j['facts'] as List).map((e) => e as String).toList(),
    missingFacts: j['missingFacts'] == null ? null : (j['missingFacts'] as List).map((e) => e as String).toList(),
    conclusion: j['conclusion'] == null ? null : j['conclusion'] as String,
    claims: j['claims'] == null ? null : (j['claims'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    citations: j['citations'] == null ? null : (j['citations'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    limitations: j['limitations'] == null ? null : (j['limitations'] as List).map((e) => e as String).toList(),
    suggestedNextSteps: j['suggestedNextSteps'] == null ? null : (j['suggestedNextSteps'] as List).map((e) => e as String).toList(),
    coverage: j['coverage'] == null ? null : Map<String, dynamic>.from(j['coverage'] as Map),
  );
  Map<String, dynamic> toJson() => {
    'runId': ?runId,
    if (status != null) 'status': status!.valor,
    if (facts != null) 'facts': facts!.map((e) => e).toList(),
    if (missingFacts != null) 'missingFacts': missingFacts!.map((e) => e).toList(),
    'conclusion': ?conclusion,
    if (claims != null) 'claims': claims!.map((e) => e).toList(),
    if (citations != null) 'citations': citations!.map((e) => e).toList(),
    if (limitations != null) 'limitations': limitations!.map((e) => e).toList(),
    if (suggestedNextSteps != null) 'suggestedNextSteps': suggestedNextSteps!.map((e) => e).toList(),
    'coverage': ?coverage,
  };
  RespuestaJuridica copyWith({int? runId, RespuestaJuridicaStatus? status, List<String>? facts, List<String>? missingFacts, String? conclusion, List<Map<String, dynamic>>? claims, List<Map<String, dynamic>>? citations, List<String>? limitations, List<String>? suggestedNextSteps, Map<String, dynamic>? coverage, }) => RespuestaJuridica(runId: runId ?? this.runId, status: status ?? this.status, facts: facts ?? this.facts, missingFacts: missingFacts ?? this.missingFacts, conclusion: conclusion ?? this.conclusion, claims: claims ?? this.claims, citations: citations ?? this.citations, limitations: limitations ?? this.limitations, suggestedNextSteps: suggestedNextSteps ?? this.suggestedNextSteps, coverage: coverage ?? this.coverage, );
  @override bool operator ==(Object other) => other is RespuestaJuridica && other.runId == runId && other.status == status && other.facts == facts && other.missingFacts == missingFacts && other.conclusion == conclusion && other.claims == claims && other.citations == citations && other.limitations == limitations && other.suggestedNextSteps == suggestedNextSteps && other.coverage == coverage;
  @override int get hashCode => Object.hashAll([runId, status, facts, missingFacts, conclusion, claims, citations, limitations, suggestedNextSteps, coverage]);
}

class ResultadoCambio {
  final bool? cambiado;
  const ResultadoCambio({this.cambiado, });
  factory ResultadoCambio.fromJson(Map<String, dynamic> j) => ResultadoCambio(
    cambiado: j['cambiado'] == null ? null : _aBool(j['cambiado']),
  );
  Map<String, dynamic> toJson() => {
    'cambiado': ?cambiado,
  };
  ResultadoCambio copyWith({bool? cambiado, }) => ResultadoCambio(cambiado: cambiado ?? this.cambiado, );
  @override bool operator ==(Object other) => other is ResultadoCambio && other.cambiado == cambiado;
  @override int get hashCode => Object.hashAll([cambiado]);
}

class ResultadoComentario {
  final List<String>? avisadas;
  final List<String>? sinAcceso;
  final List<String>? noEncontradas;
  const ResultadoComentario({this.avisadas, this.sinAcceso, this.noEncontradas, });
  factory ResultadoComentario.fromJson(Map<String, dynamic> j) => ResultadoComentario(
    avisadas: j['avisadas'] == null ? null : (j['avisadas'] as List).map((e) => e as String).toList(),
    sinAcceso: j['sin_acceso'] == null ? null : (j['sin_acceso'] as List).map((e) => e as String).toList(),
    noEncontradas: j['no_encontradas'] == null ? null : (j['no_encontradas'] as List).map((e) => e as String).toList(),
  );
  Map<String, dynamic> toJson() => {
    if (avisadas != null) 'avisadas': avisadas!.map((e) => e).toList(),
    if (sinAcceso != null) 'sin_acceso': sinAcceso!.map((e) => e).toList(),
    if (noEncontradas != null) 'no_encontradas': noEncontradas!.map((e) => e).toList(),
  };
  ResultadoComentario copyWith({List<String>? avisadas, List<String>? sinAcceso, List<String>? noEncontradas, }) => ResultadoComentario(avisadas: avisadas ?? this.avisadas, sinAcceso: sinAcceso ?? this.sinAcceso, noEncontradas: noEncontradas ?? this.noEncontradas, );
  @override bool operator ==(Object other) => other is ResultadoComentario && other.avisadas == avisadas && other.sinAcceso == sinAcceso && other.noEncontradas == noEncontradas;
  @override int get hashCode => Object.hashAll([avisadas, sinAcceso, noEncontradas]);
}

class ResultadoConflicto {
  final bool? hayConflicto;
  final List<Map<String, dynamic>>? hallazgos;
  const ResultadoConflicto({this.hayConflicto, this.hallazgos, });
  factory ResultadoConflicto.fromJson(Map<String, dynamic> j) => ResultadoConflicto(
    hayConflicto: j['hay_conflicto'] == null ? null : _aBool(j['hay_conflicto']),
    hallazgos: j['hallazgos'] == null ? null : (j['hallazgos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'hay_conflicto': ?hayConflicto,
    if (hallazgos != null) 'hallazgos': hallazgos!.map((e) => e).toList(),
  };
  ResultadoConflicto copyWith({bool? hayConflicto, List<Map<String, dynamic>>? hallazgos, }) => ResultadoConflicto(hayConflicto: hayConflicto ?? this.hayConflicto, hallazgos: hallazgos ?? this.hallazgos, );
  @override bool operator ==(Object other) => other is ResultadoConflicto && other.hayConflicto == hayConflicto && other.hallazgos == hallazgos;
  @override int get hashCode => Object.hashAll([hayConflicto, hallazgos]);
}

class ResultadoImportacion {
  final int? id;
  final bool? nuevo;
  final String? huella;
  const ResultadoImportacion({this.id, this.nuevo, this.huella, });
  factory ResultadoImportacion.fromJson(Map<String, dynamic> j) => ResultadoImportacion(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nuevo: j['nuevo'] == null ? null : _aBool(j['nuevo']),
    huella: j['huella'] == null ? null : j['huella'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nuevo': ?nuevo,
    'huella': ?huella,
  };
  ResultadoImportacion copyWith({int? id, bool? nuevo, String? huella, }) => ResultadoImportacion(id: id ?? this.id, nuevo: nuevo ?? this.nuevo, huella: huella ?? this.huella, );
  @override bool operator ==(Object other) => other is ResultadoImportacion && other.id == id && other.nuevo == nuevo && other.huella == huella;
  @override int get hashCode => Object.hashAll([id, nuevo, huella]);
}

class ResultadoLote {
  final int? ok;
  final int? fallos;
  const ResultadoLote({this.ok, this.fallos, });
  factory ResultadoLote.fromJson(Map<String, dynamic> j) => ResultadoLote(
    ok: j['ok'] == null ? null : (j['ok'] as num).toInt(),
    fallos: j['fallos'] == null ? null : (j['fallos'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'ok': ?ok,
    'fallos': ?fallos,
  };
  ResultadoLote copyWith({int? ok, int? fallos, }) => ResultadoLote(ok: ok ?? this.ok, fallos: fallos ?? this.fallos, );
  @override bool operator ==(Object other) => other is ResultadoLote && other.ok == ok && other.fallos == fallos;
  @override int get hashCode => Object.hashAll([ok, fallos]);
}

class ResultadoTransicion {
  final String? fase;
  final String? estado;
  final int? version;
  const ResultadoTransicion({this.fase, this.estado, this.version, });
  factory ResultadoTransicion.fromJson(Map<String, dynamic> j) => ResultadoTransicion(
    fase: j['fase'] == null ? null : j['fase'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'fase': ?fase,
    'estado': ?estado,
    'version': ?version,
  };
  ResultadoTransicion copyWith({String? fase, String? estado, int? version, }) => ResultadoTransicion(fase: fase ?? this.fase, estado: estado ?? this.estado, version: version ?? this.version, );
  @override bool operator ==(Object other) => other is ResultadoTransicion && other.fase == fase && other.estado == estado && other.version == version;
  @override int get hashCode => Object.hashAll([fase, estado, version]);
}

class ResumenAgencia {
  final int? inmueblesActivos;
  final Map<String, dynamic>? porFase;
  final int? demandasActivas;
  final List<Map<String, dynamic>>? visitasHoy;
  final int? visitasSemana;
  final List<Map<String, dynamic>>? ofertasAbiertas;
  final List<Map<String, dynamic>>? sinMovimiento14Dias;
  const ResumenAgencia({this.inmueblesActivos, this.porFase, this.demandasActivas, this.visitasHoy, this.visitasSemana, this.ofertasAbiertas, this.sinMovimiento14Dias, });
  factory ResumenAgencia.fromJson(Map<String, dynamic> j) => ResumenAgencia(
    inmueblesActivos: j['inmuebles_activos'] == null ? null : (j['inmuebles_activos'] as num).toInt(),
    porFase: j['por_fase'] == null ? null : Map<String, dynamic>.from(j['por_fase'] as Map),
    demandasActivas: j['demandas_activas'] == null ? null : (j['demandas_activas'] as num).toInt(),
    visitasHoy: j['visitas_hoy'] == null ? null : (j['visitas_hoy'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    visitasSemana: j['visitas_semana'] == null ? null : (j['visitas_semana'] as num).toInt(),
    ofertasAbiertas: j['ofertas_abiertas'] == null ? null : (j['ofertas_abiertas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    sinMovimiento14Dias: j['sin_movimiento_14_dias'] == null ? null : (j['sin_movimiento_14_dias'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'inmuebles_activos': ?inmueblesActivos,
    'por_fase': ?porFase,
    'demandas_activas': ?demandasActivas,
    if (visitasHoy != null) 'visitas_hoy': visitasHoy!.map((e) => e).toList(),
    'visitas_semana': ?visitasSemana,
    if (ofertasAbiertas != null) 'ofertas_abiertas': ofertasAbiertas!.map((e) => e).toList(),
    if (sinMovimiento14Dias != null) 'sin_movimiento_14_dias': sinMovimiento14Dias!.map((e) => e).toList(),
  };
  ResumenAgencia copyWith({int? inmueblesActivos, Map<String, dynamic>? porFase, int? demandasActivas, List<Map<String, dynamic>>? visitasHoy, int? visitasSemana, List<Map<String, dynamic>>? ofertasAbiertas, List<Map<String, dynamic>>? sinMovimiento14Dias, }) => ResumenAgencia(inmueblesActivos: inmueblesActivos ?? this.inmueblesActivos, porFase: porFase ?? this.porFase, demandasActivas: demandasActivas ?? this.demandasActivas, visitasHoy: visitasHoy ?? this.visitasHoy, visitasSemana: visitasSemana ?? this.visitasSemana, ofertasAbiertas: ofertasAbiertas ?? this.ofertasAbiertas, sinMovimiento14Dias: sinMovimiento14Dias ?? this.sinMovimiento14Dias, );
  @override bool operator ==(Object other) => other is ResumenAgencia && other.inmueblesActivos == inmueblesActivos && other.porFase == porFase && other.demandasActivas == demandasActivas && other.visitasHoy == visitasHoy && other.visitasSemana == visitasSemana && other.ofertasAbiertas == ofertasAbiertas && other.sinMovimiento14Dias == sinMovimiento14Dias;
  @override int get hashCode => Object.hashAll([inmueblesActivos, porFase, demandasActivas, visitasHoy, visitasSemana, ofertasAbiertas, sinMovimiento14Dias]);
}

class ResumenContabilidad {
  final Map<String, dynamic>? plan;
  final int? porRevisar;
  final int? porLeer;
  final int? paraExportar;
  final List<Map<String, dynamic>>? clientes;
  const ResumenContabilidad({this.plan, this.porRevisar, this.porLeer, this.paraExportar, this.clientes, });
  factory ResumenContabilidad.fromJson(Map<String, dynamic> j) => ResumenContabilidad(
    plan: j['plan'] == null ? null : Map<String, dynamic>.from(j['plan'] as Map),
    porRevisar: j['por_revisar'] == null ? null : (j['por_revisar'] as num).toInt(),
    porLeer: j['por_leer'] == null ? null : (j['por_leer'] as num).toInt(),
    paraExportar: j['para_exportar'] == null ? null : (j['para_exportar'] as num).toInt(),
    clientes: j['clientes'] == null ? null : (j['clientes'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'plan': ?plan,
    'por_revisar': ?porRevisar,
    'por_leer': ?porLeer,
    'para_exportar': ?paraExportar,
    if (clientes != null) 'clientes': clientes!.map((e) => e).toList(),
  };
  ResumenContabilidad copyWith({Map<String, dynamic>? plan, int? porRevisar, int? porLeer, int? paraExportar, List<Map<String, dynamic>>? clientes, }) => ResumenContabilidad(plan: plan ?? this.plan, porRevisar: porRevisar ?? this.porRevisar, porLeer: porLeer ?? this.porLeer, paraExportar: paraExportar ?? this.paraExportar, clientes: clientes ?? this.clientes, );
  @override bool operator ==(Object other) => other is ResumenContabilidad && other.plan == plan && other.porRevisar == porRevisar && other.porLeer == porLeer && other.paraExportar == paraExportar && other.clientes == clientes;
  @override int get hashCode => Object.hashAll([plan, porRevisar, porLeer, paraExportar, clientes]);
}

class ReunionComercial {
  final int? id;
  final String? titulo;
  final String? fecha;
  final ReunionComercialPlantilla? plantilla;
  final int? clienteId;
  final String? clienteNombre;
  final int? oportunidadId;
  final String? participantes;
  final String? notas;
  final String? autor;
  final String? creadaEn;
  final String? actualizadaEn;
  final bool? tieneTranscripcion;
  final Map<String, dynamic>? acta;
  const ReunionComercial({this.id, this.titulo, this.fecha, this.plantilla, this.clienteId, this.clienteNombre, this.oportunidadId, this.participantes, this.notas, this.autor, this.creadaEn, this.actualizadaEn, this.tieneTranscripcion, this.acta, });
  factory ReunionComercial.fromJson(Map<String, dynamic> j) => ReunionComercial(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
    plantilla: j['plantilla'] == null ? null : ReunionComercialPlantilla.desde(j['plantilla'] as String),
    clienteId: j['cliente_id'] == null ? null : (j['cliente_id'] as num).toInt(),
    clienteNombre: j['cliente_nombre'] == null ? null : j['cliente_nombre'] as String,
    oportunidadId: j['oportunidad_id'] == null ? null : (j['oportunidad_id'] as num).toInt(),
    participantes: j['participantes'] == null ? null : j['participantes'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    autor: j['autor'] == null ? null : j['autor'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    actualizadaEn: j['actualizada_en'] == null ? null : j['actualizada_en'] as String,
    tieneTranscripcion: j['tiene_transcripcion'] == null ? null : _aBool(j['tiene_transcripcion']),
    acta: j['acta'] == null ? null : Map<String, dynamic>.from(j['acta'] as Map),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'titulo': ?titulo,
    'fecha': ?fecha,
    if (plantilla != null) 'plantilla': plantilla!.valor,
    'cliente_id': ?clienteId,
    'cliente_nombre': ?clienteNombre,
    'oportunidad_id': ?oportunidadId,
    'participantes': ?participantes,
    'notas': ?notas,
    'autor': ?autor,
    'creada_en': ?creadaEn,
    'actualizada_en': ?actualizadaEn,
    'tiene_transcripcion': ?tieneTranscripcion,
    'acta': ?acta,
  };
  ReunionComercial copyWith({int? id, String? titulo, String? fecha, ReunionComercialPlantilla? plantilla, int? clienteId, String? clienteNombre, int? oportunidadId, String? participantes, String? notas, String? autor, String? creadaEn, String? actualizadaEn, bool? tieneTranscripcion, Map<String, dynamic>? acta, }) => ReunionComercial(id: id ?? this.id, titulo: titulo ?? this.titulo, fecha: fecha ?? this.fecha, plantilla: plantilla ?? this.plantilla, clienteId: clienteId ?? this.clienteId, clienteNombre: clienteNombre ?? this.clienteNombre, oportunidadId: oportunidadId ?? this.oportunidadId, participantes: participantes ?? this.participantes, notas: notas ?? this.notas, autor: autor ?? this.autor, creadaEn: creadaEn ?? this.creadaEn, actualizadaEn: actualizadaEn ?? this.actualizadaEn, tieneTranscripcion: tieneTranscripcion ?? this.tieneTranscripcion, acta: acta ?? this.acta, );
  @override bool operator ==(Object other) => other is ReunionComercial && other.id == id && other.titulo == titulo && other.fecha == fecha && other.plantilla == plantilla && other.clienteId == clienteId && other.clienteNombre == clienteNombre && other.oportunidadId == oportunidadId && other.participantes == participantes && other.notas == notas && other.autor == autor && other.creadaEn == creadaEn && other.actualizadaEn == actualizadaEn && other.tieneTranscripcion == tieneTranscripcion && other.acta == acta;
  @override int get hashCode => Object.hashAll([id, titulo, fecha, plantilla, clienteId, clienteNombre, oportunidadId, participantes, notas, autor, creadaEn, actualizadaEn, tieneTranscripcion, acta]);
}

class RevisionTarea {
  final int? id;
  final int? tareaId;
  final int? solicitadaPor;
  final int? revisorId;
  final RevisionTareaEstado? estado;
  final String? notaSolicitud;
  final String? notaResolucion;
  final String? solicitadaEn;
  final String? resueltaEn;
  final RevisionTareaModo? modo;
  final int? turno;
  final List<int>? revisores;
  final List<int>? pendientes;
  final int? aprobados;
  final List<Map<String, dynamic>>? votos;
  const RevisionTarea({this.id, this.tareaId, this.solicitadaPor, this.revisorId, this.estado, this.notaSolicitud, this.notaResolucion, this.solicitadaEn, this.resueltaEn, this.modo, this.turno, this.revisores, this.pendientes, this.aprobados, this.votos, });
  factory RevisionTarea.fromJson(Map<String, dynamic> j) => RevisionTarea(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    tareaId: j['tarea_id'] == null ? null : (j['tarea_id'] as num).toInt(),
    solicitadaPor: j['solicitada_por'] == null ? null : (j['solicitada_por'] as num).toInt(),
    revisorId: j['revisor_id'] == null ? null : (j['revisor_id'] as num).toInt(),
    estado: j['estado'] == null ? null : RevisionTareaEstado.desde(j['estado'] as String),
    notaSolicitud: j['nota_solicitud'] == null ? null : j['nota_solicitud'] as String,
    notaResolucion: j['nota_resolucion'] == null ? null : j['nota_resolucion'] as String,
    solicitadaEn: j['solicitada_en'] == null ? null : j['solicitada_en'] as String,
    resueltaEn: j['resuelta_en'] == null ? null : j['resuelta_en'] as String,
    modo: j['modo'] == null ? null : RevisionTareaModo.desde(j['modo'] as String),
    turno: j['turno'] == null ? null : (j['turno'] as num).toInt(),
    revisores: j['revisores'] == null ? null : (j['revisores'] as List).map((e) => (e as num).toInt()).toList(),
    pendientes: j['pendientes'] == null ? null : (j['pendientes'] as List).map((e) => (e as num).toInt()).toList(),
    aprobados: j['aprobados'] == null ? null : (j['aprobados'] as num).toInt(),
    votos: j['votos'] == null ? null : (j['votos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'tarea_id': ?tareaId,
    'solicitada_por': ?solicitadaPor,
    'revisor_id': ?revisorId,
    if (estado != null) 'estado': estado!.valor,
    'nota_solicitud': ?notaSolicitud,
    'nota_resolucion': ?notaResolucion,
    'solicitada_en': ?solicitadaEn,
    'resuelta_en': ?resueltaEn,
    if (modo != null) 'modo': modo!.valor,
    'turno': ?turno,
    if (revisores != null) 'revisores': revisores!.map((e) => e).toList(),
    if (pendientes != null) 'pendientes': pendientes!.map((e) => e).toList(),
    'aprobados': ?aprobados,
    if (votos != null) 'votos': votos!.map((e) => e).toList(),
  };
  RevisionTarea copyWith({int? id, int? tareaId, int? solicitadaPor, int? revisorId, RevisionTareaEstado? estado, String? notaSolicitud, String? notaResolucion, String? solicitadaEn, String? resueltaEn, RevisionTareaModo? modo, int? turno, List<int>? revisores, List<int>? pendientes, int? aprobados, List<Map<String, dynamic>>? votos, }) => RevisionTarea(id: id ?? this.id, tareaId: tareaId ?? this.tareaId, solicitadaPor: solicitadaPor ?? this.solicitadaPor, revisorId: revisorId ?? this.revisorId, estado: estado ?? this.estado, notaSolicitud: notaSolicitud ?? this.notaSolicitud, notaResolucion: notaResolucion ?? this.notaResolucion, solicitadaEn: solicitadaEn ?? this.solicitadaEn, resueltaEn: resueltaEn ?? this.resueltaEn, modo: modo ?? this.modo, turno: turno ?? this.turno, revisores: revisores ?? this.revisores, pendientes: pendientes ?? this.pendientes, aprobados: aprobados ?? this.aprobados, votos: votos ?? this.votos, );
  @override bool operator ==(Object other) => other is RevisionTarea && other.id == id && other.tareaId == tareaId && other.solicitadaPor == solicitadaPor && other.revisorId == revisorId && other.estado == estado && other.notaSolicitud == notaSolicitud && other.notaResolucion == notaResolucion && other.solicitadaEn == solicitadaEn && other.resueltaEn == resueltaEn && other.modo == modo && other.turno == turno && other.revisores == revisores && other.pendientes == pendientes && other.aprobados == aprobados && other.votos == votos;
  @override int get hashCode => Object.hashAll([id, tareaId, solicitadaPor, revisorId, estado, notaSolicitud, notaResolucion, solicitadaEn, resueltaEn, modo, turno, revisores, pendientes, aprobados, votos]);
}

class RevisionesDeTarea {
  final dynamic? pendiente;
  final List<RevisionTarea>? historial;
  const RevisionesDeTarea({this.pendiente, this.historial, });
  factory RevisionesDeTarea.fromJson(Map<String, dynamic> j) => RevisionesDeTarea(
    pendiente: j['pendiente'],
    historial: j['historial'] == null ? null : (j['historial'] as List).map((e) => RevisionTarea.fromJson(e as Map<String, dynamic>)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'pendiente': ?pendiente,
    if (historial != null) 'historial': historial!.map((e) => e.toJson()).toList(),
  };
  RevisionesDeTarea copyWith({dynamic pendiente, List<RevisionTarea>? historial, }) => RevisionesDeTarea(pendiente: pendiente ?? this.pendiente, historial: historial ?? this.historial, );
  @override bool operator ==(Object other) => other is RevisionesDeTarea && other.pendiente == pendiente && other.historial == historial;
  @override int get hashCode => Object.hashAll([pendiente, historial]);
}

class Revocada {
  final bool? revocada;
  const Revocada({this.revocada, });
  factory Revocada.fromJson(Map<String, dynamic> j) => Revocada(
    revocada: j['revocada'] == null ? null : _aBool(j['revocada']),
  );
  Map<String, dynamic> toJson() => {
    'revocada': ?revocada,
  };
  Revocada copyWith({bool? revocada, }) => Revocada(revocada: revocada ?? this.revocada, );
  @override bool operator ==(Object other) => other is Revocada && other.revocada == revocada;
  @override int get hashCode => Object.hashAll([revocada]);
}

class RiesgoCertificado {
  final int? vencimientoId;
  final String? cliente;
  final String? modelo;
  final String? periodo;
  final String? fechaLimite;
  final RiesgoCertificadoTipo? tipo;
  final String? motivo;
  final int? certificadoId;
  const RiesgoCertificado({this.vencimientoId, this.cliente, this.modelo, this.periodo, this.fechaLimite, this.tipo, this.motivo, this.certificadoId, });
  factory RiesgoCertificado.fromJson(Map<String, dynamic> j) => RiesgoCertificado(
    vencimientoId: j['vencimiento_id'] == null ? null : (j['vencimiento_id'] as num).toInt(),
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    modelo: j['modelo'] == null ? null : j['modelo'] as String,
    periodo: j['periodo'] == null ? null : j['periodo'] as String,
    fechaLimite: j['fecha_limite'] == null ? null : j['fecha_limite'] as String,
    tipo: j['tipo'] == null ? null : RiesgoCertificadoTipo.desde(j['tipo'] as String),
    motivo: j['motivo'] == null ? null : j['motivo'] as String,
    certificadoId: j['certificado_id'] == null ? null : (j['certificado_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'vencimiento_id': ?vencimientoId,
    'cliente': ?cliente,
    'modelo': ?modelo,
    'periodo': ?periodo,
    'fecha_limite': ?fechaLimite,
    if (tipo != null) 'tipo': tipo!.valor,
    'motivo': ?motivo,
    'certificado_id': ?certificadoId,
  };
  RiesgoCertificado copyWith({int? vencimientoId, String? cliente, String? modelo, String? periodo, String? fechaLimite, RiesgoCertificadoTipo? tipo, String? motivo, int? certificadoId, }) => RiesgoCertificado(vencimientoId: vencimientoId ?? this.vencimientoId, cliente: cliente ?? this.cliente, modelo: modelo ?? this.modelo, periodo: periodo ?? this.periodo, fechaLimite: fechaLimite ?? this.fechaLimite, tipo: tipo ?? this.tipo, motivo: motivo ?? this.motivo, certificadoId: certificadoId ?? this.certificadoId, );
  @override bool operator ==(Object other) => other is RiesgoCertificado && other.vencimientoId == vencimientoId && other.cliente == cliente && other.modelo == modelo && other.periodo == periodo && other.fechaLimite == fechaLimite && other.tipo == tipo && other.motivo == motivo && other.certificadoId == certificadoId;
  @override int get hashCode => Object.hashAll([vencimientoId, cliente, modelo, periodo, fechaLimite, tipo, motivo, certificadoId]);
}

class SaldoAusencias {
  final int? anio;
  final double? total;
  final double? aprobadas;
  final double? pendientes;
  final double? disponibles;
  const SaldoAusencias({this.anio, this.total, this.aprobadas, this.pendientes, this.disponibles, });
  factory SaldoAusencias.fromJson(Map<String, dynamic> j) => SaldoAusencias(
    anio: j['anio'] == null ? null : (j['anio'] as num).toInt(),
    total: j['total'] == null ? null : (j['total'] as num).toDouble(),
    aprobadas: j['aprobadas'] == null ? null : (j['aprobadas'] as num).toDouble(),
    pendientes: j['pendientes'] == null ? null : (j['pendientes'] as num).toDouble(),
    disponibles: j['disponibles'] == null ? null : (j['disponibles'] as num).toDouble(),
  );
  Map<String, dynamic> toJson() => {
    'anio': ?anio,
    'total': ?total,
    'aprobadas': ?aprobadas,
    'pendientes': ?pendientes,
    'disponibles': ?disponibles,
  };
  SaldoAusencias copyWith({int? anio, double? total, double? aprobadas, double? pendientes, double? disponibles, }) => SaldoAusencias(anio: anio ?? this.anio, total: total ?? this.total, aprobadas: aprobadas ?? this.aprobadas, pendientes: pendientes ?? this.pendientes, disponibles: disponibles ?? this.disponibles, );
  @override bool operator ==(Object other) => other is SaldoAusencias && other.anio == anio && other.total == total && other.aprobadas == aprobadas && other.pendientes == pendientes && other.disponibles == disponibles;
  @override int get hashCode => Object.hashAll([anio, total, aprobadas, pendientes, disponibles]);
}

class SeccionHoy {
  final String? clave;
  final String? titulo;
  final int? total;
  final int? urgentes;
  final List<ElementoHoy>? elementos;
  const SeccionHoy({this.clave, this.titulo, this.total, this.urgentes, this.elementos, });
  factory SeccionHoy.fromJson(Map<String, dynamic> j) => SeccionHoy(
    clave: j['clave'] == null ? null : j['clave'] as String,
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    total: j['total'] == null ? null : (j['total'] as num).toInt(),
    urgentes: j['urgentes'] == null ? null : (j['urgentes'] as num).toInt(),
    elementos: j['elementos'] == null ? null : (j['elementos'] as List).map((e) => ElementoHoy.fromJson(e as Map<String, dynamic>)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'clave': ?clave,
    'titulo': ?titulo,
    'total': ?total,
    'urgentes': ?urgentes,
    if (elementos != null) 'elementos': elementos!.map((e) => e.toJson()).toList(),
  };
  SeccionHoy copyWith({String? clave, String? titulo, int? total, int? urgentes, List<ElementoHoy>? elementos, }) => SeccionHoy(clave: clave ?? this.clave, titulo: titulo ?? this.titulo, total: total ?? this.total, urgentes: urgentes ?? this.urgentes, elementos: elementos ?? this.elementos, );
  @override bool operator ==(Object other) => other is SeccionHoy && other.clave == clave && other.titulo == titulo && other.total == total && other.urgentes == urgentes && other.elementos == elementos;
  @override int get hashCode => Object.hashAll([clave, titulo, total, urgentes, elementos]);
}

class SeguimientoCorreo {
  final int id;
  final int? usuarioId;
  final int? cuentaId;
  final String? messageId;
  final String? asunto;
  final String? destinatarios;
  final String? creadoEn;
  final String? avisarEn;
  final String? estado;
  final String? cerradoEn;
  const SeguimientoCorreo({required this.id, this.usuarioId, this.cuentaId, this.messageId, this.asunto, this.destinatarios, this.creadoEn, this.avisarEn, this.estado, this.cerradoEn, });
  factory SeguimientoCorreo.fromJson(Map<String, dynamic> j) => SeguimientoCorreo(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    cuentaId: j['cuenta_id'] == null ? null : (j['cuenta_id'] as num).toInt(),
    messageId: j['message_id'] == null ? null : j['message_id'] as String,
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    destinatarios: j['destinatarios'] == null ? null : j['destinatarios'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    avisarEn: j['avisar_en'] == null ? null : j['avisar_en'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    cerradoEn: j['cerrado_en'] == null ? null : j['cerrado_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'cuenta_id': ?cuentaId,
    'message_id': ?messageId,
    'asunto': ?asunto,
    'destinatarios': ?destinatarios,
    'creado_en': ?creadoEn,
    'avisar_en': ?avisarEn,
    'estado': ?estado,
    'cerrado_en': ?cerradoEn,
  };
  SeguimientoCorreo copyWith({int? id, int? usuarioId, int? cuentaId, String? messageId, String? asunto, String? destinatarios, String? creadoEn, String? avisarEn, String? estado, String? cerradoEn, }) => SeguimientoCorreo(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, cuentaId: cuentaId ?? this.cuentaId, messageId: messageId ?? this.messageId, asunto: asunto ?? this.asunto, destinatarios: destinatarios ?? this.destinatarios, creadoEn: creadoEn ?? this.creadoEn, avisarEn: avisarEn ?? this.avisarEn, estado: estado ?? this.estado, cerradoEn: cerradoEn ?? this.cerradoEn, );
  @override bool operator ==(Object other) => other is SeguimientoCorreo && other.id == id && other.usuarioId == usuarioId && other.cuentaId == cuentaId && other.messageId == messageId && other.asunto == asunto && other.destinatarios == destinatarios && other.creadoEn == creadoEn && other.avisarEn == avisarEn && other.estado == estado && other.cerradoEn == cerradoEn;
  @override int get hashCode => Object.hashAll([id, usuarioId, cuentaId, messageId, asunto, destinatarios, creadoEn, avisarEn, estado, cerradoEn]);
}

class Sesion {
  final String token;
  final Usuario usuario;
  const Sesion({required this.token, required this.usuario, });
  factory Sesion.fromJson(Map<String, dynamic> j) => Sesion(
    token: j['token'] as String,
    usuario: Usuario.fromJson(j['usuario'] as Map<String, dynamic>),
  );
  Map<String, dynamic> toJson() => {
    'token': token,
    'usuario': usuario.toJson(),
  };
  Sesion copyWith({String? token, Usuario? usuario, }) => Sesion(token: token ?? this.token, usuario: usuario ?? this.usuario, );
  @override bool operator ==(Object other) => other is Sesion && other.token == token && other.usuario == usuario;
  @override int get hashCode => Object.hashAll([token, usuario]);
}

class Sincronizacion {
  final int cursor;
  final bool hayMas;
  final bool reiniciar;
  final Map<String, dynamic>? cambios;
  final Map<String, dynamic>? eliminados;
  const Sincronizacion({required this.cursor, required this.hayMas, required this.reiniciar, this.cambios, this.eliminados, });
  factory Sincronizacion.fromJson(Map<String, dynamic> j) => Sincronizacion(
    cursor: (j['cursor'] as num).toInt(),
    hayMas: _aBool(j['hay_mas']),
    reiniciar: _aBool(j['reiniciar']),
    cambios: j['cambios'] == null ? null : Map<String, dynamic>.from(j['cambios'] as Map),
    eliminados: j['eliminados'] == null ? null : Map<String, dynamic>.from(j['eliminados'] as Map),
  );
  Map<String, dynamic> toJson() => {
    'cursor': cursor,
    'hay_mas': hayMas,
    'reiniciar': reiniciar,
    'cambios': ?cambios,
    'eliminados': ?eliminados,
  };
  Sincronizacion copyWith({int? cursor, bool? hayMas, bool? reiniciar, Map<String, dynamic>? cambios, Map<String, dynamic>? eliminados, }) => Sincronizacion(cursor: cursor ?? this.cursor, hayMas: hayMas ?? this.hayMas, reiniciar: reiniciar ?? this.reiniciar, cambios: cambios ?? this.cambios, eliminados: eliminados ?? this.eliminados, );
  @override bool operator ==(Object other) => other is Sincronizacion && other.cursor == cursor && other.hayMas == hayMas && other.reiniciar == reiniciar && other.cambios == cambios && other.eliminados == eliminados;
  @override int get hashCode => Object.hashAll([cursor, hayMas, reiniciar, cambios, eliminados]);
}

class SubtareasDeTarea {
  final List<Map<String, dynamic>>? subtareas;
  final Map<String, dynamic>? progreso;
  const SubtareasDeTarea({this.subtareas, this.progreso, });
  factory SubtareasDeTarea.fromJson(Map<String, dynamic> j) => SubtareasDeTarea(
    subtareas: j['subtareas'] == null ? null : (j['subtareas'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    progreso: j['progreso'] == null ? null : Map<String, dynamic>.from(j['progreso'] as Map),
  );
  Map<String, dynamic> toJson() => {
    if (subtareas != null) 'subtareas': subtareas!.map((e) => e).toList(),
    'progreso': ?progreso,
  };
  SubtareasDeTarea copyWith({List<Map<String, dynamic>>? subtareas, Map<String, dynamic>? progreso, }) => SubtareasDeTarea(subtareas: subtareas ?? this.subtareas, progreso: progreso ?? this.progreso, );
  @override bool operator ==(Object other) => other is SubtareasDeTarea && other.subtareas == subtareas && other.progreso == progreso;
  @override int get hashCode => Object.hashAll([subtareas, progreso]);
}

class TareaConDuracion {
  final int id;
  final int? usuarioId;
  final String? nombre;
  final int? categoriaId;
  final String? tipo;
  final String? estado;
  final String? inicioEn;
  final String? finEn;
  final int? duracionSegundos;
  final String? papeleraEn;
  final int? tareaOutlookId;
  const TareaConDuracion({required this.id, this.usuarioId, this.nombre, this.categoriaId, this.tipo, this.estado, this.inicioEn, this.finEn, this.duracionSegundos, this.papeleraEn, this.tareaOutlookId, });
  factory TareaConDuracion.fromJson(Map<String, dynamic> j) => TareaConDuracion(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    inicioEn: j['inicio_en'] == null ? null : j['inicio_en'] as String,
    finEn: j['fin_en'] == null ? null : j['fin_en'] as String,
    duracionSegundos: j['duracion_segundos'] == null ? null : (j['duracion_segundos'] as num).toInt(),
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
    tareaOutlookId: j['tarea_outlook_id'] == null ? null : (j['tarea_outlook_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'nombre': ?nombre,
    'categoria_id': ?categoriaId,
    'tipo': ?tipo,
    'estado': ?estado,
    'inicio_en': ?inicioEn,
    'fin_en': ?finEn,
    'duracion_segundos': ?duracionSegundos,
    'papelera_en': ?papeleraEn,
    'tarea_outlook_id': ?tareaOutlookId,
  };
  TareaConDuracion copyWith({int? id, int? usuarioId, String? nombre, int? categoriaId, String? tipo, String? estado, String? inicioEn, String? finEn, int? duracionSegundos, String? papeleraEn, int? tareaOutlookId, }) => TareaConDuracion(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, nombre: nombre ?? this.nombre, categoriaId: categoriaId ?? this.categoriaId, tipo: tipo ?? this.tipo, estado: estado ?? this.estado, inicioEn: inicioEn ?? this.inicioEn, finEn: finEn ?? this.finEn, duracionSegundos: duracionSegundos ?? this.duracionSegundos, papeleraEn: papeleraEn ?? this.papeleraEn, tareaOutlookId: tareaOutlookId ?? this.tareaOutlookId, );
  @override bool operator ==(Object other) => other is TareaConDuracion && other.id == id && other.usuarioId == usuarioId && other.nombre == nombre && other.categoriaId == categoriaId && other.tipo == tipo && other.estado == estado && other.inicioEn == inicioEn && other.finEn == finEn && other.duracionSegundos == duracionSegundos && other.papeleraEn == papeleraEn && other.tareaOutlookId == tareaOutlookId;
  @override int get hashCode => Object.hashAll([id, usuarioId, nombre, categoriaId, tipo, estado, inicioEn, finEn, duracionSegundos, papeleraEn, tareaOutlookId]);
}

class TareaOutlook {
  final int id;
  final int? usuarioId;
  final String? asunto;
  final String? cuerpo;
  final String? estado;
  final int? porcentajeCompletado;
  final String? prioridad;
  final String? fechaInicio;
  final String? fechaVencimiento;
  final String? fechaCompletada;
  final String? categoriaOutlook;
  final String? outlookEntryId;
  final String? creadaEn;
  final String? actualizadaEn;
  final String? papeleraEn;
  final String? referenciaExterna;
  final int? tareaRecurrenteId;
  final int? asignadaA;
  final int? clienteFiscalId;
  final int? vencimientoId;
  final int? mensajeCorreoId;
  final int? categoriaId;
  final int? seccionId;
  final int? ordenProyecto;
  final int? estimacionMin;
  final int? version;
  final String? motivoBloqueo;
  final int? tareaPadreId;
  final int? visibleCliente;
  final int? comentariosCliente;
  final String? categoriaNombre;
  final String? categoriaColor;
  final bool? vencida;
  final List<ClienteDeTarea>? clientes;
  final int? nComentarios;
  final int? checklistHechas;
  final int? checklistTotal;
  final String? asignadaNombre;
  final String? creadorNombre;
  final int? bloqueos;
  final String? rol;
  const TareaOutlook({required this.id, this.usuarioId, this.asunto, this.cuerpo, this.estado, this.porcentajeCompletado, this.prioridad, this.fechaInicio, this.fechaVencimiento, this.fechaCompletada, this.categoriaOutlook, this.outlookEntryId, this.creadaEn, this.actualizadaEn, this.papeleraEn, this.referenciaExterna, this.tareaRecurrenteId, this.asignadaA, this.clienteFiscalId, this.vencimientoId, this.mensajeCorreoId, this.categoriaId, this.seccionId, this.ordenProyecto, this.estimacionMin, this.version, this.motivoBloqueo, this.tareaPadreId, this.visibleCliente, this.comentariosCliente, this.categoriaNombre, this.categoriaColor, this.vencida, this.clientes, this.nComentarios, this.checklistHechas, this.checklistTotal, this.asignadaNombre, this.creadorNombre, this.bloqueos, this.rol, });
  factory TareaOutlook.fromJson(Map<String, dynamic> j) => TareaOutlook(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
    cuerpo: j['cuerpo'] == null ? null : j['cuerpo'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    porcentajeCompletado: j['porcentaje_completado'] == null ? null : (j['porcentaje_completado'] as num).toInt(),
    prioridad: j['prioridad'] == null ? null : j['prioridad'] as String,
    fechaInicio: j['fecha_inicio'] == null ? null : j['fecha_inicio'] as String,
    fechaVencimiento: j['fecha_vencimiento'] == null ? null : j['fecha_vencimiento'] as String,
    fechaCompletada: j['fecha_completada'] == null ? null : j['fecha_completada'] as String,
    categoriaOutlook: j['categoria_outlook'] == null ? null : j['categoria_outlook'] as String,
    outlookEntryId: j['outlook_entry_id'] == null ? null : j['outlook_entry_id'] as String,
    creadaEn: j['creada_en'] == null ? null : j['creada_en'] as String,
    actualizadaEn: j['actualizada_en'] == null ? null : j['actualizada_en'] as String,
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
    referenciaExterna: j['referencia_externa'] == null ? null : j['referencia_externa'] as String,
    tareaRecurrenteId: j['tarea_recurrente_id'] == null ? null : (j['tarea_recurrente_id'] as num).toInt(),
    asignadaA: j['asignada_a'] == null ? null : (j['asignada_a'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    vencimientoId: j['vencimiento_id'] == null ? null : (j['vencimiento_id'] as num).toInt(),
    mensajeCorreoId: j['mensaje_correo_id'] == null ? null : (j['mensaje_correo_id'] as num).toInt(),
    categoriaId: j['categoria_id'] == null ? null : (j['categoria_id'] as num).toInt(),
    seccionId: j['seccion_id'] == null ? null : (j['seccion_id'] as num).toInt(),
    ordenProyecto: j['orden_proyecto'] == null ? null : (j['orden_proyecto'] as num).toInt(),
    estimacionMin: j['estimacion_min'] == null ? null : (j['estimacion_min'] as num).toInt(),
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    motivoBloqueo: j['motivo_bloqueo'] == null ? null : j['motivo_bloqueo'] as String,
    tareaPadreId: j['tarea_padre_id'] == null ? null : (j['tarea_padre_id'] as num).toInt(),
    visibleCliente: j['visible_cliente'] == null ? null : (j['visible_cliente'] as num).toInt(),
    comentariosCliente: j['comentarios_cliente'] == null ? null : (j['comentarios_cliente'] as num).toInt(),
    categoriaNombre: j['categoria_nombre'] == null ? null : j['categoria_nombre'] as String,
    categoriaColor: j['categoria_color'] == null ? null : j['categoria_color'] as String,
    vencida: j['vencida'] == null ? null : _aBool(j['vencida']),
    clientes: j['clientes'] == null ? null : (j['clientes'] as List).map((e) => ClienteDeTarea.fromJson(e as Map<String, dynamic>)).toList(),
    nComentarios: j['n_comentarios'] == null ? null : (j['n_comentarios'] as num).toInt(),
    checklistHechas: j['checklist_hechas'] == null ? null : (j['checklist_hechas'] as num).toInt(),
    checklistTotal: j['checklist_total'] == null ? null : (j['checklist_total'] as num).toInt(),
    asignadaNombre: j['asignada_nombre'] == null ? null : j['asignada_nombre'] as String,
    creadorNombre: j['creador_nombre'] == null ? null : j['creador_nombre'] as String,
    bloqueos: j['bloqueos'] == null ? null : (j['bloqueos'] as num).toInt(),
    rol: j['rol'] == null ? null : j['rol'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'asunto': ?asunto,
    'cuerpo': ?cuerpo,
    'estado': ?estado,
    'porcentaje_completado': ?porcentajeCompletado,
    'prioridad': ?prioridad,
    'fecha_inicio': ?fechaInicio,
    'fecha_vencimiento': ?fechaVencimiento,
    'fecha_completada': ?fechaCompletada,
    'categoria_outlook': ?categoriaOutlook,
    'outlook_entry_id': ?outlookEntryId,
    'creada_en': ?creadaEn,
    'actualizada_en': ?actualizadaEn,
    'papelera_en': ?papeleraEn,
    'referencia_externa': ?referenciaExterna,
    'tarea_recurrente_id': ?tareaRecurrenteId,
    'asignada_a': ?asignadaA,
    'cliente_fiscal_id': ?clienteFiscalId,
    'vencimiento_id': ?vencimientoId,
    'mensaje_correo_id': ?mensajeCorreoId,
    'categoria_id': ?categoriaId,
    'seccion_id': ?seccionId,
    'orden_proyecto': ?ordenProyecto,
    'estimacion_min': ?estimacionMin,
    'version': ?version,
    'motivo_bloqueo': ?motivoBloqueo,
    'tarea_padre_id': ?tareaPadreId,
    'visible_cliente': ?visibleCliente,
    'comentarios_cliente': ?comentariosCliente,
    'categoria_nombre': ?categoriaNombre,
    'categoria_color': ?categoriaColor,
    'vencida': ?vencida,
    if (clientes != null) 'clientes': clientes!.map((e) => e.toJson()).toList(),
    'n_comentarios': ?nComentarios,
    'checklist_hechas': ?checklistHechas,
    'checklist_total': ?checklistTotal,
    'asignada_nombre': ?asignadaNombre,
    'creador_nombre': ?creadorNombre,
    'bloqueos': ?bloqueos,
    'rol': ?rol,
  };
  TareaOutlook copyWith({int? id, int? usuarioId, String? asunto, String? cuerpo, String? estado, int? porcentajeCompletado, String? prioridad, String? fechaInicio, String? fechaVencimiento, String? fechaCompletada, String? categoriaOutlook, String? outlookEntryId, String? creadaEn, String? actualizadaEn, String? papeleraEn, String? referenciaExterna, int? tareaRecurrenteId, int? asignadaA, int? clienteFiscalId, int? vencimientoId, int? mensajeCorreoId, int? categoriaId, int? seccionId, int? ordenProyecto, int? estimacionMin, int? version, String? motivoBloqueo, int? tareaPadreId, int? visibleCliente, int? comentariosCliente, String? categoriaNombre, String? categoriaColor, bool? vencida, List<ClienteDeTarea>? clientes, int? nComentarios, int? checklistHechas, int? checklistTotal, String? asignadaNombre, String? creadorNombre, int? bloqueos, String? rol, }) => TareaOutlook(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, asunto: asunto ?? this.asunto, cuerpo: cuerpo ?? this.cuerpo, estado: estado ?? this.estado, porcentajeCompletado: porcentajeCompletado ?? this.porcentajeCompletado, prioridad: prioridad ?? this.prioridad, fechaInicio: fechaInicio ?? this.fechaInicio, fechaVencimiento: fechaVencimiento ?? this.fechaVencimiento, fechaCompletada: fechaCompletada ?? this.fechaCompletada, categoriaOutlook: categoriaOutlook ?? this.categoriaOutlook, outlookEntryId: outlookEntryId ?? this.outlookEntryId, creadaEn: creadaEn ?? this.creadaEn, actualizadaEn: actualizadaEn ?? this.actualizadaEn, papeleraEn: papeleraEn ?? this.papeleraEn, referenciaExterna: referenciaExterna ?? this.referenciaExterna, tareaRecurrenteId: tareaRecurrenteId ?? this.tareaRecurrenteId, asignadaA: asignadaA ?? this.asignadaA, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, vencimientoId: vencimientoId ?? this.vencimientoId, mensajeCorreoId: mensajeCorreoId ?? this.mensajeCorreoId, categoriaId: categoriaId ?? this.categoriaId, seccionId: seccionId ?? this.seccionId, ordenProyecto: ordenProyecto ?? this.ordenProyecto, estimacionMin: estimacionMin ?? this.estimacionMin, version: version ?? this.version, motivoBloqueo: motivoBloqueo ?? this.motivoBloqueo, tareaPadreId: tareaPadreId ?? this.tareaPadreId, visibleCliente: visibleCliente ?? this.visibleCliente, comentariosCliente: comentariosCliente ?? this.comentariosCliente, categoriaNombre: categoriaNombre ?? this.categoriaNombre, categoriaColor: categoriaColor ?? this.categoriaColor, vencida: vencida ?? this.vencida, clientes: clientes ?? this.clientes, nComentarios: nComentarios ?? this.nComentarios, checklistHechas: checklistHechas ?? this.checklistHechas, checklistTotal: checklistTotal ?? this.checklistTotal, asignadaNombre: asignadaNombre ?? this.asignadaNombre, creadorNombre: creadorNombre ?? this.creadorNombre, bloqueos: bloqueos ?? this.bloqueos, rol: rol ?? this.rol, );
  @override bool operator ==(Object other) => other is TareaOutlook && other.id == id && other.usuarioId == usuarioId && other.asunto == asunto && other.cuerpo == cuerpo && other.estado == estado && other.porcentajeCompletado == porcentajeCompletado && other.prioridad == prioridad && other.fechaInicio == fechaInicio && other.fechaVencimiento == fechaVencimiento && other.fechaCompletada == fechaCompletada && other.categoriaOutlook == categoriaOutlook && other.outlookEntryId == outlookEntryId && other.creadaEn == creadaEn && other.actualizadaEn == actualizadaEn && other.papeleraEn == papeleraEn && other.referenciaExterna == referenciaExterna && other.tareaRecurrenteId == tareaRecurrenteId && other.asignadaA == asignadaA && other.clienteFiscalId == clienteFiscalId && other.vencimientoId == vencimientoId && other.mensajeCorreoId == mensajeCorreoId && other.categoriaId == categoriaId && other.seccionId == seccionId && other.ordenProyecto == ordenProyecto && other.estimacionMin == estimacionMin && other.version == version && other.motivoBloqueo == motivoBloqueo && other.tareaPadreId == tareaPadreId && other.visibleCliente == visibleCliente && other.comentariosCliente == comentariosCliente && other.categoriaNombre == categoriaNombre && other.categoriaColor == categoriaColor && other.vencida == vencida && other.clientes == clientes && other.nComentarios == nComentarios && other.checklistHechas == checklistHechas && other.checklistTotal == checklistTotal && other.asignadaNombre == asignadaNombre && other.creadorNombre == creadorNombre && other.bloqueos == bloqueos && other.rol == rol;
  @override int get hashCode => Object.hashAll([id, usuarioId, asunto, cuerpo, estado, porcentajeCompletado, prioridad, fechaInicio, fechaVencimiento, fechaCompletada, categoriaOutlook, outlookEntryId, creadaEn, actualizadaEn, papeleraEn, referenciaExterna, tareaRecurrenteId, asignadaA, clienteFiscalId, vencimientoId, mensajeCorreoId, categoriaId, seccionId, ordenProyecto, estimacionMin, version, motivoBloqueo, tareaPadreId, visibleCliente, comentariosCliente, categoriaNombre, categoriaColor, vencida, clientes, nComentarios, checklistHechas, checklistTotal, asignadaNombre, creadorNombre, bloqueos, rol]);
}

class TareasCreadasDeReunion {
  final List<int>? tareaIds;
  const TareasCreadasDeReunion({this.tareaIds, });
  factory TareasCreadasDeReunion.fromJson(Map<String, dynamic> j) => TareasCreadasDeReunion(
    tareaIds: j['tarea_ids'] == null ? null : (j['tarea_ids'] as List).map((e) => (e as num).toInt()).toList(),
  );
  Map<String, dynamic> toJson() => {
    if (tareaIds != null) 'tarea_ids': tareaIds!.map((e) => e).toList(),
  };
  TareasCreadasDeReunion copyWith({List<int>? tareaIds, }) => TareasCreadasDeReunion(tareaIds: tareaIds ?? this.tareaIds, );
  @override bool operator ==(Object other) => other is TareasCreadasDeReunion && other.tareaIds == tareaIds;
  @override int get hashCode => Object.hashAll([tareaIds]);
}

class Tiquet {
  final int id;
  final int? usuarioId;
  final String? tipo;
  final String? titulo;
  final String? descripcion;
  final String? estado;
  final String? creadoEn;
  final String? actualizadoEn;
  final String? prioridad;
  final int? usuarioAsignadoId;
  const Tiquet({required this.id, this.usuarioId, this.tipo, this.titulo, this.descripcion, this.estado, this.creadoEn, this.actualizadoEn, this.prioridad, this.usuarioAsignadoId, });
  factory Tiquet.fromJson(Map<String, dynamic> j) => Tiquet(
    id: (j['id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    titulo: j['titulo'] == null ? null : j['titulo'] as String,
    descripcion: j['descripcion'] == null ? null : j['descripcion'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    actualizadoEn: j['actualizado_en'] == null ? null : j['actualizado_en'] as String,
    prioridad: j['prioridad'] == null ? null : j['prioridad'] as String,
    usuarioAsignadoId: j['usuario_asignado_id'] == null ? null : (j['usuario_asignado_id'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'usuario_id': ?usuarioId,
    'tipo': ?tipo,
    'titulo': ?titulo,
    'descripcion': ?descripcion,
    'estado': ?estado,
    'creado_en': ?creadoEn,
    'actualizado_en': ?actualizadoEn,
    'prioridad': ?prioridad,
    'usuario_asignado_id': ?usuarioAsignadoId,
  };
  Tiquet copyWith({int? id, int? usuarioId, String? tipo, String? titulo, String? descripcion, String? estado, String? creadoEn, String? actualizadoEn, String? prioridad, int? usuarioAsignadoId, }) => Tiquet(id: id ?? this.id, usuarioId: usuarioId ?? this.usuarioId, tipo: tipo ?? this.tipo, titulo: titulo ?? this.titulo, descripcion: descripcion ?? this.descripcion, estado: estado ?? this.estado, creadoEn: creadoEn ?? this.creadoEn, actualizadoEn: actualizadoEn ?? this.actualizadoEn, prioridad: prioridad ?? this.prioridad, usuarioAsignadoId: usuarioAsignadoId ?? this.usuarioAsignadoId, );
  @override bool operator ==(Object other) => other is Tiquet && other.id == id && other.usuarioId == usuarioId && other.tipo == tipo && other.titulo == titulo && other.descripcion == descripcion && other.estado == estado && other.creadoEn == creadoEn && other.actualizadoEn == actualizadoEn && other.prioridad == prioridad && other.usuarioAsignadoId == usuarioAsignadoId;
  @override int get hashCode => Object.hashAll([id, usuarioId, tipo, titulo, descripcion, estado, creadoEn, actualizadoEn, prioridad, usuarioAsignadoId]);
}

class Token {
  final int? id;
  final String? nombreDispositivo;
  final String? permisos;
  final List<String>? areas;
  final String? caducaEn;
  final String? creadoEn;
  final String? ultimoUsoEn;
  final String? ultimaIp;
  final int? llamadas30d;
  const Token({this.id, this.nombreDispositivo, this.permisos, this.areas, this.caducaEn, this.creadoEn, this.ultimoUsoEn, this.ultimaIp, this.llamadas30d, });
  factory Token.fromJson(Map<String, dynamic> j) => Token(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nombreDispositivo: j['nombre_dispositivo'] == null ? null : j['nombre_dispositivo'] as String,
    permisos: j['permisos'] == null ? null : j['permisos'] as String,
    areas: j['areas'] == null ? null : (j['areas'] as List).map((e) => e as String).toList(),
    caducaEn: j['caduca_en'] == null ? null : j['caduca_en'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    ultimoUsoEn: j['ultimo_uso_en'] == null ? null : j['ultimo_uso_en'] as String,
    ultimaIp: j['ultima_ip'] == null ? null : j['ultima_ip'] as String,
    llamadas30d: j['llamadas_30d'] == null ? null : (j['llamadas_30d'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre_dispositivo': ?nombreDispositivo,
    'permisos': ?permisos,
    if (areas != null) 'areas': areas!.map((e) => e).toList(),
    'caduca_en': ?caducaEn,
    'creado_en': ?creadoEn,
    'ultimo_uso_en': ?ultimoUsoEn,
    'ultima_ip': ?ultimaIp,
    'llamadas_30d': ?llamadas30d,
  };
  Token copyWith({int? id, String? nombreDispositivo, String? permisos, List<String>? areas, String? caducaEn, String? creadoEn, String? ultimoUsoEn, String? ultimaIp, int? llamadas30d, }) => Token(id: id ?? this.id, nombreDispositivo: nombreDispositivo ?? this.nombreDispositivo, permisos: permisos ?? this.permisos, areas: areas ?? this.areas, caducaEn: caducaEn ?? this.caducaEn, creadoEn: creadoEn ?? this.creadoEn, ultimoUsoEn: ultimoUsoEn ?? this.ultimoUsoEn, ultimaIp: ultimaIp ?? this.ultimaIp, llamadas30d: llamadas30d ?? this.llamadas30d, );
  @override bool operator ==(Object other) => other is Token && other.id == id && other.nombreDispositivo == nombreDispositivo && other.permisos == permisos && other.areas == areas && other.caducaEn == caducaEn && other.creadoEn == creadoEn && other.ultimoUsoEn == ultimoUsoEn && other.ultimaIp == ultimaIp && other.llamadas30d == llamadas30d;
  @override int get hashCode => Object.hashAll([id, nombreDispositivo, permisos, areas, caducaEn, creadoEn, ultimoUsoEn, ultimaIp, llamadas30d]);
}

class TokenCreado {
  final String? token;
  final int? id;
  final TokenCreadoPermisos? permisos;
  final String? nombre;
  final List<String>? areas;
  final String? caducaEn;
  const TokenCreado({this.token, this.id, this.permisos, this.nombre, this.areas, this.caducaEn, });
  factory TokenCreado.fromJson(Map<String, dynamic> j) => TokenCreado(
    token: j['token'] == null ? null : j['token'] as String,
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    permisos: j['permisos'] == null ? null : TokenCreadoPermisos.desde(j['permisos'] as String),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    areas: j['areas'] == null ? null : (j['areas'] as List).map((e) => e as String).toList(),
    caducaEn: j['caduca_en'] == null ? null : j['caduca_en'] as String,
  );
  Map<String, dynamic> toJson() => {
    'token': ?token,
    'id': ?id,
    if (permisos != null) 'permisos': permisos!.valor,
    'nombre': ?nombre,
    if (areas != null) 'areas': areas!.map((e) => e).toList(),
    'caduca_en': ?caducaEn,
  };
  TokenCreado copyWith({String? token, int? id, TokenCreadoPermisos? permisos, String? nombre, List<String>? areas, String? caducaEn, }) => TokenCreado(token: token ?? this.token, id: id ?? this.id, permisos: permisos ?? this.permisos, nombre: nombre ?? this.nombre, areas: areas ?? this.areas, caducaEn: caducaEn ?? this.caducaEn, );
  @override bool operator ==(Object other) => other is TokenCreado && other.token == token && other.id == id && other.permisos == permisos && other.nombre == nombre && other.areas == areas && other.caducaEn == caducaEn;
  @override int get hashCode => Object.hashAll([token, id, permisos, nombre, areas, caducaEn]);
}

class Traspaso {
  final int id;
  final int? clienteFiscalId;
  final int? deUsuarioId;
  final int? aUsuarioId;
  final int? deOficinaId;
  final int? aOficinaId;
  final String? nota;
  final String? estado;
  final int? creadoPor;
  final String? creadoEn;
  final int? resueltoPor;
  final String? resueltoEn;
  final String? motivo;
  final String? escaladoEn;
  final int? version;
  final String? cliente;
  final String? deNombre;
  final String? aNombre;
  final String? deOficina;
  final String? aOficina;
  final String? proximoVencimiento;
  final int? diasAlVencimiento;
  const Traspaso({required this.id, this.clienteFiscalId, this.deUsuarioId, this.aUsuarioId, this.deOficinaId, this.aOficinaId, this.nota, this.estado, this.creadoPor, this.creadoEn, this.resueltoPor, this.resueltoEn, this.motivo, this.escaladoEn, this.version, this.cliente, this.deNombre, this.aNombre, this.deOficina, this.aOficina, this.proximoVencimiento, this.diasAlVencimiento, });
  factory Traspaso.fromJson(Map<String, dynamic> j) => Traspaso(
    id: (j['id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    deUsuarioId: j['de_usuario_id'] == null ? null : (j['de_usuario_id'] as num).toInt(),
    aUsuarioId: j['a_usuario_id'] == null ? null : (j['a_usuario_id'] as num).toInt(),
    deOficinaId: j['de_oficina_id'] == null ? null : (j['de_oficina_id'] as num).toInt(),
    aOficinaId: j['a_oficina_id'] == null ? null : (j['a_oficina_id'] as num).toInt(),
    nota: j['nota'] == null ? null : j['nota'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    creadoPor: j['creado_por'] == null ? null : (j['creado_por'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    resueltoPor: j['resuelto_por'] == null ? null : (j['resuelto_por'] as num).toInt(),
    resueltoEn: j['resuelto_en'] == null ? null : j['resuelto_en'] as String,
    motivo: j['motivo'] == null ? null : j['motivo'] as String,
    escaladoEn: j['escalado_en'] == null ? null : j['escalado_en'] as String,
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    cliente: j['cliente'] == null ? null : j['cliente'] as String,
    deNombre: j['de_nombre'] == null ? null : j['de_nombre'] as String,
    aNombre: j['a_nombre'] == null ? null : j['a_nombre'] as String,
    deOficina: j['de_oficina'] == null ? null : j['de_oficina'] as String,
    aOficina: j['a_oficina'] == null ? null : j['a_oficina'] as String,
    proximoVencimiento: j['proximo_vencimiento'] == null ? null : j['proximo_vencimiento'] as String,
    diasAlVencimiento: j['dias_al_vencimiento'] == null ? null : (j['dias_al_vencimiento'] as num).toInt(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'cliente_fiscal_id': ?clienteFiscalId,
    'de_usuario_id': ?deUsuarioId,
    'a_usuario_id': ?aUsuarioId,
    'de_oficina_id': ?deOficinaId,
    'a_oficina_id': ?aOficinaId,
    'nota': ?nota,
    'estado': ?estado,
    'creado_por': ?creadoPor,
    'creado_en': ?creadoEn,
    'resuelto_por': ?resueltoPor,
    'resuelto_en': ?resueltoEn,
    'motivo': ?motivo,
    'escalado_en': ?escaladoEn,
    'version': ?version,
    'cliente': ?cliente,
    'de_nombre': ?deNombre,
    'a_nombre': ?aNombre,
    'de_oficina': ?deOficina,
    'a_oficina': ?aOficina,
    'proximo_vencimiento': ?proximoVencimiento,
    'dias_al_vencimiento': ?diasAlVencimiento,
  };
  Traspaso copyWith({int? id, int? clienteFiscalId, int? deUsuarioId, int? aUsuarioId, int? deOficinaId, int? aOficinaId, String? nota, String? estado, int? creadoPor, String? creadoEn, int? resueltoPor, String? resueltoEn, String? motivo, String? escaladoEn, int? version, String? cliente, String? deNombre, String? aNombre, String? deOficina, String? aOficina, String? proximoVencimiento, int? diasAlVencimiento, }) => Traspaso(id: id ?? this.id, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, deUsuarioId: deUsuarioId ?? this.deUsuarioId, aUsuarioId: aUsuarioId ?? this.aUsuarioId, deOficinaId: deOficinaId ?? this.deOficinaId, aOficinaId: aOficinaId ?? this.aOficinaId, nota: nota ?? this.nota, estado: estado ?? this.estado, creadoPor: creadoPor ?? this.creadoPor, creadoEn: creadoEn ?? this.creadoEn, resueltoPor: resueltoPor ?? this.resueltoPor, resueltoEn: resueltoEn ?? this.resueltoEn, motivo: motivo ?? this.motivo, escaladoEn: escaladoEn ?? this.escaladoEn, version: version ?? this.version, cliente: cliente ?? this.cliente, deNombre: deNombre ?? this.deNombre, aNombre: aNombre ?? this.aNombre, deOficina: deOficina ?? this.deOficina, aOficina: aOficina ?? this.aOficina, proximoVencimiento: proximoVencimiento ?? this.proximoVencimiento, diasAlVencimiento: diasAlVencimiento ?? this.diasAlVencimiento, );
  @override bool operator ==(Object other) => other is Traspaso && other.id == id && other.clienteFiscalId == clienteFiscalId && other.deUsuarioId == deUsuarioId && other.aUsuarioId == aUsuarioId && other.deOficinaId == deOficinaId && other.aOficinaId == aOficinaId && other.nota == nota && other.estado == estado && other.creadoPor == creadoPor && other.creadoEn == creadoEn && other.resueltoPor == resueltoPor && other.resueltoEn == resueltoEn && other.motivo == motivo && other.escaladoEn == escaladoEn && other.version == version && other.cliente == cliente && other.deNombre == deNombre && other.aNombre == aNombre && other.deOficina == deOficina && other.aOficina == aOficina && other.proximoVencimiento == proximoVencimiento && other.diasAlVencimiento == diasAlVencimiento;
  @override int get hashCode => Object.hashAll([id, clienteFiscalId, deUsuarioId, aUsuarioId, deOficinaId, aOficinaId, nota, estado, creadoPor, creadoEn, resueltoPor, resueltoEn, motivo, escaladoEn, version, cliente, deNombre, aNombre, deOficina, aOficina, proximoVencimiento, diasAlVencimiento]);
}

class TurnoAsignado {
  final String? fecha;
  final int? turnoId;
  final String? nombre;
  final String? inicio;
  final String? fin;
  final String? color;
  final double? horas;
  const TurnoAsignado({this.fecha, this.turnoId, this.nombre, this.inicio, this.fin, this.color, this.horas, });
  factory TurnoAsignado.fromJson(Map<String, dynamic> j) => TurnoAsignado(
    fecha: j['fecha'] == null ? null : j['fecha'] as String,
    turnoId: j['turno_id'] == null ? null : (j['turno_id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    inicio: j['inicio'] == null ? null : j['inicio'] as String,
    fin: j['fin'] == null ? null : j['fin'] as String,
    color: j['color'] == null ? null : j['color'] as String,
    horas: j['horas'] == null ? null : (j['horas'] as num).toDouble(),
  );
  Map<String, dynamic> toJson() => {
    'fecha': ?fecha,
    'turno_id': ?turnoId,
    'nombre': ?nombre,
    'inicio': ?inicio,
    'fin': ?fin,
    'color': ?color,
    'horas': ?horas,
  };
  TurnoAsignado copyWith({String? fecha, int? turnoId, String? nombre, String? inicio, String? fin, String? color, double? horas, }) => TurnoAsignado(fecha: fecha ?? this.fecha, turnoId: turnoId ?? this.turnoId, nombre: nombre ?? this.nombre, inicio: inicio ?? this.inicio, fin: fin ?? this.fin, color: color ?? this.color, horas: horas ?? this.horas, );
  @override bool operator ==(Object other) => other is TurnoAsignado && other.fecha == fecha && other.turnoId == turnoId && other.nombre == nombre && other.inicio == inicio && other.fin == fin && other.color == color && other.horas == horas;
  @override int get hashCode => Object.hashAll([fecha, turnoId, nombre, inicio, fin, color, horas]);
}

class TurnoTipo {
  final int id;
  final String? nombre;
  final String? inicio;
  final String? fin;
  final String? color;
  final int? archivado;
  final String? creadoEn;
  final double? horas;
  const TurnoTipo({required this.id, this.nombre, this.inicio, this.fin, this.color, this.archivado, this.creadoEn, this.horas, });
  factory TurnoTipo.fromJson(Map<String, dynamic> j) => TurnoTipo(
    id: (j['id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    inicio: j['inicio'] == null ? null : j['inicio'] as String,
    fin: j['fin'] == null ? null : j['fin'] as String,
    color: j['color'] == null ? null : j['color'] as String,
    archivado: j['archivado'] == null ? null : (j['archivado'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    horas: j['horas'] == null ? null : (j['horas'] as num).toDouble(),
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'nombre': ?nombre,
    'inicio': ?inicio,
    'fin': ?fin,
    'color': ?color,
    'archivado': ?archivado,
    'creado_en': ?creadoEn,
    'horas': ?horas,
  };
  TurnoTipo copyWith({int? id, String? nombre, String? inicio, String? fin, String? color, int? archivado, String? creadoEn, double? horas, }) => TurnoTipo(id: id ?? this.id, nombre: nombre ?? this.nombre, inicio: inicio ?? this.inicio, fin: fin ?? this.fin, color: color ?? this.color, archivado: archivado ?? this.archivado, creadoEn: creadoEn ?? this.creadoEn, horas: horas ?? this.horas, );
  @override bool operator ==(Object other) => other is TurnoTipo && other.id == id && other.nombre == nombre && other.inicio == inicio && other.fin == fin && other.color == color && other.archivado == archivado && other.creadoEn == creadoEn && other.horas == horas;
  @override int get hashCode => Object.hashAll([id, nombre, inicio, fin, color, archivado, creadoEn, horas]);
}

class Usuario {
  final int? id;
  final String? email;
  final int? tenantId;
  final String? tenant;
  final int? despachoActivo;
  final List<DespachoDeUsuario>? despachos;
  final Map<String, dynamic>? modulos;
  final Map<String, dynamic>? permisos;
  final Map<String, dynamic>? cifrado;
  final Apariencia? apariencia;
  final InfoAppMovil? app;
  const Usuario({this.id, this.email, this.tenantId, this.tenant, this.despachoActivo, this.despachos, this.modulos, this.permisos, this.cifrado, this.apariencia, this.app, });
  factory Usuario.fromJson(Map<String, dynamic> j) => Usuario(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    email: j['email'] == null ? null : j['email'] as String,
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    tenant: j['tenant'] == null ? null : j['tenant'] as String,
    despachoActivo: j['despacho_activo'] == null ? null : (j['despacho_activo'] as num).toInt(),
    despachos: j['despachos'] == null ? null : (j['despachos'] as List).map((e) => DespachoDeUsuario.fromJson(e as Map<String, dynamic>)).toList(),
    modulos: j['modulos'] == null ? null : Map<String, dynamic>.from(j['modulos'] as Map),
    permisos: j['permisos'] == null ? null : Map<String, dynamic>.from(j['permisos'] as Map),
    cifrado: j['cifrado'] == null ? null : Map<String, dynamic>.from(j['cifrado'] as Map),
    apariencia: j['apariencia'] == null ? null : Apariencia.fromJson(j['apariencia'] as Map<String, dynamic>),
    app: j['app'] == null ? null : InfoAppMovil.fromJson(j['app'] as Map<String, dynamic>),
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'email': ?email,
    'tenant_id': ?tenantId,
    'tenant': ?tenant,
    'despacho_activo': ?despachoActivo,
    if (despachos != null) 'despachos': despachos!.map((e) => e.toJson()).toList(),
    'modulos': ?modulos,
    'permisos': ?permisos,
    'cifrado': ?cifrado,
    if (apariencia != null) 'apariencia': apariencia!.toJson(),
    if (app != null) 'app': app!.toJson(),
  };
  Usuario copyWith({int? id, String? email, int? tenantId, String? tenant, int? despachoActivo, List<DespachoDeUsuario>? despachos, Map<String, dynamic>? modulos, Map<String, dynamic>? permisos, Map<String, dynamic>? cifrado, Apariencia? apariencia, InfoAppMovil? app, }) => Usuario(id: id ?? this.id, email: email ?? this.email, tenantId: tenantId ?? this.tenantId, tenant: tenant ?? this.tenant, despachoActivo: despachoActivo ?? this.despachoActivo, despachos: despachos ?? this.despachos, modulos: modulos ?? this.modulos, permisos: permisos ?? this.permisos, cifrado: cifrado ?? this.cifrado, apariencia: apariencia ?? this.apariencia, app: app ?? this.app, );
  @override bool operator ==(Object other) => other is Usuario && other.id == id && other.email == email && other.tenantId == tenantId && other.tenant == tenant && other.despachoActivo == despachoActivo && other.despachos == despachos && other.modulos == modulos && other.permisos == permisos && other.cifrado == cifrado && other.apariencia == apariencia && other.app == app;
  @override int get hashCode => Object.hashAll([id, email, tenantId, tenant, despachoActivo, despachos, modulos, permisos, cifrado, apariencia, app]);
}

class Vencimiento {
  final int id;
  final int? tenantId;
  final int? clienteFiscalId;
  final int? usuarioId;
  final String? modelo;
  final String? periodo;
  final String? fechaLimite;
  final String? estado;
  final String? notas;
  final String? creadoEn;
  final String? actualizadoEn;
  final String? papeleraEn;
  final String? recordatorioEnviadoEn;
  final String? documensoDocumentoId;
  final String? documentoSolicitado;
  final String? fase;
  final String? faseMotivo;
  final int? presentadaTarde;
  final int? bloqueada;
  final String? bloqueoMotivo;
  final int? version;
  final int? rectificaA;
  final int? trabajadorId;
  final String? clienteNombre;
  const Vencimiento({required this.id, this.tenantId, this.clienteFiscalId, this.usuarioId, this.modelo, this.periodo, this.fechaLimite, this.estado, this.notas, this.creadoEn, this.actualizadoEn, this.papeleraEn, this.recordatorioEnviadoEn, this.documensoDocumentoId, this.documentoSolicitado, this.fase, this.faseMotivo, this.presentadaTarde, this.bloqueada, this.bloqueoMotivo, this.version, this.rectificaA, this.trabajadorId, this.clienteNombre, });
  factory Vencimiento.fromJson(Map<String, dynamic> j) => Vencimiento(
    id: (j['id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    clienteFiscalId: j['cliente_fiscal_id'] == null ? null : (j['cliente_fiscal_id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    modelo: j['modelo'] == null ? null : j['modelo'] as String,
    periodo: j['periodo'] == null ? null : j['periodo'] as String,
    fechaLimite: j['fecha_limite'] == null ? null : j['fecha_limite'] as String,
    estado: j['estado'] == null ? null : j['estado'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    actualizadoEn: j['actualizado_en'] == null ? null : j['actualizado_en'] as String,
    papeleraEn: j['papelera_en'] == null ? null : j['papelera_en'] as String,
    recordatorioEnviadoEn: j['recordatorio_enviado_en'] == null ? null : j['recordatorio_enviado_en'] as String,
    documensoDocumentoId: j['documenso_documento_id'] == null ? null : j['documenso_documento_id'] as String,
    documentoSolicitado: j['documento_solicitado'] == null ? null : j['documento_solicitado'] as String,
    fase: j['fase'] == null ? null : j['fase'] as String,
    faseMotivo: j['fase_motivo'] == null ? null : j['fase_motivo'] as String,
    presentadaTarde: j['presentada_tarde'] == null ? null : (j['presentada_tarde'] as num).toInt(),
    bloqueada: j['bloqueada'] == null ? null : (j['bloqueada'] as num).toInt(),
    bloqueoMotivo: j['bloqueo_motivo'] == null ? null : j['bloqueo_motivo'] as String,
    version: j['version'] == null ? null : (j['version'] as num).toInt(),
    rectificaA: j['rectifica_a'] == null ? null : (j['rectifica_a'] as num).toInt(),
    trabajadorId: j['trabajador_id'] == null ? null : (j['trabajador_id'] as num).toInt(),
    clienteNombre: j['cliente_nombre'] == null ? null : j['cliente_nombre'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tenant_id': ?tenantId,
    'cliente_fiscal_id': ?clienteFiscalId,
    'usuario_id': ?usuarioId,
    'modelo': ?modelo,
    'periodo': ?periodo,
    'fecha_limite': ?fechaLimite,
    'estado': ?estado,
    'notas': ?notas,
    'creado_en': ?creadoEn,
    'actualizado_en': ?actualizadoEn,
    'papelera_en': ?papeleraEn,
    'recordatorio_enviado_en': ?recordatorioEnviadoEn,
    'documenso_documento_id': ?documensoDocumentoId,
    'documento_solicitado': ?documentoSolicitado,
    'fase': ?fase,
    'fase_motivo': ?faseMotivo,
    'presentada_tarde': ?presentadaTarde,
    'bloqueada': ?bloqueada,
    'bloqueo_motivo': ?bloqueoMotivo,
    'version': ?version,
    'rectifica_a': ?rectificaA,
    'trabajador_id': ?trabajadorId,
    'cliente_nombre': ?clienteNombre,
  };
  Vencimiento copyWith({int? id, int? tenantId, int? clienteFiscalId, int? usuarioId, String? modelo, String? periodo, String? fechaLimite, String? estado, String? notas, String? creadoEn, String? actualizadoEn, String? papeleraEn, String? recordatorioEnviadoEn, String? documensoDocumentoId, String? documentoSolicitado, String? fase, String? faseMotivo, int? presentadaTarde, int? bloqueada, String? bloqueoMotivo, int? version, int? rectificaA, int? trabajadorId, String? clienteNombre, }) => Vencimiento(id: id ?? this.id, tenantId: tenantId ?? this.tenantId, clienteFiscalId: clienteFiscalId ?? this.clienteFiscalId, usuarioId: usuarioId ?? this.usuarioId, modelo: modelo ?? this.modelo, periodo: periodo ?? this.periodo, fechaLimite: fechaLimite ?? this.fechaLimite, estado: estado ?? this.estado, notas: notas ?? this.notas, creadoEn: creadoEn ?? this.creadoEn, actualizadoEn: actualizadoEn ?? this.actualizadoEn, papeleraEn: papeleraEn ?? this.papeleraEn, recordatorioEnviadoEn: recordatorioEnviadoEn ?? this.recordatorioEnviadoEn, documensoDocumentoId: documensoDocumentoId ?? this.documensoDocumentoId, documentoSolicitado: documentoSolicitado ?? this.documentoSolicitado, fase: fase ?? this.fase, faseMotivo: faseMotivo ?? this.faseMotivo, presentadaTarde: presentadaTarde ?? this.presentadaTarde, bloqueada: bloqueada ?? this.bloqueada, bloqueoMotivo: bloqueoMotivo ?? this.bloqueoMotivo, version: version ?? this.version, rectificaA: rectificaA ?? this.rectificaA, trabajadorId: trabajadorId ?? this.trabajadorId, clienteNombre: clienteNombre ?? this.clienteNombre, );
  @override bool operator ==(Object other) => other is Vencimiento && other.id == id && other.tenantId == tenantId && other.clienteFiscalId == clienteFiscalId && other.usuarioId == usuarioId && other.modelo == modelo && other.periodo == periodo && other.fechaLimite == fechaLimite && other.estado == estado && other.notas == notas && other.creadoEn == creadoEn && other.actualizadoEn == actualizadoEn && other.papeleraEn == papeleraEn && other.recordatorioEnviadoEn == recordatorioEnviadoEn && other.documensoDocumentoId == documensoDocumentoId && other.documentoSolicitado == documentoSolicitado && other.fase == fase && other.faseMotivo == faseMotivo && other.presentadaTarde == presentadaTarde && other.bloqueada == bloqueada && other.bloqueoMotivo == bloqueoMotivo && other.version == version && other.rectificaA == rectificaA && other.trabajadorId == trabajadorId && other.clienteNombre == clienteNombre;
  @override int get hashCode => Object.hashAll([id, tenantId, clienteFiscalId, usuarioId, modelo, periodo, fechaLimite, estado, notas, creadoEn, actualizadoEn, papeleraEn, recordatorioEnviadoEn, documensoDocumentoId, documentoSolicitado, fase, faseMotivo, presentadaTarde, bloqueada, bloqueoMotivo, version, rectificaA, trabajadorId, clienteNombre]);
}

class VersionJuridica {
  final Map<String, dynamic>? documento;
  final Map<String, dynamic>? version;
  final String? fechaJuridica;
  final List<String>? huecos;
  final List<Map<String, dynamic>>? fragmentos;
  const VersionJuridica({this.documento, this.version, this.fechaJuridica, this.huecos, this.fragmentos, });
  factory VersionJuridica.fromJson(Map<String, dynamic> j) => VersionJuridica(
    documento: j['documento'] == null ? null : Map<String, dynamic>.from(j['documento'] as Map),
    version: j['version'] == null ? null : Map<String, dynamic>.from(j['version'] as Map),
    fechaJuridica: j['fecha_juridica'] == null ? null : j['fecha_juridica'] as String,
    huecos: j['huecos'] == null ? null : (j['huecos'] as List).map((e) => e as String).toList(),
    fragmentos: j['fragmentos'] == null ? null : (j['fragmentos'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
  );
  Map<String, dynamic> toJson() => {
    'documento': ?documento,
    'version': ?version,
    'fecha_juridica': ?fechaJuridica,
    if (huecos != null) 'huecos': huecos!.map((e) => e).toList(),
    if (fragmentos != null) 'fragmentos': fragmentos!.map((e) => e).toList(),
  };
  VersionJuridica copyWith({Map<String, dynamic>? documento, Map<String, dynamic>? version, String? fechaJuridica, List<String>? huecos, List<Map<String, dynamic>>? fragmentos, }) => VersionJuridica(documento: documento ?? this.documento, version: version ?? this.version, fechaJuridica: fechaJuridica ?? this.fechaJuridica, huecos: huecos ?? this.huecos, fragmentos: fragmentos ?? this.fragmentos, );
  @override bool operator ==(Object other) => other is VersionJuridica && other.documento == documento && other.version == version && other.fechaJuridica == fechaJuridica && other.huecos == huecos && other.fragmentos == fragmentos;
  @override int get hashCode => Object.hashAll([documento, version, fechaJuridica, huecos, fragmentos]);
}

class VisibleCliente {
  final bool? visibleCliente;
  final bool? comentariosCliente;
  const VisibleCliente({this.visibleCliente, this.comentariosCliente, });
  factory VisibleCliente.fromJson(Map<String, dynamic> j) => VisibleCliente(
    visibleCliente: j['visible_cliente'] == null ? null : _aBool(j['visible_cliente']),
    comentariosCliente: j['comentarios_cliente'] == null ? null : _aBool(j['comentarios_cliente']),
  );
  Map<String, dynamic> toJson() => {
    'visible_cliente': ?visibleCliente,
    'comentarios_cliente': ?comentariosCliente,
  };
  VisibleCliente copyWith({bool? visibleCliente, bool? comentariosCliente, }) => VisibleCliente(visibleCliente: visibleCliente ?? this.visibleCliente, comentariosCliente: comentariosCliente ?? this.comentariosCliente, );
  @override bool operator ==(Object other) => other is VisibleCliente && other.visibleCliente == visibleCliente && other.comentariosCliente == comentariosCliente;
  @override int get hashCode => Object.hashAll([visibleCliente, comentariosCliente]);
}

class VisitaAgenda {
  final int? id;
  final int? inmuebleId;
  final String? fechaHora;
  final String? direccion;
  final String? municipio;
  final String? visitanteNombre;
  final String? agenteNombre;
  const VisitaAgenda({this.id, this.inmuebleId, this.fechaHora, this.direccion, this.municipio, this.visitanteNombre, this.agenteNombre, });
  factory VisitaAgenda.fromJson(Map<String, dynamic> j) => VisitaAgenda(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    inmuebleId: j['inmueble_id'] == null ? null : (j['inmueble_id'] as num).toInt(),
    fechaHora: j['fecha_hora'] == null ? null : j['fecha_hora'] as String,
    direccion: j['direccion'] == null ? null : j['direccion'] as String,
    municipio: j['municipio'] == null ? null : j['municipio'] as String,
    visitanteNombre: j['visitante_nombre'] == null ? null : j['visitante_nombre'] as String,
    agenteNombre: j['agente_nombre'] == null ? null : j['agente_nombre'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'inmueble_id': ?inmuebleId,
    'fecha_hora': ?fechaHora,
    'direccion': ?direccion,
    'municipio': ?municipio,
    'visitante_nombre': ?visitanteNombre,
    'agente_nombre': ?agenteNombre,
  };
  VisitaAgenda copyWith({int? id, int? inmuebleId, String? fechaHora, String? direccion, String? municipio, String? visitanteNombre, String? agenteNombre, }) => VisitaAgenda(id: id ?? this.id, inmuebleId: inmuebleId ?? this.inmuebleId, fechaHora: fechaHora ?? this.fechaHora, direccion: direccion ?? this.direccion, municipio: municipio ?? this.municipio, visitanteNombre: visitanteNombre ?? this.visitanteNombre, agenteNombre: agenteNombre ?? this.agenteNombre, );
  @override bool operator ==(Object other) => other is VisitaAgenda && other.id == id && other.inmuebleId == inmuebleId && other.fechaHora == fechaHora && other.direccion == direccion && other.municipio == municipio && other.visitanteNombre == visitanteNombre && other.agenteNombre == agenteNombre;
  @override int get hashCode => Object.hashAll([id, inmuebleId, fechaHora, direccion, municipio, visitanteNombre, agenteNombre]);
}

class Vista {
  final int? id;
  final String? nombre;
  final Map<String, dynamic>? filtros;
  final bool? compartida;
  final bool? mia;
  final String? autor;
  const Vista({this.id, this.nombre, this.filtros, this.compartida, this.mia, this.autor, });
  factory Vista.fromJson(Map<String, dynamic> j) => Vista(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    nombre: j['nombre'] == null ? null : j['nombre'] as String,
    filtros: j['filtros'] == null ? null : Map<String, dynamic>.from(j['filtros'] as Map),
    compartida: j['compartida'] == null ? null : _aBool(j['compartida']),
    mia: j['mia'] == null ? null : _aBool(j['mia']),
    autor: j['autor'] == null ? null : j['autor'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'nombre': ?nombre,
    'filtros': ?filtros,
    'compartida': ?compartida,
    'mia': ?mia,
    'autor': ?autor,
  };
  Vista copyWith({int? id, String? nombre, Map<String, dynamic>? filtros, bool? compartida, bool? mia, String? autor, }) => Vista(id: id ?? this.id, nombre: nombre ?? this.nombre, filtros: filtros ?? this.filtros, compartida: compartida ?? this.compartida, mia: mia ?? this.mia, autor: autor ?? this.autor, );
  @override bool operator ==(Object other) => other is Vista && other.id == id && other.nombre == nombre && other.filtros == filtros && other.compartida == compartida && other.mia == mia && other.autor == autor;
  @override int get hashCode => Object.hashAll([id, nombre, filtros, compartida, mia, autor]);
}

class VistaAgenda {
  final int? id;
  final int? expedienteId;
  final String? fechaHora;
  final String? tipo;
  final String? lugar;
  final String? notas;
  final String? asunto;
  const VistaAgenda({this.id, this.expedienteId, this.fechaHora, this.tipo, this.lugar, this.notas, this.asunto, });
  factory VistaAgenda.fromJson(Map<String, dynamic> j) => VistaAgenda(
    id: j['id'] == null ? null : (j['id'] as num).toInt(),
    expedienteId: j['expediente_id'] == null ? null : (j['expediente_id'] as num).toInt(),
    fechaHora: j['fecha_hora'] == null ? null : j['fecha_hora'] as String,
    tipo: j['tipo'] == null ? null : j['tipo'] as String,
    lugar: j['lugar'] == null ? null : j['lugar'] as String,
    notas: j['notas'] == null ? null : j['notas'] as String,
    asunto: j['asunto'] == null ? null : j['asunto'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': ?id,
    'expediente_id': ?expedienteId,
    'fecha_hora': ?fechaHora,
    'tipo': ?tipo,
    'lugar': ?lugar,
    'notas': ?notas,
    'asunto': ?asunto,
  };
  VistaAgenda copyWith({int? id, int? expedienteId, String? fechaHora, String? tipo, String? lugar, String? notas, String? asunto, }) => VistaAgenda(id: id ?? this.id, expedienteId: expedienteId ?? this.expedienteId, fechaHora: fechaHora ?? this.fechaHora, tipo: tipo ?? this.tipo, lugar: lugar ?? this.lugar, notas: notas ?? this.notas, asunto: asunto ?? this.asunto, );
  @override bool operator ==(Object other) => other is VistaAgenda && other.id == id && other.expedienteId == expedienteId && other.fechaHora == fechaHora && other.tipo == tipo && other.lugar == lugar && other.notas == notas && other.asunto == asunto;
  @override int get hashCode => Object.hashAll([id, expedienteId, fechaHora, tipo, lugar, notas, asunto]);
}

class Webhook {
  final int id;
  final int? tenantId;
  final int? usuarioId;
  final String? url;
  final List<String>? eventos;
  final int? activo;
  final String? creadoEn;
  final String? origen;
  const Webhook({required this.id, this.tenantId, this.usuarioId, this.url, this.eventos, this.activo, this.creadoEn, this.origen, });
  factory Webhook.fromJson(Map<String, dynamic> j) => Webhook(
    id: (j['id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    url: j['url'] == null ? null : j['url'] as String,
    eventos: j['eventos'] == null ? null : (j['eventos'] as List).map((e) => e as String).toList(),
    activo: j['activo'] == null ? null : (j['activo'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    origen: j['origen'] == null ? null : j['origen'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tenant_id': ?tenantId,
    'usuario_id': ?usuarioId,
    'url': ?url,
    if (eventos != null) 'eventos': eventos!.map((e) => e).toList(),
    'activo': ?activo,
    'creado_en': ?creadoEn,
    'origen': ?origen,
  };
  Webhook copyWith({int? id, int? tenantId, int? usuarioId, String? url, List<String>? eventos, int? activo, String? creadoEn, String? origen, }) => Webhook(id: id ?? this.id, tenantId: tenantId ?? this.tenantId, usuarioId: usuarioId ?? this.usuarioId, url: url ?? this.url, eventos: eventos ?? this.eventos, activo: activo ?? this.activo, creadoEn: creadoEn ?? this.creadoEn, origen: origen ?? this.origen, );
  @override bool operator ==(Object other) => other is Webhook && other.id == id && other.tenantId == tenantId && other.usuarioId == usuarioId && other.url == url && other.eventos == eventos && other.activo == activo && other.creadoEn == creadoEn && other.origen == origen;
  @override int get hashCode => Object.hashAll([id, tenantId, usuarioId, url, eventos, activo, creadoEn, origen]);
}

class WebhookCreado {
  final int id;
  final int? tenantId;
  final int? usuarioId;
  final String? url;
  final List<String>? eventos;
  final int? activo;
  final String? creadoEn;
  final String? origen;
  final String? secreto;
  const WebhookCreado({required this.id, this.tenantId, this.usuarioId, this.url, this.eventos, this.activo, this.creadoEn, this.origen, this.secreto, });
  factory WebhookCreado.fromJson(Map<String, dynamic> j) => WebhookCreado(
    id: (j['id'] as num).toInt(),
    tenantId: j['tenant_id'] == null ? null : (j['tenant_id'] as num).toInt(),
    usuarioId: j['usuario_id'] == null ? null : (j['usuario_id'] as num).toInt(),
    url: j['url'] == null ? null : j['url'] as String,
    eventos: j['eventos'] == null ? null : (j['eventos'] as List).map((e) => e as String).toList(),
    activo: j['activo'] == null ? null : (j['activo'] as num).toInt(),
    creadoEn: j['creado_en'] == null ? null : j['creado_en'] as String,
    origen: j['origen'] == null ? null : j['origen'] as String,
    secreto: j['secreto'] == null ? null : j['secreto'] as String,
  );
  Map<String, dynamic> toJson() => {
    'id': id,
    'tenant_id': ?tenantId,
    'usuario_id': ?usuarioId,
    'url': ?url,
    if (eventos != null) 'eventos': eventos!.map((e) => e).toList(),
    'activo': ?activo,
    'creado_en': ?creadoEn,
    'origen': ?origen,
    'secreto': ?secreto,
  };
  WebhookCreado copyWith({int? id, int? tenantId, int? usuarioId, String? url, List<String>? eventos, int? activo, String? creadoEn, String? origen, String? secreto, }) => WebhookCreado(id: id ?? this.id, tenantId: tenantId ?? this.tenantId, usuarioId: usuarioId ?? this.usuarioId, url: url ?? this.url, eventos: eventos ?? this.eventos, activo: activo ?? this.activo, creadoEn: creadoEn ?? this.creadoEn, origen: origen ?? this.origen, secreto: secreto ?? this.secreto, );
  @override bool operator ==(Object other) => other is WebhookCreado && other.id == id && other.tenantId == tenantId && other.usuarioId == usuarioId && other.url == url && other.eventos == eventos && other.activo == activo && other.creadoEn == creadoEn && other.origen == origen && other.secreto == secreto;
  @override int get hashCode => Object.hashAll([id, tenantId, usuarioId, url, eventos, activo, creadoEn, origen, secreto]);
}

