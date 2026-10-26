/* Cartera de Guilda Fiscal: el buscador filtra la tabla mientras se escribe (sin acentos ni mayúsculas, por nombre o NIF). Sin JavaScript, el formulario recarga la página con el mismo filtro. */
(function () {
  var campo = document.querySelector('[data-buscar-campo]'), filas = document.querySelectorAll('tr[data-buscar]'), vacio = document.querySelector('[data-sin-resultados]');
  if (!campo || !filas.length) return;
  function limpio(t) { return (t || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim(); }
  var textos = Array.prototype.map.call(filas, function (f) { return limpio(f.getAttribute('data-buscar')); });
  function filtrar() {
    var palabras = limpio(campo.value).split(/\s+/).filter(Boolean), visibles = 0;
    filas.forEach(function (f, i) {
      var ok = palabras.every(function (p) { return textos[i].indexOf(p) >= 0; });
      f.hidden = !ok;
      if (ok) visibles++;
    });
    if (vacio) vacio.hidden = visibles > 0;
  }
  campo.addEventListener('input', filtrar);
  filtrar();
})();
