// Comportamientos que antes vivían en atributos `on...=` dentro del HTML y que una política de contenido estricta (CSP sin
// 'unsafe-inline' para scripts) bloquea. Ahora el HTML lleva atributos `data-*` y este fichero los atiende con un único listener
// delegado por tipo de evento (también para lo que se añade después al DOM).
//
//   <form data-confirmar-envio="¿Seguro?">          pide confirmación antes de enviar el formulario
//   <button data-confirmar-clic="¿Seguro?">          pide confirmación antes de seguir el clic
//   <select data-autoenviar> / data-autoenviar="submit"   envía el formulario al cambiar (requestSubmit respeta validación y listeners)
//   <a data-accion="imprimir"> / "cerrar-creacion-rapida"
//   <a href="#id" data-mostrar="id">                 muestra ese elemento y oculta el propio enlace
//   <select data-requerido-si-vacio="campo">         el campo del mismo formulario es obligatorio si este valor está vacío
//   <iframe data-autoaltura>                         ajusta su alto al contenido (si es del mismo origen)
(function () {
  function cancelar(e) { e.preventDefault(); e.stopImmediatePropagation(); }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = form && form.dataset ? form.dataset.confirmarEnvio : null;
    if (msg && !window.confirm(msg)) cancelar(e);
  }, true);

  document.addEventListener("click", function (e) {
    var conf = e.target.closest ? e.target.closest("[data-confirmar-clic]") : null;
    if (conf && !window.confirm(conf.dataset.confirmarClic)) { cancelar(e); return; }
    var accion = e.target.closest ? e.target.closest("[data-accion]") : null;
    if (accion) {
      if (accion.dataset.accion === "imprimir") window.print();
      else if (accion.dataset.accion === "cerrar-creacion-rapida" && typeof window.cerrarCreacionRapidaTarea === "function") window.cerrarCreacionRapidaTarea();
    }
    var mostrar = e.target.closest ? e.target.closest("[data-mostrar]") : null;
    if (mostrar) {
      e.preventDefault();
      var destino = document.getElementById(mostrar.dataset.mostrar);
      if (destino) destino.hidden = false;
      mostrar.hidden = true;
    }
  }, true);

  document.addEventListener("change", function (e) {
    var el = e.target;
    if (!el || !el.matches) return;
    if (el.matches("[data-autoenviar]") && el.form) {
      if (el.dataset.autoenviar === "submit") el.form.submit(); else el.form.requestSubmit();
    }
    if (el.matches("[data-requerido-si-vacio]") && el.form) {
      var campo = el.form.elements[el.dataset.requeridoSiVacio];
      if (campo) campo.required = !el.value;
    }
  });

  function ajustar(iframe) {
    try { iframe.style.height = (iframe.contentWindow.document.body.scrollHeight + 24) + "px"; } catch (err) { /* otro origen: se queda como está */ }
  }
  document.addEventListener("load", function (e) {
    if (e.target && e.target.matches && e.target.matches("iframe[data-autoaltura]")) ajustar(e.target);
  }, true);
  document.querySelectorAll("iframe[data-autoaltura]").forEach(function (f) { if (f.contentDocument && f.contentDocument.readyState === "complete") ajustar(f); });
})();
