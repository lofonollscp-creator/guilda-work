// Marcar o desmarcar todas las oportunidades de la lista (la casilla de la cabecera lleva data-marcar-todos="<nombre del campo>").
document.addEventListener("change", function (e) {
  var caja = e.target.closest("[data-marcar-todos]");
  if (!caja) return;
  document.querySelectorAll('input[type="checkbox"][name="' + caja.dataset.marcarTodos + '"]').forEach(function (c) { c.checked = caja.checked; });
});
