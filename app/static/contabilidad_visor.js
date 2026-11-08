// Visor del documento en la pantalla de revisión de una factura: páginas del PDF, zoom y el recuadro (aproximado) de donde la IA leyó cada dato. Al enfocar un campo del formulario se resalta su recuadro.
(function () {
  var raiz = document.querySelector('[data-visor-revision]');
  var imagen = document.querySelector('[data-visor-imagen]');
  if (!raiz || !imagen) return;
  var hoja = document.querySelector('[data-visor-hoja]');
  var lienzo = document.querySelector('[data-visor-lienzo]');
  var caja = document.querySelector('[data-visor-caja]');
  var estado = document.querySelector('[data-visor-estado]');
  var paginas = parseInt(imagen.dataset.paginas || '1', 10);
  var esPdf = imagen.dataset.tipo === 'pdf';
  var pagina = 1, zoom = 1;
  var evidencias = {};
  try { evidencias = JSON.parse((document.getElementById('visor-evidencias') || {}).textContent || '{}'); } catch (e) { evidencias = {}; }

  // Mientras llega la imagen (o la página siguiente) la hoja enseña un esqueleto en vez de un hueco en blanco.
  function esperar() { if (!imagen.complete) hoja.classList.add('cargando'); }
  function listo() { hoja.classList.remove('cargando'); }
  imagen.addEventListener('load', listo); imagen.addEventListener('error', listo);
  esperar();
  function aplicarZoom() { hoja.style.width = (zoom * 100) + '%'; }
  function ocultarCaja() { caja.hidden = true; }
  function dibujar(c) {
    if (pagina !== 1 || !c || c.length !== 4) { ocultarCaja(); return; }
    caja.style.left = (c[0] * 100) + '%'; caja.style.top = (c[1] * 100) + '%';
    caja.style.width = ((c[2] - c[0]) * 100) + '%'; caja.style.height = ((c[3] - c[1]) * 100) + '%';
    caja.hidden = false;
    var r = caja.getBoundingClientRect(), l = lienzo.getBoundingClientRect();
    if (r.top < l.top || r.bottom > l.bottom) lienzo.scrollTop += r.top - l.top - l.height / 3;
  }
  function irA(n) {
    pagina = Math.max(1, Math.min(paginas, n));
    ocultarCaja();
    if (esPdf) imagen.src = imagen.dataset.url.replace(/\/0$/, '/' + pagina);
    esperar();
    imagen.alt = 'Página ' + pagina + ' de ' + paginas;
    if (estado) estado.textContent = pagina + ' / ' + paginas;
    lienzo.scrollTop = 0;
  }
  document.querySelectorAll('[data-visor-pagina]').forEach(function (b) {
    b.addEventListener('click', function () { irA(pagina + parseInt(b.dataset.visorPagina, 10)); });
  });
  document.querySelectorAll('[data-visor-zoom]').forEach(function (b) {
    b.addEventListener('click', function () {
      var d = parseInt(b.dataset.visorZoom, 10);
      zoom = d === 0 ? 1 : Math.max(0.5, Math.min(3, zoom + d * 0.25));
      aplicarZoom();
    });
  });
  lienzo.addEventListener('keydown', function (e) {
    var paso = 60;
    if (e.key === 'ArrowDown') { lienzo.scrollTop += paso; e.preventDefault(); }
    else if (e.key === 'ArrowUp') { lienzo.scrollTop -= paso; e.preventDefault(); }
    else if (e.key === 'PageDown' && esPdf && paginas > 1) { irA(pagina + 1); e.preventDefault(); }
    else if (e.key === 'PageUp' && esPdf && paginas > 1) { irA(pagina - 1); e.preventDefault(); }
  });
  document.querySelectorAll('[data-evidencia-ver]').forEach(function (b) {
    b.addEventListener('click', function () {
      var v = b.dataset.evidenciaVer.split(',').map(parseFloat);
      if (v.length === 4 && !v.some(isNaN)) { if (pagina !== 1) irA(1); dibujar(v); }
    });
  });
  document.querySelectorAll('[data-evidencia-campo]').forEach(function (campo) {
    function mostrar() { var e = evidencias[campo.dataset.evidenciaCampo]; if (e) dibujar(e.caja); }
    campo.addEventListener('focus', mostrar);
    campo.addEventListener('mouseenter', mostrar);
    campo.addEventListener('blur', ocultarCaja);
  });
  aplicarZoom();
})();
