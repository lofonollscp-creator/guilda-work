(function () {
  "use strict";
  var banner = document.getElementById("correo-envio-banner");
  var cuenta = document.getElementById("correo-envio-cuenta");
  if (!banner || !cuenta) return; // programado: sin cuenta atrás
  var restante = parseInt(banner.dataset.segundos, 10) || 0;
  var timer = setInterval(function () {
    restante -= 1;
    if (restante > 0) { cuenta.textContent = String(restante); return; }
    clearInterval(timer);
    // Pasada la ventana el hilo del servidor lo enviará en unos segundos:
    // ya no se ofrece deshacer.
    var texto = banner.querySelector(".correo-envio-texto");
    if (texto) texto.textContent = banner.dataset.tEnviado;
    var form = document.getElementById("correo-envio-deshacer");
    if (form) form.hidden = true;
    setTimeout(function () { banner.hidden = true; }, 4000);
  }, 1000);
})();
