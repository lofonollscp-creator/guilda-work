// Comportamientos que antes vivían en atributos `on...=` dentro del HTML y que una política de contenido estricta (CSP sin
// 'unsafe-inline' para scripts) bloquea. Ahora el HTML lleva atributos `data-*` y este fichero los atiende con un único listener
// delegado por tipo de evento (también para lo que se añade después al DOM).
//
//   <form data-confirmar-envio="¿Seguro?">          pide confirmación antes de enviar el formulario (data-confirmar-excepto="nombre": no pregunta si envía ese botón;
//                                                    data-confirmar-peligro: diálogo de acción destructiva)
//   <button data-confirmar-clic="¿Seguro?">          pide confirmación antes de seguir el clic
//   <select data-autoenviar> / data-autoenviar="submit"   envía el formulario al cambiar (requestSubmit respeta validación y listeners)
//   <a data-accion="imprimir"> / "cerrar-creacion-rapida"
//   <a href="#id" data-mostrar="id">                 muestra ese elemento y oculta el propio enlace
//   <select data-requerido-si-vacio="campo">         el campo del mismo formulario es obligatorio si este valor está vacío
//   <iframe data-autoaltura>                         ajusta su alto al contenido (si es del mismo origen)
(function () {
  function cancelar(e) { e.preventDefault(); e.stopImmediatePropagation(); }

  // Confirmación con el diálogo del sistema de diseño (ds.js); sin él, el confirm() nativo. Como el diálogo es asíncrono, se frena el evento
  // y, si la persona acepta, se repite saltándose la pregunta.
  function preguntar(msg, peligro) {
    if (window.GuildaDS) return window.GuildaDS.confirmar(msg, { peligro: peligro });
    return Promise.resolve(window.confirm(msg));
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = form && form.dataset ? form.dataset.confirmarEnvio : null;
    if (!msg || form.__dsConfirmado) return;
    // data-confirmar-excepto="programar": no preguntar si el botón que envía se llama así.
    if (form.dataset.confirmarExcepto && e.submitter && e.submitter.name === form.dataset.confirmarExcepto) return;
    cancelar(e);
    var remitente = e.submitter || null;
    preguntar(msg, form.dataset.confirmarPeligro !== undefined).then(function (si) {
      if (!si) return;
      form.__dsConfirmado = true;
      try { if (form.requestSubmit) form.requestSubmit(remitente || undefined); else form.submit(); } finally { form.__dsConfirmado = false; }
    });
  }, true);

  document.addEventListener("click", function (e) {
    var conf = e.target.closest ? e.target.closest("[data-confirmar-clic]") : null;
    if (conf && !conf.__dsConfirmado) {
      cancelar(e);
      preguntar(conf.dataset.confirmarClic, conf.dataset.confirmarPeligro !== undefined || /\bbtn-peligro\b/.test(conf.className)).then(function (si) {
        if (!si) return;
        conf.__dsConfirmado = true;
        try { conf.click(); } finally { conf.__dsConfirmado = false; }
      });
      return;
    }
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
    if (e.target && e.target.matches && e.target.matches("iframe[data-autoaltura]")) {
      ajustar(e.target);
      [400, 1500].forEach(function (ms) { setTimeout(function () { ajustar(e.target); }, ms); });      // las imágenes del correo llegan después y cambian el alto
    }
  }, true);
  document.querySelectorAll("iframe[data-autoaltura]").forEach(function (f) { if (f.contentDocument && f.contentDocument.readyState === "complete") ajustar(f); });
})();
