/* Registra el service worker de recursos estáticos (solo con https o localhost; si falla, la app funciona igual). */
(function () {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* sin service worker no pasa nada */ });
  });
})();
