// Atajos de teclado globales (a nivel de ventana/JS, complementarios al
// atajo de sistema operativo Ctrl+Alt+G ya existente vía la librería
// `keyboard` en app/main.py). Solo funcionan con la app en primer plano.
(function () {
  function esAtajo(e, tecla) {
    return e.ctrlKey && e.altKey && !e.shiftKey && !e.metaKey && e.key.toLowerCase() === tecla;
  }

  document.addEventListener("keydown", function (e) {
    if (esAtajo(e, "n")) {
      e.preventDefault();
      if (window.pywebview && window.pywebview.api && window.pywebview.api.abrir_captura) {
        window.pywebview.api.abrir_captura();
      } else if (location.pathname === "/") {
        var campo = document.getElementById("dash-nota-texto");
        if (campo) campo.focus();
      } else {
        location.href = "/";
      }
    } else if (esAtajo(e, "t")) {
      e.preventDefault();
      location.href = "/tareas/?nueva=1";
    } else if (esAtajo(e, "b")) {
      e.preventDefault();
      location.href = "/historial?enfocar=1";
    }
  });

  // Al llegar desde uno de los atajos anteriores, enfocar el campo relevante.
  var params = new URLSearchParams(location.search);
  if (params.has("nueva")) {
    var asunto = document.querySelector('input[name="asunto"]');
    if (asunto) {
      asunto.scrollIntoView({ block: "center" });
      asunto.focus();
    }
  }
  if (params.has("enfocar")) {
    var buscar = document.getElementById("historial-buscar-input");
    if (buscar) buscar.focus();
  }
})();
