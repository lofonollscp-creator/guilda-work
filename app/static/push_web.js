/* Avisos push en este navegador o webapp (Web Push). El botón vive en el desplegable de la campana y solo aparece
   si el navegador lo soporta y el servidor tiene el canal activado. */
(function () {
  var cont = document.getElementById("push-web");
  if (!cont || !("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return;
  var boton = document.getElementById("push-web-boton");
  var mensaje = document.getElementById("push-web-mensaje");
  var T = cont.dataset;
  var clave = null;

  function aBytes(b64) {
    var relleno = "=".repeat((4 - (b64.length % 4)) % 4);
    var bin = atob((b64 + relleno).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(bin, function (c) { return c.charCodeAt(0); });
  }
  function avisar(texto) { mensaje.textContent = texto || ""; mensaje.hidden = !texto; }
  function registro() { return navigator.serviceWorker.ready; }
  function post(url, cuerpo) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  }

  function pintar(activo) {
    boton.dataset.activo = activo ? "1" : "0";
    boton.textContent = activo ? T.tDesactivar : T.tActivar;
    if (Notification.permission === "denied" && !activo) avisar(T.tBloqueado); else avisar("");
  }

  function estadoActual() {
    return registro().then(function (r) { return r.pushManager.getSubscription(); }).then(function (s) { return !!s && Notification.permission === "granted"; });
  }

  function activar() {
    return Notification.requestPermission().then(function (permiso) {
      if (permiso !== "granted") return false;
      return registro().then(function (r) {
        return r.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: aBytes(clave) });
      }).then(function (sus) {
        return post("/notificaciones/push/suscribir", sus.toJSON());
      }).then(function (resp) { return resp.ok; });
    });
  }

  function desactivar() {
    return registro().then(function (r) { return r.pushManager.getSubscription(); }).then(function (sus) {
      if (!sus) return true;
      var endpoint = sus.endpoint;
      return sus.unsubscribe().then(function () { return post("/notificaciones/push/baja", { endpoint: endpoint }); }).then(function () { return true; });
    });
  }

  boton.addEventListener("click", function () {
    boton.disabled = true;
    var activo = boton.dataset.activo === "1";
    (activo ? desactivar() : activar())
      .then(function (ok) {
        if (!ok && !activo && Notification.permission !== "denied") avisar(T.tError);
        return estadoActual();
      })
      .then(pintar)
      .catch(function () { avisar(T.tError); })
      .then(function () { boton.disabled = false; });
  });

  fetch("/notificaciones/push/clave").then(function (r) { return r.json(); }).then(function (d) {
    if (!d.clave) return;
    clave = d.clave;
    return estadoActual().then(function (activo) { pintar(activo); cont.hidden = false; });
  }).catch(function () { /* sin avisos push: la campana funciona igual */ });
})();
