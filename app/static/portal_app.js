// Portal: barra de carga, «Más» de la barra inferior e insignia de la app, invitación a instalar y atajos de teclado (tres piezas independientes en un solo archivo, para cargar menos).
// Rapidez percibida del portal: al pulsar un enlace o enviar un formulario aparece al instante una barra de carga arriba y la página se marca como ocupada, en vez de quedarse quieta hasta que llega la siguiente.
// Es solo decoración (aria-hidden): no cambia a dónde se va ni bloquea nada. Con «reducir movimiento» la barra no se anima.
(function () {
  var barra = document.querySelector('[data-barra-carga]');
  var main = document.getElementById('portal-contenido');
  if (!barra) return;
  function empezar() { barra.hidden = false; barra.classList.add('en-marcha'); if (main) main.setAttribute('aria-busy', 'true'); }
  function terminar() { barra.hidden = true; barra.classList.remove('en-marcha'); if (main) main.removeAttribute('aria-busy'); }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target && a.target !== '_self') return;
    if (a.hasAttribute('download') || a.origin !== location.origin || (a.pathname === location.pathname && a.search === location.search)) return;
    empezar();
  });
  document.addEventListener('submit', function (e) { if (!e.defaultPrevented) setTimeout(function () { if (!e.defaultPrevented) empezar(); }, 0); });
  window.addEventListener('pageshow', terminar);              // al volver con «atrás» la página puede venir de la caché con la barra a medias

  // «Más» de la barra inferior: se cierra al pulsar fuera o con Esc.
  var mas = document.querySelector('.portal-tabs-mas');
  if (mas) {
    document.addEventListener('click', function (e) { if (mas.open && !mas.contains(e.target)) mas.open = false; });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && mas.open) { mas.open = false; var r = mas.querySelector('summary'); if (r) r.focus(); } });
  }
  // Número de cosas pendientes en el icono de la app instalada (donde el sistema lo permite).
  var m = document.querySelector('meta[name=portal-insignia]');
  if (m && navigator.setAppBadge) {
    var n = parseInt(m.content || '0', 10);
    try { if (n > 0) navigator.setAppBadge(n); else if (navigator.clearAppBadge) navigator.clearAppBadge(); } catch (err) { /* sin insignia no pasa nada */ }
  }
})();

// Invitación a instalar el portal como aplicación: en Chrome/Edge/Android con el botón del sistema; en iPhone y iPad con las instrucciones (Safari no tiene botón). Se ofrece a partir de la segunda visita,
// se puede descartar (no vuelve a salir en 30 días) y nunca sale si ya está instalada.
(function () {
  var caja = document.querySelector('[data-instalar]');
  if (!caja) return;
  var texto = caja.querySelector('[data-instalar-texto]'), boton = caja.querySelector('[data-instalar-boton]'), cerrar = caja.querySelector('[data-instalar-cerrar]');
  var CLAVE_NO = 'gw-instalar-no', CLAVE_VISITAS = 'gw-portal-visitas';
  function leer(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento no pasa nada */ } }
  var instalada = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
  var visitas = parseInt(leer(CLAVE_VISITAS) || '0', 10) + 1;
  guardar(CLAVE_VISITAS, String(visitas));
  var no = parseInt(leer(CLAVE_NO) || '0', 10);
  if (instalada || visitas < 2 || (no && Date.now() - no < 30 * 24 * 3600 * 1000)) return;
  var propuesta = null;
  function mostrar(t, conBoton) { texto.textContent = t; boton.hidden = !conBoton; caja.hidden = false; }
  window.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); propuesta = e; mostrar(caja.getAttribute('data-txt-instalar'), true); });
  var ua = navigator.userAgent || '';
  if (/iPhone|iPad|iPod/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua)) mostrar(caja.getAttribute('data-txt-ios'), false);
  boton.addEventListener('click', function () {
    if (!propuesta) return;
    propuesta.prompt();
    propuesta.userChoice.then(function () { propuesta = null; caja.hidden = true; guardar(CLAVE_NO, String(Date.now())); });
  });
  cerrar.addEventListener('click', function () { caja.hidden = true; guardar(CLAVE_NO, String(Date.now())); });
  window.addEventListener('appinstalled', function () { caja.hidden = true; });
})();

// Atajos de teclado del portal (para quien lo usa en el ordenador): «g» y una letra para ir a una sección, «/» para buscar y «?» para ver la lista. No actúan mientras se escribe en un campo.
(function () {
  var dialogo = document.getElementById('portal-atajos');
  var destinos = {};
  document.querySelectorAll('[data-atajo]').forEach(function (a) { destinos[a.getAttribute('data-atajo')] = a.getAttribute('href'); });
  var pendiente = false, temporizador = null;
  function escribiendo(e) { var t = e.target || {}; return /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable; }
  function abrir() { if (dialogo && dialogo.showModal && !dialogo.open) dialogo.showModal(); }
  document.querySelectorAll('[data-atajos-abrir]').forEach(function (b) { b.addEventListener('click', abrir); });
  if (dialogo) {
    var cerrar = dialogo.querySelector('[data-atajos-cerrar]');
    if (cerrar) cerrar.addEventListener('click', function () { dialogo.close(); });
    dialogo.addEventListener('click', function (e) { if (e.target === dialogo) dialogo.close(); });
  }
  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || escribiendo(e) || (dialogo && dialogo.open)) return;
    var k = e.key;
    if (pendiente) {
      pendiente = false; clearTimeout(temporizador);
      if (destinos[k]) { e.preventDefault(); location.href = destinos[k]; }
      return;
    }
    if (k === 'g') { pendiente = true; temporizador = setTimeout(function () { pendiente = false; }, 1500); }
    else if (k === '/' && destinos['/']) { e.preventDefault(); location.href = destinos['/']; }
    else if (k === '?') { e.preventDefault(); abrir(); }
  });
})();

// Salud del portal (solo si el despacho la ha encendido): el tiempo de carga de la pantalla (una de cada cuatro) y los primeros errores de JavaScript. Sin nada de la persona ni de la página, solo el camino.
(function () {
  var m = document.querySelector('meta[name=portal-telemetria]');
  if (!m || !navigator.sendBeacon) return;
  var url = m.content, ruta = location.pathname, enviados = 0;
  function mandar(o) { try { navigator.sendBeacon(url, new Blob([JSON.stringify(o)], { type: 'application/json' })); } catch (e) { /* no pasa nada */ } }
  window.addEventListener('error', function (e) { if (enviados++ < 3) mandar({ tipo: 'error', ruta: ruta, mensaje: e.message || '' }); });
  window.addEventListener('load', function () {
    setTimeout(function () {
      var n = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      if (n && n.loadEventEnd > 0 && Math.random() < 0.25) mandar({ tipo: 'carga', ruta: ruta, ms: Math.round(n.loadEventEnd) });
    }, 0);
  });
})();
