/* Respuestas rápidas del despacho: al elegir una, su texto pasa al cuadro de texto indicado (se añade a lo que ya hubiera) para editarlo antes de enviar. */
(function () {
  "use strict";
  document.addEventListener("change", function (e) {
    var sel = e.target;
    if (!sel.classList || !sel.classList.contains("respuestas-rapidas") || !sel.value) return;
    var caja = document.getElementById(sel.getAttribute("data-destino"));
    if (caja) {
      caja.value = caja.value ? caja.value.replace(/\s+$/, "") + "\n" + sel.value : sel.value;
      caja.focus();
    }
    sel.selectedIndex = 0;
  });
})();
