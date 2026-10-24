import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/screens/login_screen.dart';
import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:guilda_work_mobile/services/locale_service.dart';
import 'package:guilda_work_mobile/services/push_service.dart';
import 'package:guilda_work_mobile/services/session_service.dart';
import 'package:guilda_work_mobile/services/sync_service.dart';
import 'package:guilda_work_mobile/services/theme_service.dart';
import 'package:mocktail/mocktail.dart';

class _Api extends Mock implements ApiClient {}

class _Sesion extends Mock implements SessionService {}

class _Push extends Mock implements PushService {}

void main() {
  late _Api api;
  late _Sesion sesion;
  late List<Usuario> entradas;

  setUp(() {
    api = _Api();
    sesion = _Sesion();
    entradas = [];
    when(() => sesion.guardarToken(any())).thenAnswer((_) async {});
    when(() => sesion.obtenerServidor()).thenAnswer((_) async => 'https://servidor.prueba');
  });

  Widget pantalla() => MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('es'),
        home: LoginScreen(api: api, sesion: sesion, sync: SyncService(), push: _Push(), tema: ThemeService(), locale: LocaleService(), alIniciarSesion: entradas.add),
      );

  void loginDevuelve(Future<(String, Usuario)> Function(String, String, String?) f) =>
      when(() => api.login(any(), any(), codigo2fa: any(named: 'codigo2fa'))).thenAnswer((i) => f(i.positionalArguments[0] as String, i.positionalArguments[1] as String, i.namedArguments[#codigo2fa] as String?));

  group('credenciales', () {
    testWidgets('pide correo y contraseña con ayuda del gestor de contraseñas y del teclado', (t) async {
      await t.pumpWidget(pantalla());
      final campos = t.widgetList<TextField>(find.byType(TextField)).toList();
      expect(campos.length, 2);
      expect(campos[0].autofillHints, containsAll([AutofillHints.username, AutofillHints.email]));
      expect(campos[0].keyboardType, TextInputType.emailAddress);
      expect(campos[0].textInputAction, TextInputAction.next);
      expect(campos[1].autofillHints, [AutofillHints.password]);
      expect(campos[1].textInputAction, TextInputAction.done);
      expect(campos[1].obscureText, true);
      expect(find.byType(AutofillGroup), findsOneWidget);
    });

    testWidgets('mostrar y ocultar la contraseña, con su etiqueta para lectores de pantalla', (t) async {
      await t.pumpWidget(pantalla());
      expect(find.byTooltip('Mostrar contraseña'), findsOneWidget);
      await t.tap(find.byTooltip('Mostrar contraseña'));
      await t.pump();
      expect(t.widgetList<TextField>(find.byType(TextField)).last.obscureText, false);
      expect(find.byTooltip('Ocultar contraseña'), findsOneWidget);
    });

    testWidgets('sin registro público: se explica que el acceso es por invitación', (t) async {
      await t.pumpWidget(pantalla());
      expect(registroPublicoEnApp, false);
      expect(find.text('¿No tienes cuenta? Regístrate'), findsNothing);
      await t.tap(find.text('¿Tu despacho te ha invitado?'));
      await t.pumpAndSettle();
      expect(find.text('El acceso es por invitación'), findsOneWidget);
      await t.tap(find.text('Entendido'));
      await t.pumpAndSettle();
      expect(find.text('El acceso es por invitación'), findsNothing);
    });

    testWidgets('entrar guarda el token y avisa con el usuario', (t) async {
      loginDevuelve((e, c, d) async => ('tok', Usuario(id: 3, email: e)));
      await t.pumpWidget(pantalla());
      await t.enterText(find.byType(TextField).first, '  ana@gestoria.com ');
      await t.enterText(find.byType(TextField).last, 'secreta-123');
      await t.tap(find.text('Entrar'));
      await t.pumpAndSettle();
      verify(() => api.login('ana@gestoria.com', 'secreta-123', codigo2fa: null)).called(1);
      verify(() => sesion.guardarToken('tok')).called(1);
      expect(entradas.single.id, 3);
    });

    testWidgets('con la tecla «hecho» del teclado también entra', (t) async {
      loginDevuelve((e, c, d) async => ('tok', Usuario(id: 1, email: e)));
      await t.pumpWidget(pantalla());
      await t.enterText(find.byType(TextField).first, 'a@b.c');
      await t.enterText(find.byType(TextField).last, 'x');
      await t.testTextInput.receiveAction(TextInputAction.done);
      await t.pumpAndSettle();
      expect(entradas.length, 1);
    });

    testWidgets('credenciales erróneas: el mensaje del servidor, sin salir de la pantalla', (t) async {
      loginDevuelve((e, c, d) async => throw ApiException('Credenciales incorrectas.'));
      await t.pumpWidget(pantalla());
      await t.enterText(find.byType(TextField).first, 'a@b.c');
      await t.enterText(find.byType(TextField).last, 'mala');
      await t.tap(find.text('Entrar'));
      await t.pumpAndSettle();
      expect(find.text('Credenciales incorrectas.'), findsOneWidget);
      expect(entradas, isEmpty);
    });

    testWidgets('pulsación larga en el logotipo: ajustes del servidor', (t) async {
      await t.pumpWidget(pantalla());
      await t.longPress(find.byType(Image).first);
      await t.pumpAndSettle();
      expect(find.text('URL base (ej. http://10.0.2.2:8000)'), findsOneWidget);
    });
  });

  group('verificación en dos pasos', () {
    Future<void> hastaElCodigo(WidgetTester t) async {
      await t.pumpWidget(pantalla());
      await t.enterText(find.byType(TextField).first, 'ana@gestoria.com');
      await t.enterText(find.byType(TextField).last, 'secreta-123');
      await t.tap(find.text('Entrar'));
      await t.pumpAndSettle();
    }

    testWidgets('pasa a una pantalla propia que pide solo el código (y lo autocompleta desde SMS o app)', (t) async {
      loginDevuelve((e, c, d) async => d == null ? throw ApiException('Falta el código', codigo: 'requiere_2fa') : ('tok', Usuario(id: 1, email: e)));
      await hastaElCodigo(t);
      expect(find.text('Verificación en dos pasos'), findsOneWidget);
      final campos = t.widgetList<TextField>(find.byType(TextField)).toList();
      expect(campos.length, 1); // ya no están el correo ni la contraseña
      expect(campos.single.autofillHints, [AutofillHints.oneTimeCode]);
      expect(campos.single.keyboardType, TextInputType.number);
    });

    testWidgets('con 6 cifras se envía solo', (t) async {
      loginDevuelve((e, c, d) async => d == null ? throw ApiException('x', codigo: 'requiere_2fa') : ('tok', Usuario(id: 9, email: e)));
      await hastaElCodigo(t);
      await t.enterText(find.byType(TextField), '12345');
      await t.pump();
      verifyNever(() => api.login(any(), any(), codigo2fa: '12345'));
      await t.enterText(find.byType(TextField), '123456');
      await t.pumpAndSettle();
      verify(() => api.login('ana@gestoria.com', 'secreta-123', codigo2fa: '123456')).called(1);
      expect(entradas.single.id, 9);
    });

    testWidgets('solo admite cifras y máximo 6', (t) async {
      loginDevuelve((e, c, d) async => throw ApiException('x', codigo: 'requiere_2fa'));
      await hastaElCodigo(t);
      await t.enterText(find.byType(TextField), '12ab34567890');
      await t.pump();
      expect(t.widget<TextField>(find.byType(TextField)).controller!.text, '123456');
    });

    testWidgets('un código incorrecto enseña el error y vacía el campo para reintentar', (t) async {
      loginDevuelve((e, c, d) async => d == null ? throw ApiException('x', codigo: 'requiere_2fa') : throw ApiException('Código incorrecto.'));
      await hastaElCodigo(t);
      await t.enterText(find.byType(TextField), '000000');
      await t.pumpAndSettle();
      expect(find.text('Código incorrecto.'), findsOneWidget);
      expect(t.widget<TextField>(find.byType(TextField)).controller!.text, '');
      expect(entradas, isEmpty);
    });

    testWidgets('un código de recuperación lleva letras: teclado de texto y sin envío automático', (t) async {
      loginDevuelve((e, c, d) async => throw ApiException('x', codigo: 'requiere_2fa'));
      await hastaElCodigo(t);
      await t.tap(find.text('Usar un código de recuperación'));
      await t.pumpAndSettle();
      expect(t.widget<TextField>(find.byType(TextField)).keyboardType, TextInputType.visiblePassword);
      clearInteractions(api);
      await t.enterText(find.byType(TextField), 'abcd-efgh');
      await t.pump();
      verifyNever(() => api.login(any(), any(), codigo2fa: any(named: 'codigo2fa')));
      expect(find.text('Usar el código de la app'), findsOneWidget);
    });

    testWidgets('«usar otra cuenta» vuelve a las credenciales y borra la contraseña', (t) async {
      loginDevuelve((e, c, d) async => throw ApiException('x', codigo: 'requiere_2fa'));
      await hastaElCodigo(t);
      await t.ensureVisible(find.text('Usar otra cuenta')); // en una pantalla baja queda bajo el pliegue: se desplaza
      await t.tap(find.text('Usar otra cuenta'));
      await t.pumpAndSettle();
      final campos = t.widgetList<TextField>(find.byType(TextField)).toList();
      expect(campos.length, 2);
      expect(campos.last.controller!.text, '');
      expect(campos.first.controller!.text, 'ana@gestoria.com'); // el correo se conserva
    });
  });
}
