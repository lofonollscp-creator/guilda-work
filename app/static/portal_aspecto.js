// Aspecto del portal a gusto de cada persona: tema (sistema, claro u oscuro), tamaño de letra y «pantallas sencillas» (letra grande y solo lo principal en la barra). Se guarda solo en este navegador. Se carga en la cabecera para aplicarse antes de pintar la página.
(function () {
  var TEMA = 'guilda-work-tema', LETRA = 'guilda-work-letra', SENCILLO = 'guilda-work-sencillo', LETRAS = ['normal', 'grande', 'muy-grande'];
  function leer(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento: vale para esta página */ } }
  var raiz = document.documentElement;

  // El color de la barra del navegador en el móvil sigue al tema elegido (sin elegir, lo deciden las dos etiquetas con media= de la cabecera).
  var COLOR_BARRA = { light: '#f5f6f8', dark: '#16140f' };
  function aplicarTema(t) {
    if (t === 'light' || t === 'dark') raiz.setAttribute('data-theme', t); else raiz.removeAttribute('data-theme');
    var m = document.querySelector('meta[data-tema-color]');
    if (m && COLOR_BARRA[t]) { m.setAttribute('content', COLOR_BARRA[t]); m.removeAttribute('media'); } else if (m) m.setAttribute('media', 'not all');
  }
  function temaActual() { var v = leer(TEMA); return v === 'light' || v === 'dark' ? v : 'system'; }
  function marcarSelectores() {
    var actual = temaActual();
    Array.prototype.forEach.call(document.querySelectorAll('[data-tema]'), function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-tema') === actual ? 'true' : 'false'); });
    Array.prototype.forEach.call(document.querySelectorAll('input[name="aspecto-tema"]'), function (r) { r.checked = r.value === actual; });
  }
  function sencillo() { return leer(SENCILLO) === '1'; }
  // En las pantallas sencillas la letra nunca baja de «grande»: es lo que más ayuda a quien las activa.
  function aplicarLetra(l) { if (LETRAS.indexOf(l) > 0) raiz.setAttribute('data-letra', l); else if (sencillo()) raiz.setAttribute('data-letra', 'grande'); else raiz.removeAttribute('data-letra'); }
  function aplicarSencillo(v) { if (v) raiz.setAttribute('data-sencillo', '1'); else raiz.removeAttribute('data-sencillo'); }
  aplicarTema(leer(TEMA));
  aplicarSencillo(sencillo());
  aplicarLetra(leer(LETRA));

  document.addEventListener('DOMContentLoaded', function () {
    aplicarTema(leer(TEMA));
    var temas = document.querySelector('[data-temas]');                      // selector rápido del menú de perfil: solo tiene sentido con JS
    if (temas) {
      temas.hidden = false;
      Array.prototype.forEach.call(temas.querySelectorAll('[data-tema]'), function (b) {
        b.addEventListener('click', function () { var v = b.getAttribute('data-tema'); guardar(TEMA, v); aplicarTema(v); marcarSelectores(); });
      });
      marcarSelectores();
    }
    var bloque = document.getElementById('aspecto');
    if (!bloque) return;
    var caja = document.getElementById('aspecto-sencillo');
    if (caja) {
      caja.checked = sencillo();
      caja.addEventListener('change', function () { guardar(SENCILLO, caja.checked ? '1' : '0'); aplicarSencillo(caja.checked); aplicarLetra(leer(LETRA)); });
    }
    [['aspecto-tema', TEMA, aplicarTema, function (v) { return v === 'light' || v === 'dark' ? v : 'system'; }], ['aspecto-letra', LETRA, aplicarLetra, function (v) { return LETRAS.indexOf(v) >= 0 ? v : 'normal'; }]].forEach(function (g) {
      var radios = bloque.querySelectorAll('input[name="' + g[0] + '"]'), actual = g[3](leer(g[1]));
      Array.prototype.forEach.call(radios, function (r) {
        r.checked = r.value === actual;
        r.addEventListener('change', function () { if (r.checked) { guardar(g[1], r.value); g[2](r.value); marcarSelectores(); } });
      });
    });
  });
})();
