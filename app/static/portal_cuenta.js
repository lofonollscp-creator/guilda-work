/* «Mi cuenta» del portal: activar o desactivar los avisos en este dispositivo (Web Push) y ofrecer instalar el portal como app. Sin esto la página funciona igual. */
(function () {
  "use strict";
  var estado = document.getElementById("push-estado");
  var activar = document.getElementById("push-activar");
  var desactivar = document.getElementById("push-desactivar");

  function texto(clave) { return estado ? estado.getAttribute("data-txt-" + clave) || "" : ""; }
  function mostrar(activo) {
    if (!estado) return;
    estado.textContent = texto(activo ? "activado" : "desactivado");
    activar.hidden = activo;
    desactivar.hidden = !activo;
  }
  function aBytes(base64Url) {
    var relleno = "=".repeat((4 - base64Url.length % 4) % 4);
    var crudo = atob((base64Url + relleno).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(crudo, function (c) { return c.charCodeAt(0); });
  }
  function enviar(url, cuerpo) {
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  }

  if (estado) {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      estado.textContent = texto("no-disponible");
    } else if (Notification.permission === "denied") {
      estado.textContent = texto("denegado");
    } else {
      navigator.serviceWorker.ready.then(function (reg) {
        reg.pushManager.getSubscription().then(function (sub) { mostrar(!!sub && Number(estado.getAttribute("data-activos")) > 0); });
        activar.addEventListener("click", function () {
          Notification.requestPermission().then(function (permiso) {
            if (permiso !== "granted") { estado.textContent = texto("denegado"); return null; }
            return fetch("/portal/push/clave", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
              if (!d.clave) { estado.textContent = texto("no-disponible"); return null; }
              return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: aBytes(d.clave) });
            }).then(function (sub) {
              if (!sub) return null;
              return enviar("/portal/push/suscribir", sub.toJSON()).then(function (r) { mostrar(r.ok); });
            });
          });
        });
        desactivar.addEventListener("click", function () {
          reg.pushManager.getSubscription().then(function (sub) {
            if (!sub) { mostrar(false); return; }
            var endpoint = sub.endpoint;
            sub.unsubscribe().then(function () { return enviar("/portal/push/baja", { endpoint: endpoint }); }).then(function () { mostrar(false); });
          });
        });
      });
    }
  }

  var instalar = document.getElementById("instalar-app");
  var propuesta = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    propuesta = e;
    if (instalar) instalar.hidden = false;
  });
  if (instalar) {
    instalar.addEventListener("click", function () {
      if (!propuesta) return;
      propuesta.prompt();
      propuesta.userChoice.then(function () { propuesta = null; instalar.hidden = true; });
    });
  }
})();
