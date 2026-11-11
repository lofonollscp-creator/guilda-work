// «Mira primero»: cada botón lleva al dato dudoso de la lectura (lo enfoca y lo centra), y al abrir la factura el cursor ya está en el más dudoso, salvo que se llegue a un campo concreto con #ancla.
(function () {
  "use strict";
  var caja = document.querySelector("[data-dudosos]");
  if (!caja) return;
  function ir(campo) {
    var destino = document.querySelector('[data-evidencia-campo="' + campo + '"]');
    if (!destino) return;
    destino.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    if (typeof destino.focus === "function") destino.focus({ preventScroll: true });
    if (typeof destino.select === "function" && destino.tagName === "INPUT") destino.select();
  }
  Array.prototype.forEach.call(caja.querySelectorAll("[data-ir-campo]"), function (b) {
    b.addEventListener("click", function () { ir(b.getAttribute("data-ir-campo")); });
  });
  var primero = caja.querySelector("[data-ir-campo]");
  if (primero && !location.hash && !document.activeElement.matches("input, textarea, select")) ir(primero.getAttribute("data-ir-campo"));
})();
