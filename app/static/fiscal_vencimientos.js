/* Vencimientos de Guilda Fiscal: el buscador y los botones de modelo filtran la tabla en el momento (sin acentos ni mayúsculas). Sin JavaScript se ve todo, igual que antes. */
(function () {
  var filas = document.querySelectorAll('tr[data-buscar]'), campo = document.querySelector('[data-buscar-campo]'), botones = document.querySelectorAll('[data-filtro-modelo]'), vacio = document.querySelector('[data-sin-resultados]');
  if (!filas.length) return;
  var modelo = '';
  function limpio(t) { return (t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim(); }
  var textos = Array.prototype.map.call(filas, function (f) { return limpio(f.getAttribute('data-buscar')); });
  function filtrar() {
    var palabras = campo ? limpio(campo.value).split(/\s+/).filter(Boolean) : [], visibles = 0;
    filas.forEach(function (f, i) {
      var ok = (!modelo || f.getAttribute('data-modelo') === modelo) && palabras.every(function (p) { return textos[i].indexOf(p) >= 0; });
      f.hidden = !ok;
      if (ok) visibles++;
    });
    if (vacio) vacio.hidden = visibles > 0;
  }
  botones.forEach(function (b) {
    b.addEventListener('click', function () {
      modelo = b.getAttribute('data-filtro-modelo');
      botones.forEach(function (o) { o.setAttribute('aria-pressed', o === b ? 'true' : 'false'); });
      filtrar();
    });
  });
  if (campo) campo.addEventListener('input', filtrar);
})();
