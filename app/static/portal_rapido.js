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
