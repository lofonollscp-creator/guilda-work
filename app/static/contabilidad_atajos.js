// Atajos de la ficha de factura: R = marcar como revisada, S = revisar y pasar a la siguiente. No actúan mientras se escribe en un campo ni con teclas modificadoras.
(function () {
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
    var el = document.activeElement;
    if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || (el && el.isContentEditable)) return;
    var boton = document.querySelector('[data-atajo="' + e.key.toLowerCase() + '"]');
    if (boton && !boton.disabled) { e.preventDefault(); boton.click(); }
  });
})();
