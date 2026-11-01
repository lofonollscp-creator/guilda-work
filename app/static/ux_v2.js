/* Web v2 · flujos de interfaz comunes a toda la plataforma.
   1) Marca <html class="js"> (para ocultar controles que solo hacen falta sin JavaScript).
   2) Evita envíos dobles: al enviar un formulario, el botón se bloquea y muestra «cargando» (se libera al volver con «atrás» o a los 20 s).
   3) Avisa antes de salir de un formulario largo con cambios sin guardar.
   4) El botón «Más» de la barra inferior (móvil) abre el menú lateral. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  var NO_BLOQUEAR = /descargar|export|pdf|csv|json|\.ics|fichero|imprimir|logout|salir/i;
  var cambiosSinGuardar = false;

  function liberar(boton) {
    boton.classList.remove("is-enviando");
    boton.removeAttribute("aria-busy");
    boton.disabled = false;
  }

  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!(f instanceof HTMLFormElement) || e.defaultPrevented) return;
    cambiosSinGuardar = false;
    if ((f.method || "").toLowerCase() !== "post" || f.target === "_blank" || f.hasAttribute("data-no-bloquear") || NO_BLOQUEAR.test(f.action || "")) return;
    var boton = e.submitter && e.submitter.tagName === "BUTTON" ? e.submitter : f.querySelector('button[type="submit"], button:not([type])');
    if (!boton || boton.disabled) return;
    // Se bloquea en el siguiente ciclo: así el botón sigue aportando su name/value al envío.
    setTimeout(function () {
      if (e.defaultPrevented) return;      // otro manejador lo ha cancelado (confirmación rechazada) o lo envía por fetch
      boton.classList.add("is-enviando");
      boton.setAttribute("aria-busy", "true");
      boton.disabled = true;
      setTimeout(function () { liberar(boton); }, 20000);
    }, 0);
  }, true);

  window.addEventListener("pageshow", function (ev) {
    if (!ev.persisted) return;
    document.querySelectorAll("button.is-enviando").forEach(liberar);
  });

  // Formularios largos de edición: aviso al salir con cambios.
  document.querySelectorAll("form.edit-form, form.notas-form").forEach(function (f) {
    if ((f.method || "").toLowerCase() !== "post") return;
    f.addEventListener("input", function () { cambiosSinGuardar = true; });
  });
  window.addEventListener("beforeunload", function (e) {
    if (!cambiosSinGuardar) return;
    e.preventDefault();
    e.returnValue = "";
  });

  var mas = document.getElementById("barra-inferior-mas");
  var abrir = document.getElementById("menu-movil-abrir");
  if (mas && abrir) mas.addEventListener("click", function () { abrir.click(); });
})();
