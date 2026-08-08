import 'package:flutter_test/flutter_test.dart';

import 'package:guilda_work_mobile/services/api_client.dart';

void main() {
  test('ApiException distingue error de conexión de error de negocio', () {
    final deNegocio = ApiException('No se puede fichar "entrada" viniendo de "entrada".');
    expect(deNegocio.esDeConexion, false);

    final deConexion = ApiException('No se ha podido conectar con el servidor.', esDeConexion: true);
    expect(deConexion.esDeConexion, true);
  });
}
