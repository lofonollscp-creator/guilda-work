// Al elegir facturas en el portal: recorta y aligera las fotos, avisa de archivos que no valen, repetidos y fotos borrosas y, si el despacho lo ha activado, enseña lo que lee la IA. Solo avisa, nunca bloquea el envío.
(function () {
  // Una factura devuelta se corrige en un toque: al elegir el archivo corregido se envía solo (el botón sigue ahí por si no funciona el envío automático).
  document.querySelectorAll('input[data-auto-enviar]').forEach(function (campo) {
    campo.addEventListener('change', function () { if (campo.files && campo.files.length && campo.form && campo.form.reportValidity()) campo.form.submit(); });
  });
  var form = document.getElementById('form-subida');
  if (!form) return;
  var entrada = form.querySelector('input[type=file]');
  var lista = document.getElementById('avisos-subida');
  var TIPOS = ['application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'application/xml', 'text/xml'];
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

  // Luz de la foto reducida: demasiadas zonas «quemadas» (blanco puro sin nada de texto: reflejos o flash) o una media muy baja (casi a oscuras). Es una pista, no un veredicto.
  function luz(archivo) {
    return new Promise(function (resolver) {
      var url = URL.createObjectURL(archivo);
      var img = new Image();
      img.onload = function () {
        try {
          var ancho = Math.min(320, img.naturalWidth), alto = Math.max(1, Math.round(img.naturalHeight * ancho / img.naturalWidth));
          var c = document.createElement('canvas');
          c.width = ancho; c.height = alto;
          var ctx = c.getContext('2d');
          ctx.drawImage(img, 0, 0, ancho, alto);
          var d = ctx.getImageData(0, 0, ancho, alto).data, bloque = 8, quemados = 0, total = 0, suma = 0;
          for (var by = 0; by + bloque <= alto; by += bloque) for (var bx = 0; bx + bloque <= ancho; bx += bloque) {
            var m = 0, m2 = 0;
            for (var y = by; y < by + bloque; y++) for (var x = bx; x < bx + bloque; x++) {
              var i = (y * ancho + x) * 4, l = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
              m += l; m2 += l * l;
            }
            m /= bloque * bloque; m2 = m2 / (bloque * bloque) - m * m;
            suma += m; total++;
            if (m >= 252 && m2 < 3) quemados++;
          }
          resolver(total ? { quemado: quemados / total, media: suma / total } : null);
        } catch (e) { resolver(null); }
        URL.revokeObjectURL(url);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolver(null); };
      img.src = url;
    });
  }

  var originales = [];                       // los archivos tal como se eligieron, por si prefiere enviarlos sin tocar
  var usarOriginales = document.getElementById('usar-originales');
  var ANCHO_MAX = 2200;

  function euros(t) { var n = parseFloat(t); return isNaN(n) ? t : n.toFixed(2).replace('.', ',') + ' €'; }
  function mb(n) { return (n / 1048576).toFixed(1).replace('.', ','); }

  // Recorta los márgenes (la mesa, la sombra) y reduce la foto: se busca el rectángulo que contiene todo lo que difiere del color de los bordes. Si no está claro, se deja como está.
  function optimizar(archivo) {
    return new Promise(function (resolver) {
      if (archivo.type.indexOf('image/') !== 0 || archivo.type === 'image/gif') return resolver(null);
      var url = URL.createObjectURL(archivo), img = new Image();
      img.onload = function () {
        try {
          var w = img.naturalWidth, h = img.naturalHeight, k = Math.min(1, ANCHO_MAX / Math.max(w, h));
          var pw = Math.max(1, Math.round(w * k)), ph = Math.max(1, Math.round(h * k));
          var c = document.createElement('canvas'); c.width = pw; c.height = ph;
          var ctx = c.getContext('2d', { willReadFrequently: true });
          ctx.drawImage(img, 0, 0, pw, ph);
          var d = ctx.getImageData(0, 0, pw, ph).data;
          var paso = Math.max(1, Math.floor(Math.max(pw, ph) / 400)), bordes = [0, 0, 0], nb = 0, x, y;
          function px(xx, yy) { var i = (yy * pw + xx) * 4; return [d[i], d[i + 1], d[i + 2]]; }
          for (x = 0; x < pw; x += paso) for (var e = 0; e < 3; e++) { var a = px(x, e), b = px(x, ph - 1 - e); for (var q = 0; q < 3; q++) bordes[q] += a[q] + b[q]; nb += 2; }
          for (y = 0; y < ph; y += paso) for (var f = 0; f < 3; f++) { var a2 = px(f, y), b2 = px(pw - 1 - f, y); for (var q2 = 0; q2 < 3; q2++) bordes[q2] += a2[q2] + b2[q2]; nb += 2; }
          bordes = bordes.map(function (v) { return v / nb; });
          var minx = pw, maxx = 0, miny = ph, maxy = 0, umbral = 48;
          for (y = 0; y < ph; y += paso) for (x = 0; x < pw; x += paso) {
            var p = px(x, y);
            if (Math.abs(p[0] - bordes[0]) + Math.abs(p[1] - bordes[1]) + Math.abs(p[2] - bordes[2]) > umbral) { if (x < minx) minx = x; if (x > maxx) maxx = x; if (y < miny) miny = y; if (y > maxy) maxy = y; }
          }
          var recortada = false, m = Math.round(Math.max(pw, ph) * 0.02);
          if (maxx > minx && maxy > miny) {
            var cx = Math.max(0, minx - m), cy = Math.max(0, miny - m), cw = Math.min(pw, maxx + m) - cx, ch = Math.min(ph, maxy + m) - cy, area = (cw * ch) / (pw * ph);
            if (area < 0.9 && area > 0.3) {                 // recorta solo si quita bastante y deja una factura razonable
              var c2 = document.createElement('canvas'); c2.width = cw; c2.height = ch;
              c2.getContext('2d').drawImage(c, cx, cy, cw, ch, 0, 0, cw, ch);
              c = c2; recortada = true;
            }
          }
          var reducida = k < 1;
          if (!recortada && !reducida) { URL.revokeObjectURL(url); return resolver(null); }
          c.toBlob(function (blob) {
            URL.revokeObjectURL(url);
            if (!blob || blob.size >= archivo.size && !recortada) return resolver(null);
            var nombre = archivo.name.replace(/\.[^.]+$/, '') + '.jpg';
            resolver({ archivo: new File([blob], nombre, { type: 'image/jpeg', lastModified: Date.now() }), recortada: recortada, antes: archivo.size, despues: blob.size });
          }, 'image/jpeg', 0.86);
        } catch (er) { URL.revokeObjectURL(url); resolver(null); }
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolver(null); };
      img.src = url;
    });
  }

  function poner(archivos) {
    try { var dt = new DataTransfer(); archivos.forEach(function (a) { dt.items.add(a); }); entrada.files = dt.files; return true; } catch (e) { return false; }
  }

  // Una línea que brilla mientras se espera la lectura; es solo decoración (el texto «leyendo…» ya lo dice) y se va al sustituir el contenido del elemento.
  function esqueleto() {
    var e = document.createElement('span'); e.className = 'portal-esqueleto'; e.setAttribute('aria-hidden', 'true');
    return e;
  }

  // Lo que lee la IA de cada archivo (solo si el despacho lo ha activado): se enseña para que la persona vea si la foto se lee bien.
  function lecturaPrevia(archivo) {
    var url = form.getAttribute('data-url-leer');
    if (!url || archivo.size > MAX || TIPOS.indexOf(archivo.type) < 0) return Promise.resolve();
    var li = document.createElement('li'); li.className = 'portal-lectura'; li.textContent = texto('leyendo', { nombre: archivo.name }); li.appendChild(esqueleto()); lista.appendChild(li);
    var datos = new FormData(); datos.append('archivo', archivo);
    return fetch(url, { method: 'POST', credentials: 'same-origin', body: datos }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).then(function (r) {
      if (!r.ok || !r.j.lectura) { li.textContent = r.j.error ? texto('nolee', { nombre: archivo.name }) : ''; if (!li.textContent) li.remove(); return; }
      var l = r.j.lectura, partes = [];
      if (l.emisor || l.nif) partes.push((l.emisor || '') + (l.nif ? ' (' + l.nif + ')' : ''));
      if (l.numero) partes.push(texto('numero', { v: l.numero }));
      if (l.fecha) partes.push(l.fecha.split('-').reverse().join('/'));
      if (l.total && l.total !== '0.00') partes.push(euros(l.total));
      var dudas = (l.avisos || []).map(function (a) { return texto('falta-' + a, {}); }).filter(Boolean);
      li.textContent = texto('lee', { nombre: archivo.name, datos: partes.join(' · ') || '—' }) + (dudas.length ? ' ' + dudas.join(' ') : '');
      if (dudas.length) li.classList.add('portal-lectura-dudosa');
    }).catch(function () { li.remove(); });
  }

  function revisar(archivos) {
    var vistos = {};
    var porHuella = {};
    var tareas = archivos.map(function (a) {
      var clave = a.name + '|' + a.size;
      if (vistos[clave]) avisar(texto('doble', { nombre: a.name })); vistos[clave] = true;
      if (TIPOS.indexOf(a.type) < 0) { avisar(texto('tipo', { nombre: a.name })); return Promise.resolve(); }
      if (a.size > MAX) avisar(texto('grande', { nombre: a.name }));
      var pasos = [huella(a).then(function (h) { if (h) porHuella[h] = a.name; })];
      if (a.type.indexOf('image/') === 0) pasos.push(nitidez(a).then(function (v) { if (v !== null && v < UMBRAL_BORROSA) avisar(texto('borrosa', { nombre: a.name })); }));
      if (a.type.indexOf('image/') === 0) pasos.push(luz(a).then(function (v) {
        if (!v) return;
        if (v.quemado > 0.18) avisar(texto('reflejos', { nombre: a.name }));
        else if (v.media < 70) avisar(texto('oscura', { nombre: a.name }));
      }));
      return Promise.all(pasos);
    });
    Promise.all(tareas).then(function () {
      var huellas = Object.keys(porHuella);
      if (!huellas.length) return;
      return fetch(form.getAttribute('data-url-comprobar'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ huellas: huellas }) })
        .then(function (r) { return r.ok ? r.json() : { repetidas: {} }; })
        .then(function (r) { Object.keys(r.repetidas || {}).forEach(function (h) { avisar(texto('repetida', { nombre: porHuella[h] || '', fecha: r.repetidas[h] })); }); });
    }).catch(function () {});
  }

  // Propone la foto enderezada (el servidor busca el papel en la imagen). Es solo una propuesta con vista previa: el cliente decide si la usa.
  function ofrecerEnderezado(archivos) {
    var url = form.getAttribute('data-url-enderezar');
    if (!url) return;
    archivos.forEach(function (archivo, i) {
      if (archivo.type.indexOf('image/') !== 0 || archivo.type === 'image/gif' || archivo.size > MAX) return;
      var datos = new FormData(); datos.append('archivo', archivo);
      fetch(url, { method: 'POST', credentials: 'same-origin', body: datos }).then(function (r) { return r.status === 200 ? r.blob() : null; }).then(function (blob) {
        if (!blob || blob.size < 2000) return;
        var li = document.createElement('li'), img = document.createElement('img'), msg = document.createElement('span'), usar = document.createElement('button'), dejar = document.createElement('button');
        var vista = URL.createObjectURL(blob);
        li.className = 'portal-enderezar'; img.src = vista; img.alt = ''; img.className = 'portal-enderezar-vista';
        msg.textContent = texto('endereza', { nombre: archivo.name });
        usar.type = 'button'; usar.className = 'btn btn-primary'; usar.textContent = texto('usar-enderezada', {});
        dejar.type = 'button'; dejar.className = 'btn btn-ghost'; dejar.textContent = texto('dejar-original', {});
        usar.addEventListener('click', function () {
          var nueva = new File([blob], archivo.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg', lastModified: Date.now() });
          var actuales = Array.prototype.slice.call(entrada.files || []);
          var j = actuales.findIndex(function (a) { return a.name === archivo.name && a.size === archivo.size; });
          if (j >= 0) { actuales[j] = nueva; poner(actuales); }
          li.textContent = texto('enderezada-puesta', {});
          URL.revokeObjectURL(vista);
        });
        dejar.addEventListener('click', function () { URL.revokeObjectURL(vista); li.remove(); });
        li.appendChild(img); li.appendChild(msg); li.appendChild(usar); li.appendChild(dejar);
        lista.appendChild(li);
      }).catch(function () {});
    });
  }

  function procesar() {
    var quiere = !(usarOriginales && usarOriginales.checked);
    return Promise.all(originales.map(function (a) { return quiere ? optimizar(a) : Promise.resolve(null); })).then(function (res) {
      var finales = originales.map(function (a, i) { return res[i] ? res[i].archivo : a; });
      var cambiado = res.some(Boolean);
      if ((cambiado || !quiere) && !poner(finales)) finales = originales.slice();
      res.forEach(function (r, i) { if (r) avisar(texto(r.recortada ? 'recortada' : 'reducida', { nombre: originales[i].name, antes: mb(r.antes), despues: mb(r.despues) })); });
      if (usarOriginales && usarOriginales.parentNode) usarOriginales.parentNode.hidden = !cambiado && !usarOriginales.checked;
      revisar(finales);
      ofrecerEnderezado(finales);
      return finales.reduce(function (p, a) { return p.then(function () { return lecturaPrevia(a); }); }, Promise.resolve());
    }).catch(function () {});
  }

  var juntar = form.querySelector('[data-misma-factura]');
  function ofrecerJuntar(archivos) {
    if (!juntar) return;
    var fotos = archivos.filter(function (a) { return a.type.indexOf('image/') === 0; });
    var todasFotos = fotos.length === archivos.length;
    juntar.hidden = !(archivos.length > 1 && todasFotos);
    if (juntar.hidden) { var marca = juntar.querySelector('input'); if (marca) marca.checked = false; }
  }
  entrada.addEventListener('change', function () {
    lista.textContent = '';
    originales = Array.prototype.slice.call(entrada.files || []);
    ofrecerJuntar(originales);
    procesar();
  });
  if (usarOriginales) usarOriginales.addEventListener('change', function () {
    if (!originales.length) return;
    lista.textContent = '';
    procesar();
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
