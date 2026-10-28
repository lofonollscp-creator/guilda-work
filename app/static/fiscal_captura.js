// Captura desde el móvil: reduce las fotos antes de subirlas (las del móvil pasan de 8 MB) y activa el botón cuando hay algo que subir.
// Si el navegador no sabe reducirlas, se suben tal cual y el servidor decide.
(function () {
  var MAX_LADO = 2200, CALIDAD = 0.85, LIMITE = 7.5 * 1024 * 1024;
  var formulario = document.querySelector('[data-captura]');
  if (!formulario) return;
  var entradas = formulario.querySelectorAll('[data-captura-entrada]');
  var resumen = formulario.querySelector('[data-captura-resumen]');
  var enviar = formulario.querySelector('[data-captura-enviar]');

  function reducir(archivo) {
    if (!/^image\/(jpeg|png|webp)$/.test(archivo.type) || archivo.size < 1.5 * 1024 * 1024 || !window.createImageBitmap) return Promise.resolve(archivo);
    return createImageBitmap(archivo).then(function (img) {
      var escala = Math.min(1, MAX_LADO / Math.max(img.width, img.height));
      var lienzo = document.createElement('canvas');
      lienzo.width = Math.round(img.width * escala);
      lienzo.height = Math.round(img.height * escala);
      lienzo.getContext('2d').drawImage(img, 0, 0, lienzo.width, lienzo.height);
      return new Promise(function (resolver) {
        lienzo.toBlob(function (blob) {
          if (!blob || blob.size >= archivo.size) return resolver(archivo);
          resolver(new File([blob], archivo.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' }));
        }, 'image/jpeg', CALIDAD);
      });
    }).catch(function () { return archivo; });
  }

  var acumulados = [];

  function actualizar() {
    var transfer = new DataTransfer();
    acumulados.forEach(function (f) { transfer.items.add(f); });
    // todos los archivos viajan en la primera entrada; las demás se vacían para no mandarlos dos veces
    entradas[0].files = transfer.files;
    for (var i = 1; i < entradas.length; i++) entradas[i].value = '';
    var grandes = acumulados.filter(function (f) { return f.size > LIMITE; }).length;
    var maximo = parseInt(formulario.getAttribute('data-max') || '10', 10);
    resumen.textContent = acumulados.length + ' · ' + (acumulados.reduce(function (s, f) { return s + f.size; }, 0) / 1048576).toFixed(1) + ' MB'
      + (grandes ? ' · ' + grandes + ' > 8 MB' : '') + (acumulados.length > maximo ? ' · máx. ' + maximo : '');
    enviar.disabled = acumulados.length === 0 || grandes > 0 || acumulados.length > maximo;
  }

  entradas.forEach(function (e) {
    e.addEventListener('change', function () {
      var nuevos = Array.prototype.slice.call(e.files);
      if (!window.DataTransfer) { enviar.disabled = false; return; }
      Promise.all(nuevos.map(reducir)).then(function (reducidos) {
        // cada foto nueva se SUMA a las ya hechas (el navegador vacía la selección anterior al abrir otra vez la cámara)
        acumulados = acumulados.concat(reducidos);
        actualizar();
      });
    });
  });
})();
