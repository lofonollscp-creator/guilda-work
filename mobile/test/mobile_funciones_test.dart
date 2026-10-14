import 'package:flutter_test/flutter_test.dart';

import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/services/api_client.dart';

void main() {
  ausenciasTests();
  group('verificación en dos pasos', () {
    test('el código requiere_2fa de la API se reconoce', () {
      expect(ApiException('falta el código', codigo: 'requiere_2fa').requiere2fa, true);
      expect(ApiException('Email o contraseña incorrectos.', codigo: 'no_autorizado').requiere2fa, false);
      expect(ApiException('sin código').requiere2fa, false);
    });
  });

  group('resumen semanal de fichaje', () {
    test('lee la respuesta de la API con jornada contratada', () {
      final r = ResumenSemanaFichaje.fromJson({
        'segundos': 90000,
        'contratados': 144000,
        'diferencia': -54000,
        'porcentaje': 63,
        'en_curso': true,
        'dias': [
          {'fecha': '2026-10-12', 'segundos': 28800, 'hoy': false},
          {'fecha': '2026-10-13', 'segundos': 3600.5, 'hoy': true},
        ],
      });
      expect(r.porcentaje, 63);
      expect(r.excedida, false);
      expect(r.dias.length, 2);
      expect(r.dias.last.hoy, true);
      expect(r.dias.last.segundos, 3600.5);
    });

    test('sin jornada contratada no hay porcentaje ni exceso', () {
      final r = ResumenSemanaFichaje.fromJson({'segundos': 100, 'contratados': null, 'diferencia': null, 'porcentaje': null, 'en_curso': false, 'dias': []});
      expect(r.contratados, null);
      expect(r.porcentaje, null);
      expect(r.excedida, false);
    });

    test('se detecta que se pasa de la jornada', () {
      final r = ResumenSemanaFichaje.fromJson({'segundos': 150000, 'contratados': 144000, 'diferencia': 6000, 'porcentaje': 100, 'en_curso': false, 'dias': []});
      expect(r.excedida, true);
    });

    test('formatoHoras redondea a minutos y rellena los ceros', () {
      expect(formatoHoras(0), '0 h 00 min');
      expect(formatoHoras(25500), '7 h 05 min');
      expect(formatoHoras(3599), '1 h 00 min');
    });
  });

  group('tareas compartidas', () {
    Map<String, dynamic> base() => {'id': 1, 'asunto': 'Revisar IVA', 'estado': 'no_iniciada', 'prioridad': 'normal'};

    test('el rol solo viene si se pidió otro ámbito', () {
      expect(TareaOutlook.fromJson(base()).rol, null);
      expect(TareaOutlook.fromJson({...base(), 'rol': 'compartida'}).rol, 'compartida');
      expect(TareaOutlook.fromJson({...base(), 'rol': 'asignada'}).rol, 'asignada');
    });
  });
}

void ausenciasTests() {
  group('ausencias y vacaciones', () {
    test('lee una ausencia de la API', () {
      final a = Ausencia.fromJson({'id': 3, 'tipo': 'vacaciones', 'desde': '2027-03-01', 'hasta': '2027-03-05', 'medio_dia': 0, 'dias': 5.0, 'motivo': null, 'estado': 'pendiente', 'comentario': null});
      expect(a.dias, 5.0);
      expect(a.medioDia, false);
      expect(formatoDias(a.dias), '5');
      expect(formatoDias(0.5), '0.5');
    });

    test('solo se cancela lo vivo y que no ha terminado', () {
      final hoy = DateTime(2027, 3, 3);
      Ausencia con(String estado, String hasta) => Ausencia.fromJson({'id': 1, 'tipo': 'permiso', 'desde': '2027-03-01', 'hasta': hasta, 'medio_dia': 0, 'dias': 1, 'estado': estado});
      expect(con('pendiente', '2027-03-05').puedeCancelarse(hoy), true);
      expect(con('aprobada', '2027-03-03').puedeCancelarse(hoy), true);
      expect(con('aprobada', '2027-03-02').puedeCancelarse(hoy), false);
      expect(con('rechazada', '2027-03-05').puedeCancelarse(hoy), false);
      expect(con('cancelada', '2027-03-05').puedeCancelarse(hoy), false);
    });

    test('lee el saldo del año', () {
      final s = SaldoAusencias.fromJson({'anio': 2027, 'total': 22, 'aprobadas': 5.0, 'pendientes': 0.5, 'disponibles': 16.5});
      expect(s.anio, 2027);
      expect(s.disponibles, 16.5);
    });
  });
}
