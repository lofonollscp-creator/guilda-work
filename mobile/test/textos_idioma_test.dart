import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/textos_idioma.dart';
import 'package:guilda_work_mobile/models/models.dart';

void main() {
  test('los textos sin pantalla (errores de red) salen en el idioma de la app', () {
    expect(textosEnIdioma('es').apiSinConexion, startsWith('No se ha podido conectar'));
    expect(textosEnIdioma('ca').apiSinConexion, startsWith('No s’ha pogut connectar'));
    expect(textosEnIdioma('en').apiSinConexion, startsWith('Could not connect'));
    expect(textosEnIdioma('fr').apiSinConexion, startsWith('Impossible de se connecter'));
    expect(textosEnIdioma('en').apiErrorRed('timeout'), 'Network error: timeout');
    expect(textosEnIdioma('fr').apiErrorHttp(502), 'Erreur 502');
  });

  test('un idioma sin traducción cae al castellano', () {
    expect(textosEnIdioma('de').apiPeticionCancelada, 'Petición cancelada.');
    expect(textosEnIdioma('').apiPeticionCancelada, 'Petición cancelada.');
  });

  test('los modelos fiscales llevan su descripción en cada idioma y el código no cambia', () {
    expect(modelosFiscalesDisponibles, ['303', '130', '111', '115', '390', '200']);
    expect(descripcionModeloFiscal(textosEnIdioma('es'), '303'), 'IVA - Declaración trimestral');
    expect(descripcionModeloFiscal(textosEnIdioma('en'), '303'), 'VAT - Quarterly return');
    expect(descripcionModeloFiscal(textosEnIdioma('fr'), '200'), 'Impôt sur les sociétés');
    expect(descripcionModeloFiscal(textosEnIdioma('ca'), '115'), 'Retencions lloguers');
  });
}
