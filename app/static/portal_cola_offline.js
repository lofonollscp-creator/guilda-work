// Subir facturas sin conexión: si el navegador no tiene red al enviar el formulario, los archivos se guardan en el propio dispositivo (IndexedDB) y se envían solos cuando vuelve la conexión.
// Solo actúa en los formularios marcados con data-cola-offline; con conexión el formulario funciona como siempre.
(function () {
  var forms = Array.prototype.slice.call(document.querySelectorAll('form[data-cola-offline]'));
  if (!forms.length || !window.indexedDB) return;
  var BD = 'gw-cola-portal', ALMACEN = 'envios', MAX_INTENTOS = 8;
  var aviso = document.getElementById('cola-offline');

  function txt(f, clave, valores) {
    var t = f.getAttribute('data-txt-' + clave) || '';
    Object.keys(valores || {}).forEach(function (k) { t = t.replace('%(' + k + ')s', valores[k]); });
    return t;
  }
  function decir(texto, alerta) { if (!aviso) return; aviso.textContent = texto; aviso.setAttribute('role', alerta ? 'alert' : 'status'); aviso.hidden = !texto; }

  function abrir() {
    return new Promise(function (ok, ko) {
      var r = indexedDB.open(BD, 1);
      r.onupgradeneeded = function () { r.result.createObjectStore(ALMACEN, { keyPath: 'id', autoIncrement: true }); };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { ko(r.error); };
    });
  }
  function op(modo, f) {
    return abrir().then(function (db) {
      return new Promise(function (ok, ko) {
        var t = db.transaction(ALMACEN, modo), s = t.objectStore(ALMACEN), r = f(s);
        t.oncomplete = function () { ok(r && r.result); db.close(); };
        t.onerror = t.onabort = function () { ko(t.error); db.close(); };
      });
    });
  }
  var guardar = function (item) { return op('readwrite', function (s) { return s.add(item); }); };
  var todos = function () { return op('readonly', function (s) { return s.getAll(); }); };
  var borrar = function (id) { return op('readwrite', function (s) { return s.delete(id); }); };
  var cambiar = function (item) { return op('readwrite', function (s) { return s.put(item); }); };

  // Los campos del formulario como datos que IndexedDB sabe guardar (los archivos, como Blob).
  function serializar(form) {
    var campos = [];
    new FormData(form).forEach(function (v, n) {
      if (typeof v === 'string') campos.push({ n: n, v: v });
      else if (v && v.size) campos.push({ n: n, b: v, nombre: v.name, tipo: v.type });
    });
    return campos;
  }
  function formData(item) {
    var d = new FormData();
    item.campos.forEach(function (c) { if (c.b) d.append(c.n, c.b, c.nombre); else d.append(c.n, c.v); });
    return d;
  }

  var enviando = false;
  function vaciar(form) {
    if (enviando || navigator.onLine === false) return Promise.resolve();
    enviando = true;
    return todos().then(function (items) {
      var enviados = 0, fallos = 0;
      return items.reduce(function (p, item) {
        return p.then(function () {
          decir(txt(form, 'enviando'), false);
          return fetch(item.url, { method: 'POST', body: formData(item), credentials: 'same-origin' }).then(function (r) {
            if (r.ok) { enviados += 1; return borrar(item.id); }
            fallos += 1;                                   // el servidor lo ha rechazado (límite, tipo…): reintentarlo igual no lo arregla
            return borrar(item.id);
          }).catch(function () {                           // sin red otra vez: se queda para la próxima
            item.intentos = (item.intentos || 0) + 1;
            return item.intentos >= MAX_INTENTOS ? borrar(item.id).then(function () { fallos += 1; }) : cambiar(item);
          });
        });
      }, Promise.resolve()).then(function () {
        if (enviados) decir(txt(form, 'enviado', { n: enviados }) + (fallos ? ' ' + txt(form, 'fallo', { n: fallos }) : ''), false);
        else if (fallos) decir(txt(form, 'fallo', { n: fallos }), true);
        else decir('', false);
      });
    }).catch(function () {}).then(function () { enviando = false; });
  }

  forms.forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (navigator.onLine !== false) return;              // con conexión, el envío normal
      var campos = serializar(form);
      if (!campos.some(function (c) { return c.b; })) return;
      e.preventDefault();
      guardar({ url: form.getAttribute('action') || location.pathname, campos: campos, creado: Date.now(), intentos: 0 }).then(function () {
        form.reset();
        decir(txt(form, 'guardado'), false);
      }).catch(function () { form.submit(); });             // sin IndexedDB (modo privado…): que el navegador haga lo que pueda
    });
    window.addEventListener('online', function () { vaciar(form); });
    vaciar(form);
  });
  window.__colaOffline = { todos: todos };                 // para las pruebas del navegador
})();
