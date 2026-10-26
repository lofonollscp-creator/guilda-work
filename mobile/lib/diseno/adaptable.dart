import 'package:flutter/material.dart';

/// Desde este ancho (dp) la app se maqueta para tableta: barra lateral en vez de la inferior, lista y ficha lado a lado, tablero con todas las columnas.
const anchoTableta = 720.0;

/// El ancho máximo del conjunto de la app: en una pantalla muy ancha el contenido no se estira.
const anchoMaximoApp = 1180.0;

/// El ancho cómodo de lectura de las pantallas de formulario o de texto.
const anchoMaximoLectura = 680.0;

/// Tableta = ancho suficiente **y** lado corto de tableta: un móvil apaisado (muy ancho, poco alto) conserva el diseño de móvil.
bool esAncha(BuildContext context) {
  final tam = MediaQuery.sizeOf(context);
  return tam.width >= anchoTableta && tam.shortestSide > 600;
}

/// Centra [child] con un ancho máximo (sin efecto en un móvil).
class AnchoMaximo extends StatelessWidget {
  final double ancho;
  final Widget child;
  const AnchoMaximo({super.key, this.ancho = anchoMaximoLectura, required this.child});

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(constraints: BoxConstraints(maxWidth: ancho), child: child),
      );
}
