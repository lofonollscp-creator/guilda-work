// Atajos de teclado globales (a nivel de ventana/JS, complementarios al
// atajo de sistema operativo Ctrl+Alt+G ya existente vía la librería
// `keyboard` en app/main.py). Solo funcionan con la app en primer plano.
(function () {
  function esAtajo(e, tecla) {
    return e.ctrlKey && e.altKey && !e.shiftKey && !e.metaKey && e.key.toLowerCase() === tecla;
  }

  // Usado también por el atajo "?" de ayuda: evita que dispare mientras el
  // usuario está escribiendo en un campo de texto (donde "?" es un
  // carácter normal, no un atajo).
  function escribiendoEnCampo(e) {
    var el = e.target;
    if (!el) return false;
    var etiqueta = el.tagName;
    return etiqueta === "INPUT" || etiqueta === "TEXTAREA" || etiqueta === "SELECT" || el.isContentEditable;
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
    } else if (e.key === "?" && !e.ctrlKey && !e.altKey && !e.metaKey && !escribiendoEnCampo(e)) {
      e.preventDefault();
      abrirAyudaAtajos();
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

  // ---- Modal de ayuda de atajos ("?") --------------------------------
  var overlay = document.getElementById("atajos-ayuda-overlay");
  var boton = document.getElementById("atajos-ayuda-abrir");
  var botonCerrar = document.getElementById("atajos-ayuda-cerrar");

  function abrirAyudaAtajos() {
    if (!overlay) return;
    overlay.hidden = false;
    if (botonCerrar) botonCerrar.focus();
  }

  function cerrarAyudaAtajos() {
    if (!overlay) return;
    overlay.hidden = true;
    if (boton) boton.focus();
  }

  if (boton) boton.addEventListener("click", abrirAyudaAtajos);
  if (botonCerrar) botonCerrar.addEventListener("click", cerrarAyudaAtajos);
  if (overlay) {
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) cerrarAyudaAtajos();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !overlay.hidden) cerrarAyudaAtajos();
    });
  }
})();
