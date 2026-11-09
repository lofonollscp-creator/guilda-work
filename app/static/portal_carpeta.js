// Carpeta del portal: filtro por texto y tipo (sin recargar) y vista previa del documento en un cuadro de diálogo.
(function () {
  var docs = Array.prototype.slice.call(document.querySelectorAll('[data-doc]'));
  var texto = document.querySelector('[data-filtro-texto]'), tipo = document.querySelector('[data-filtro-tipo]'), estado = document.querySelector('[data-filtro-estado]');
  function sinTildes(t) { return (t || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
  function filtrar() {
    var q = sinTildes(texto ? texto.value : ''), t = tipo ? tipo.value : '', visibles = 0;
    docs.forEach(function (d) {
      var ok = (!t || d.getAttribute('data-tipo') === t) && (!q || sinTildes(d.getAttribute('data-texto')).indexOf(q) >= 0);
      d.hidden = !ok; if (ok) visibles++;
    });
    if (estado) estado.textContent = (q || t) ? (visibles + ' / ' + docs.length) : '';
  }
  if (texto) texto.addEventListener('input', filtrar);
  if (tipo) tipo.addEventListener('change', filtrar);

  document.querySelectorAll('[data-seleccionar]').forEach(function (i) { i.addEventListener('click', function () { i.select(); }); });

  var dialogo = document.getElementById('car-vista');
  if (!dialogo || !dialogo.showModal) return;
  var marco = dialogo.querySelector('[data-vista-marco]'), titulo = document.getElementById('car-vista-titulo'), abridor = null;
  document.querySelectorAll('[data-ver]').forEach(function (b) {
    b.addEventListener('click', function () {
      abridor = b; titulo.textContent = b.getAttribute('data-nombre') || ''; marco.src = b.getAttribute('data-ver'); dialogo.showModal();
    });
  });
  dialogo.querySelector('[data-cerrar-vista]').addEventListener('click', function () { dialogo.close(); });
  dialogo.addEventListener('close', function () { marco.src = 'about:blank'; if (abridor) abridor.focus(); });
  dialogo.addEventListener('click', function (e) { if (e.target === dialogo) dialogo.close(); });
})();
