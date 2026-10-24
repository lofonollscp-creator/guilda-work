import '../diseno/tokens.g.dart';

/// Paleta de marca de Guilda Work. **Ya no se copia a mano**: sale de las variables
/// CSS de la web (`app/static/style.css`) a través de `diseno/tokens.g.dart`, que
/// genera `scripts/exportar_tokens_dart.py` (y el CI comprueba que no se desfasa).
/// Esta clase conserva los nombres que ya usan las pantallas.
///
/// Texto: sobre fondo claro usa siempre los tonos `*Text` (contraste AA); los demás
/// (`dangerLight`, `warningLight`...) son para fondos, bordes e iconos.
class BrandColors {
  BrandColors._();

  // --primary / --primary-dark
  static const primaryLight = TokensClaro.primary;
  static const primaryDarkAccent = TokensClaro.primaryDark; // --primary-dark en claro
  static const primaryDark = TokensOscuro.primary;
  static const primaryDarkAccentDark = TokensOscuro.primaryDark; // --primary-dark en oscuro

  // --primary-text: el lima como TEXTO (en claro, un olivo con contraste AA).
  static const primaryTextLight = TokensClaro.primaryText;
  static const primaryTextDark = TokensOscuro.primaryText;

  // --on-accent: texto sobre --primary, igual en los dos temas.
  static const onAccent = TokensClaro.onAccent;

  static const bgLight = TokensClaro.bg;
  static const surfaceLight = TokensClaro.surface;
  static const borderLight = TokensClaro.border;

  static const bgDark = TokensOscuro.bg;
  static const surfaceDark = TokensOscuro.surface;
  static const borderDark = TokensOscuro.border;

  static const textLight = TokensClaro.text;
  static const textMutedLight = TokensClaro.textMuted;
  static const textDark = TokensOscuro.text;
  static const textMutedDark = TokensOscuro.textMuted;

  static const dangerLight = TokensClaro.danger;
  static const dangerDark = TokensOscuro.danger;
  static const success = TokensClaro.success;
  static const warningLight = TokensClaro.warning;
  static const warningDark = TokensOscuro.warning;

  // Versiones para TEXTO (>= 4,5:1).
  static const dangerTextLight = TokensClaro.dangerText;
  static const dangerTextDark = TokensOscuro.dangerText;
  static const successTextLight = TokensClaro.successText;
  static const successTextDark = TokensOscuro.successText;
  static const warningTextLight = TokensClaro.warningText;
  static const warningTextDark = TokensOscuro.warningText;

  // Radios: los mismos que la web (--radius-sm / --radius-md / --radius-lg).
  static const radius = TokensMedidas.radioMedio; // 12
  static const radiusSmall = TokensMedidas.radioPequeno; // 10
  static const radiusLarge = TokensMedidas.radioGrande; // 22
}
