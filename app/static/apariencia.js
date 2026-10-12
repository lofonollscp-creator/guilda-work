// Guarda el tema y la densidad en la cuenta (POST /ajustes/apariencia) para que te sigan entre dispositivos. El navegador sigue guardándolos
// en localStorage para pintar sin parpadeo; esto solo añade la copia en el servidor. Si falla (sin conexión, sesión caducada) no pasa nada.
(function () {
  "use strict";
  var pendiente = {}, temporizador = null;
  function enviar() {
    var cuerpo = pendiente; pendiente = {}; temporizador = null;
    try {
      fetch("/ajustes/apariencia", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo), credentials: "same-origin", keepalive: true }).catch(function () { /* se vuelve a guardar en el próximo cambio */ });
    } catch (e) { /* sin fetch */ }
  }
  window.GuildaApariencia = {
    guardar: function (cambios) {
      Object.assign(pendiente, cambios);
      clearTimeout(temporizador);
      temporizador = setTimeout(enviar, 400);     // varios clics seguidos = una sola petición
    },
  };
})();
