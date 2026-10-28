// Evidencias de la lectura con IA: al pulsar «Ver en la imagen» se dibuja el recuadro aproximado que dio el modelo sobre la foto de la factura.
(function () {
  var contenedor = document.querySelector('[data-evidencia-imagen]');
  if (!contenedor) return;
  var caja = contenedor.querySelector('[data-evidencia-caja]');
  contenedor.style.position = 'relative';
  contenedor.style.display = 'inline-block';
  contenedor.style.maxWidth = '100%';
  caja.style.position = 'absolute';
  caja.style.border = '3px solid #d9822b';
  caja.style.background = 'rgba(217, 130, 43, 0.18)';
  caja.style.borderRadius = '3px';
  caja.style.pointerEvents = 'none';
  document.querySelectorAll('[data-evidencia-ver]').forEach(function (boton) {
    boton.addEventListener('click', function () {
      var v = boton.getAttribute('data-evidencia-ver').split(',').map(parseFloat);
      if (v.length !== 4 || v.some(isNaN)) return;
      caja.style.left = (v[0] * 100) + '%';
      caja.style.top = (v[1] * 100) + '%';
      caja.style.width = ((v[2] - v[0]) * 100) + '%';
      caja.style.height = ((v[3] - v[1]) * 100) + '%';
      caja.hidden = false;
      caja.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  });
})();
