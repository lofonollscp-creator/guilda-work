import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/screens/ajustes_screen.dart';
import 'package:guilda_work_mobile/screens/ausencias_screen.dart';
import 'package:guilda_work_mobile/screens/correo_compose_screen.dart';
import 'package:guilda_work_mobile/screens/fichaje_datos_screen.dart';
import 'package:guilda_work_mobile/screens/fichaje_historial_screen.dart';
import 'package:guilda_work_mobile/screens/login_screen.dart';
import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:guilda_work_mobile/services/locale_service.dart';
import 'package:guilda_work_mobile/services/push_service.dart';
import 'package:guilda_work_mobile/services/session_service.dart';
import 'package:guilda_work_mobile/services/sync_service.dart';
import 'package:guilda_work_mobile/services/theme_service.dart';

import 'ayudas/pantallas.dart';

/// Las pantallas que quedaban por revisar del rediseño, dibujadas con el tema y las fuentes reales (solo con `CAPTURAS=<carpeta>`).
void main() {
  setUpAll(cargarFuentesParaCapturas);
  final carpeta = carpetaCapturas;

  final pantallas = <String, Widget Function(ApiFalsa api)>{
    'login': (api) => LoginScreen(api: api, sesion: SessionService(), sync: SyncService(), push: PushService(api), tema: ThemeService(), locale: LocaleService()),
    'ajustes': (api) => AjustesScreen(api: api, usuario: Usuario(id: 1, email: 'ana@gestoria.com'), sesion: SessionService(), sync: SyncService(), push: PushService(api), tema: ThemeService(), locale: LocaleService()),
    'redactar': (api) => CorreoComposeScreen(api: api, cuentaIdInicial: 1),
    'historial': (api) => FichajeHistorialScreen(api: api),
    'datos_fichaje': (api) => FichajeDatosScreen(api: api),
    'ausencias': (api) => AusenciasScreen(api: api),
  };

  for (final oscuro in [false, true]) {
    final sufijo = oscuro ? 'oscuro' : 'claro';
    for (final e in pantallas.entries) {
      testWidgets('captura ${e.key} $sufijo', (t) async {
        if (carpeta == null) return;
        sinVoz();
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final api = ApiFalsa()
          ..eventos = [ev(1, 'entrada', '08:58'), ev(2, 'pausa_inicio', '11:00'), ev(3, 'pausa_fin', '11:15'), ev(4, 'salida', '17:30')]
          ..datosFichaje = FichajeDatos(nombreCompleto: 'Ana Pérez Soler', dniNie: '12345678Z', categoriaProfesional: 'Técnica fiscal', tipoContrato: 'indefinido', jornadaSemanalHoras: 40)
          ..ausencias = [
            Ausencia(id: 1, tipo: 'vacaciones', desde: '2026-12-21', hasta: '2026-12-31', medioDia: false, dias: 7, estado: 'aprobada'),
            Ausencia(id: 2, tipo: 'asuntos_propios', desde: '2026-11-13', hasta: '2026-11-13', medioDia: true, dias: 0.5, estado: 'pendiente', motivo: 'Gestión personal'),
          ];
        await t.pumpWidget(appDePantalla(e.value(api), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, '${e.key}_$sufijo');
      });
    }
  }
}
