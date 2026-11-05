// Avisos al elegir facturas en el portal: archivos que no valen, repetidos y fotos borrosas. Solo avisan, nunca bloquean el envío.
(function () {
  var form = document.getElementById('form-subida');
  if (!form) return;
  var entrada = form.querySelector('input[type=file]');
  var lista = document.getElementById('avisos-subida');
  var TIPOS = ['application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp'];
  var MAX = 8 * 1024 * 1024;
  var UMBRAL_BORROSA = 60;

  function texto(clave, valores) {
    var t = form.getAttribute('data-txt-' + clave) || '';
    Object.keys(valores).forEach(function (k) { t = t.replace('%(' + k + ')s', valores[k]); });
    return t;
  }
  function avisar(mensaje) {
    var li = document.createElement('li');
    li.textContent = mensaje;
    lista.appendChild(li);
  }
  function huella(archivo) {
    if (!window.crypto || !crypto.subtle || !archivo.arrayBuffer) return Promise.resolve(null);
    return archivo.arrayBuffer().then(function (b) { return crypto.subtle.digest('SHA-256', b); }).then(function (h) {
      return Array.prototype.map.call(new Uint8Array(h), function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
    }).catch(function () { return null; });
  }
  // Varianza del laplaciano de la foto reducida: una foto nítida de un documento da cientos; una movida, muy poco.
  function nitidez(archivo) {
    return new Promise(function (resolver) {
      var url = URL.createObjectURL(archivo);
      var img = new Image();
      img.onload = function () {
        try {
          var ancho = Math.min(480, img.naturalWidth), alto = Math.round(img.naturalHeight * ancho / img.naturalWidth);
          var c = document.createElement('canvas');
          c.width = ancho; c.height = alto;
          var ctx = c.getContext('2d');
          ctx.drawImage(img, 0, 0, ancho, alto);
          var d = ctx.getImageData(0, 0, ancho, alto).data, g = new Float32Array(ancho * alto);
          for (var i = 0; i < g.length; i++) g[i] = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2];
          var suma = 0, suma2 = 0, n = 0;
          for (var y = 1; y < alto - 1; y++) for (var x = 1; x < ancho - 1; x++) {
            var p = y * ancho + x, l = 4 * g[p] - g[p - 1] - g[p + 1] - g[p - ancho] - g[p + ancho];
            suma += l; suma2 += l * l; n++;
          }
          resolver(n ? suma2 / n - Math.pow(suma / n, 2) : null);
        } catch (e) { resolver(null); }
        URL.revokeObjectURL(url);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolver(null); };
      img.src = url;
    });
  }

  entrada.addEventListener('change', function () {
    lista.textContent = '';
    var archivos = Array.prototype.slice.call(entrada.files || []);
    var vistos = {};
    var porHuella = {};
    var tareas = archivos.map(function (a) {
      var clave = a.name + '|' + a.size;
      if (vistos[clave]) avisar(texto('doble', { nombre: a.name })); vistos[clave] = true;
      if (TIPOS.indexOf(a.type) < 0) { avisar(texto('tipo', { nombre: a.name })); return Promise.resolve(); }
      if (a.size > MAX) avisar(texto('grande', { nombre: a.name }));
      var pasos = [huella(a).then(function (h) { if (h) porHuella[h] = a.name; })];
      if (a.type.indexOf('image/') === 0) pasos.push(nitidez(a).then(function (v) { if (v !== null && v < UMBRAL_BORROSA) avisar(texto('borrosa', { nombre: a.name })); }));
      return Promise.all(pasos);
    });
    Promise.all(tareas).then(function () {
      var huellas = Object.keys(porHuella);
      if (!huellas.length) return;
      return fetch(form.getAttribute('data-url-comprobar'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ huellas: huellas }) })
        .then(function (r) { return r.ok ? r.json() : { repetidas: {} }; })
        .then(function (r) { Object.keys(r.repetidas || {}).forEach(function (h) { avisar(texto('repetida', { nombre: porHuella[h] || '', fecha: r.repetidas[h] })); }); });
    }).catch(function () {});
  });

  var fecha = document.getElementById('fecha-factura'), aviso = document.getElementById('aviso-cierre');
  if (fecha && aviso) {
    var cerrados = (fecha.getAttribute('data-cerrados') || '').split(',').filter(Boolean);
    fecha.addEventListener('change', function () {
      var v = fecha.value, ok = false;
      if (/^\d{4}-\d{2}-\d{2}$/.test(v)) ok = cerrados.indexOf(v.slice(0, 4) + '-T' + (Math.floor((parseInt(v.slice(5, 7), 10) - 1) / 3) + 1)) >= 0;
      aviso.hidden = !ok;
      aviso.textContent = ok ? aviso.getAttribute('data-txt') : '';
    });
  }
})();
