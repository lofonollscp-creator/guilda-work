/// El servidor emite fechas `AAAA-MM-DD` y momentos `AAAA-MM-DDTHH:MM[:SS]`
/// en hora local de Madrid **sin zona**. No se pasan por `DateTime.parse` en
/// las pantallas: los cambios de hora (marzo/octubre) corrompen cualquier
/// aritmética hecha con una zona inventada. Estos tipos de valor guardan los
/// componentes tal cual llegan.
class Fecha implements Comparable<Fecha> {
  final int anio, mes, dia;
  const Fecha(this.anio, this.mes, this.dia);

  static final _re = RegExp(r'^(\d{4})-(\d{2})-(\d{2})');

  /// Acepta `AAAA-MM-DD` o un momento (se queda con el día). null si no cuadra.
  static Fecha? intentar(String? s) {
    final m = s == null ? null : _re.firstMatch(s);
    if (m == null) return null;
    final f = Fecha(int.parse(m[1]!), int.parse(m[2]!), int.parse(m[3]!));
    return f.esValida ? f : null;
  }

  static Fecha parse(String s) => intentar(s) ?? (throw FormatException('Fecha no válida', s));

  bool get esValida => mes >= 1 && mes <= 12 && dia >= 1 && dia <= _diasDelMes(anio, mes);

  /// Día de la semana, 1 = lunes ... 7 = domingo (como `DateTime.weekday`).
  int get diaSemana => DateTime.utc(anio, mes, dia).weekday;

  /// Días entre dos fechas calendario; en UTC, así que no lo alteran los cambios de hora.
  int diasHasta(Fecha otra) => DateTime.utc(otra.anio, otra.mes, otra.dia).difference(DateTime.utc(anio, mes, dia)).inDays;

  Fecha masDias(int n) {
    final d = DateTime.utc(anio, mes, dia).add(Duration(days: n));
    return Fecha(d.year, d.month, d.day);
  }

  /// Para el servidor.
  String toJson() => '${_n(anio, 4)}-${_n(mes)}-${_n(dia)}';

  @override
  int compareTo(Fecha o) => anio != o.anio ? anio.compareTo(o.anio) : (mes != o.mes ? mes.compareTo(o.mes) : dia.compareTo(o.dia));

  @override
  bool operator ==(Object other) => other is Fecha && other.anio == anio && other.mes == mes && other.dia == dia;

  @override
  int get hashCode => Object.hash(anio, mes, dia);

  @override
  String toString() => toJson();
}

/// Fecha y hora local sin zona (ver [Fecha]).
class MomentoLocal implements Comparable<MomentoLocal> {
  final Fecha fecha;
  final int hora, minuto, segundo;
  const MomentoLocal(this.fecha, this.hora, this.minuto, [this.segundo = 0]);

  static final _re = RegExp(r'^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?');

  static MomentoLocal? intentar(String? s) {
    final m = s == null ? null : _re.firstMatch(s);
    if (m == null) return null;
    final f = Fecha.intentar(m[1]);
    final h = int.parse(m[2]!), mi = int.parse(m[3]!), se = int.tryParse(m[4] ?? '0') ?? 0;
    if (f == null || h > 23 || mi > 59 || se > 59) return null;
    return MomentoLocal(f, h, mi, se);
  }

  static MomentoLocal parse(String s) => intentar(s) ?? (throw FormatException('Momento no válido', s));

  /// Para el servidor: `AAAA-MM-DDTHH:MM` (con segundos solo si los hay).
  String toJson() => '${fecha.toJson()}T${_n(hora)}:${_n(minuto)}${segundo == 0 ? '' : ':${_n(segundo)}'}';

  @override
  int compareTo(MomentoLocal o) {
    final c = fecha.compareTo(o.fecha);
    return c != 0 ? c : (hora * 3600 + minuto * 60 + segundo).compareTo(o.hora * 3600 + o.minuto * 60 + o.segundo);
  }

  @override
  bool operator ==(Object other) =>
      other is MomentoLocal && other.fecha == fecha && other.hora == hora && other.minuto == minuto && other.segundo == segundo;

  @override
  int get hashCode => Object.hash(fecha, hora, minuto, segundo);

  @override
  String toString() => toJson();
}

String _n(int v, [int ancho = 2]) => v.toString().padLeft(ancho, '0');

int _diasDelMes(int anio, int mes) => DateTime.utc(anio, mes + 1, 0).day;
