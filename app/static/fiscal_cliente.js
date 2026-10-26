/* Ficha del titular en Guilda Fiscal: botón «Copiar» del mensaje al cliente. */
document.addEventListener('click', function (ev) {
  var b = ev.target.closest('[data-copiar]');
  if (!b) return;
  var campo = document.querySelector(b.getAttribute('data-copiar'));
  if (!campo) return;
  var original = b.textContent;
  function listo() { b.textContent = b.getAttribute('data-copiado') || original; setTimeout(function () { b.textContent = original; }, 1600); }
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(campo.value).then(listo, function () { campo.select(); });
  else { campo.select(); document.execCommand('copy'); listo(); }
});
