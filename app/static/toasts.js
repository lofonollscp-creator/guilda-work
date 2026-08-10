// Sistema único de toast/flash (sustituye a los avisos de error ad hoc que
// había repartidos por varias plantillas). Expone window.mostrarToast(),
// usado tanto desde plantillas (que pueden traducir con {{ _('...') }} antes
// de llamarlo) como desde los .js sueltos de app/static/, que no pasan por
// Jinja: para esos, base.html vuelca los textos ya traducidos en
// window.GUILDA_I18N (ver <script> justo antes de este archivo).
(function () {
  function contenedor() {
    var cont = document.getElementById("toast-contenedor");
    if (!cont) {
      cont = document.createElement("div");
      cont.id = "toast-contenedor";
      cont.className = "toast-contenedor";
      document.body.appendChild(cont);
    }
    return cont;
  }

  var textoCerrar = (window.GUILDA_I18N && window.GUILDA_I18N.cerrar) || "Cerrar";

  /**
   * mostrarToast(mensaje, tipo, opciones)
   *  - tipo: "exito" (por defecto) o "error".
   *  - opciones.duracion: ms antes de autoocultarse (por defecto 4000).
   *  - opciones.textoAccion / opciones.accion: botón adicional opcional
   *    (usado, p.ej., por el "Deshacer" tras borrar).
   * Devuelve un objeto { cerrar } por si quien llama necesita cerrarlo
   * manualmente (p.ej. al confirmar la acción del botón extra).
   */
  function mostrarToast(mensaje, tipo, opciones) {
    tipo = tipo === "error" ? "error" : "exito";
    opciones = opciones || {};

    var toast = document.createElement("div");
    toast.className = "toast toast-" + tipo;
    // role="alert" (asertivo) para errores -- que el lector de pantalla lo
    // anuncie ya; role="status" (educado) para éxito, que espera a que el
    // usuario termine lo que esté leyendo. Mismo criterio que el resto de
    // mensajes accesibles ya presentes en la app.
    toast.setAttribute("role", tipo === "error" ? "alert" : "status");
    toast.setAttribute("aria-live", tipo === "error" ? "assertive" : "polite");

    var icono = document.createElement("span");
    icono.className = "toast-icono";
    icono.setAttribute("aria-hidden", "true");
    icono.textContent = tipo === "error" ? "⚠" : "✓";
    toast.appendChild(icono);

    var texto = document.createElement("span");
    texto.className = "toast-texto";
    texto.textContent = mensaje;
    toast.appendChild(texto);

    var temporizador;
    function cerrar() {
      if (!toast.parentNode) return;
      clearTimeout(temporizador);
      toast.classList.add("toast-saliendo");
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 200);
    }

    if (opciones.textoAccion && typeof opciones.accion === "function") {
      var btnAccion = document.createElement("button");
      btnAccion.type = "button";
      btnAccion.className = "toast-accion";
      btnAccion.textContent = opciones.textoAccion;
      btnAccion.addEventListener("click", function () {
        opciones.accion();
        cerrar();
      });
      toast.appendChild(btnAccion);
    }

    var btnCerrar = document.createElement("button");
    btnCerrar.type = "button";
    btnCerrar.className = "toast-cerrar";
    btnCerrar.setAttribute("aria-label", textoCerrar);
    btnCerrar.textContent = "×";
    btnCerrar.addEventListener("click", cerrar);
    toast.appendChild(btnCerrar);

    contenedor().appendChild(toast);
    temporizador = setTimeout(cerrar, opciones.duracion || 4000);
    return { cerrar: cerrar };
  }

  window.mostrarToast = mostrarToast;

  // ---- Deshacer tras borrar --------------------------------------------
  // Guarda un toast pendiente en sessionStorage para pintarlo justo
  // después de una navegación (p.ej. al borrar una nota desde su página
  // de edición, que redirige a `volver_a` -- ahí ya no existe el toast
  // que se habría mostrado en la página de origen, así que se traslada a
  // la siguiente carga de página).
  var CLAVE_TOAST_PENDIENTE = "gw-toast-pendiente";

  function mostrarToastPendiente(mensaje, tipo, opciones) {
    opciones = opciones || {};
    try {
      sessionStorage.setItem(CLAVE_TOAST_PENDIENTE, JSON.stringify({
        mensaje: mensaje,
        tipo: tipo,
        textoAccion: opciones.textoAccion,
        accionUrl: opciones.accionUrl,
      }));
    } catch (e) {
      // sessionStorage no disponible (modo privado muy restrictivo, etc.)
      // -- simplemente se pierde el toast, no es crítico.
    }
  }

  function accionDeshacerDesdeUrl(url) {
    return async function () {
      try {
        const resp = await fetch(url, { method: "POST" });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        window.location.reload();
      } catch (e) {
        mostrarToast((window.GUILDA_I18N && window.GUILDA_I18N.deshacerError) || "No se pudo deshacer la acción.", "error");
      }
    };
  }

  function mostrarToastPendienteSiHay() {
    var raw;
    try {
      raw = sessionStorage.getItem(CLAVE_TOAST_PENDIENTE);
      if (raw) sessionStorage.removeItem(CLAVE_TOAST_PENDIENTE);
    } catch (e) {
      return;
    }
    if (!raw) return;
    var datos;
    try {
      datos = JSON.parse(raw);
    } catch (e) {
      return;
    }
    mostrarToast(datos.mensaje, datos.tipo, {
      textoAccion: datos.accionUrl ? datos.textoAccion : undefined,
      accion: datos.accionUrl ? accionDeshacerDesdeUrl(datos.accionUrl) : undefined,
    });
  }

  // Wiring genérico para formularios de borrado que quieren un toast con
  // "Deshacer" en vez del comportamiento por defecto (recarga silenciosa
  // de página / navegación sin feedback). Marca el <form> con
  // data-eliminar-deshacer más:
  //   data-confirmar        (opcional) texto de confirm() antes de enviar
  //   data-mensaje-ok       texto del toast en éxito
  //   data-mensaje-error    texto del toast en fallo
  //   data-restaurar-url    URL POST del "Deshacer" (opcional)
  //   data-quitar-selector  selector ascendente (closest) a eliminar del
  //                         DOM en éxito, p.ej. "li" -- si se omite y hay
  //                         data-volver-a, navega allí en vez de quitar
  //                         un elemento
  //   data-volver-a         URL a la que navegar tras el borrado (p.ej.
  //                         páginas de edición de un único ítem, que no
  //                         tienen una fila que quitar)
  function inicializarFormulariosEliminarConDeshacer() {
    document.querySelectorAll("form[data-eliminar-deshacer]").forEach(function (form) {
      if (form.dataset.deshacerWired) return;
      form.dataset.deshacerWired = "1";
      form.addEventListener("submit", async function (e) {
        e.preventDefault();
        var confirmar = form.dataset.confirmar;
        if (confirmar && !window.confirm(confirmar)) return;

        var mensajeOk = form.dataset.mensajeOk || "";
        var mensajeError = form.dataset.mensajeError || mensajeOk;
        var restaurarUrl = form.dataset.restaurarUrl || "";
        var textoDeshacer = (window.GUILDA_I18N && window.GUILDA_I18N.deshacer) || "Deshacer";
        var volverA = form.dataset.volverA || "";
        var quitarSelector = form.dataset.quitarSelector || "";

        try {
          const resp = await fetch(form.action, { method: "POST" });
          if (!resp.ok) throw new Error("HTTP " + resp.status);

          if (volverA) {
            mostrarToastPendiente(mensajeOk, "exito", {
              textoAccion: restaurarUrl ? textoDeshacer : undefined,
              accionUrl: restaurarUrl || undefined,
            });
            window.location.href = volverA;
            return;
          }

          if (quitarSelector) {
            var elemento = form.closest(quitarSelector);
            if (elemento) elemento.remove();
          }
          mostrarToast(mensajeOk, "exito", restaurarUrl ? {
            textoAccion: textoDeshacer,
            accion: accionDeshacerDesdeUrl(restaurarUrl),
          } : undefined);
        } catch (err) {
          mostrarToast(mensajeError, "error");
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    mostrarToastPendienteSiHay();
    inicializarFormulariosEliminarConDeshacer();
  });
})();
