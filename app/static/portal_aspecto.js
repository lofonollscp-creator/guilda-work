// Aspecto del portal a gusto de cada persona: tema (sistema, claro u oscuro) y tamaño de letra. Se guarda solo en este navegador. Se carga en la cabecera para aplicarse antes de pintar la página.
(function () {
  var TEMA = 'guilda-work-tema', LETRA = 'guilda-work-letra', LETRAS = ['normal', 'grande', 'muy-grande'];
  function leer(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento: vale para esta página */ } }
  var raiz = document.documentElement;

  function aplicarTema(t) { if (t === 'light' || t === 'dark') raiz.setAttribute('data-theme', t); else raiz.removeAttribute('data-theme'); }
  function aplicarLetra(l) { if (LETRAS.indexOf(l) > 0) raiz.setAttribute('data-letra', l); else raiz.removeAttribute('data-letra'); }
  aplicarTema(leer(TEMA));
  aplicarLetra(leer(LETRA));

  document.addEventListener('DOMContentLoaded', function () {
    var bloque = document.getElementById('aspecto');
    if (!bloque) return;
    [['aspecto-tema', TEMA, aplicarTema, function (v) { return v === 'light' || v === 'dark' ? v : 'system'; }], ['aspecto-letra', LETRA, aplicarLetra, function (v) { return LETRAS.indexOf(v) >= 0 ? v : 'normal'; }]].forEach(function (g) {
      var radios = bloque.querySelectorAll('input[name="' + g[0] + '"]'), actual = g[3](leer(g[1]));
      Array.prototype.forEach.call(radios, function (r) {
        r.checked = r.value === actual;
        r.addEventListener('change', function () { if (r.checked) { guardar(g[1], r.value); g[2](r.value); } });
      });
    });
  });
})();
