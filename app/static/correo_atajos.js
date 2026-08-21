// Atajos de teclado tipo Gmail para triar correo, solo en /correo/ y con
// el foco fuera de un campo de texto (mismo guard que app/static/atajos.js,
// duplicado aquí a propósito -- son ficheros con audiencias distintas,
// ver comentario de ese fichero).
//   j / k   -- siguiente / anterior mensaje de la lista
//   # / Supr -- eliminar el mensaje abierto (caché local)
//   u        -- marcar el mensaje abierto como no leído
//   e        -- archivar (mover a la carpeta "Archivo"/"Archive" de la
//                cuenta, si existe -- no todas las cuentas IMAP la tienen)
(function () {
  const lista = document.getElementById("correo-lista-mensajes");
  if (!lista) return;

  function escribiendoEnCampo(e) {
    const el = e.target;
    if (!el) return false;
    const etiqueta = el.tagName;
    return etiqueta === "INPUT" || etiqueta === "TEXTAREA" || etiqueta === "SELECT" || el.isContentEditable;
  }

  function filaSeleccionada() {
    return lista.querySelector(".correo-fila-wrap.is-seleccionada");
  }

  function navegarA(fila) {
    if (!fila) return false;
    const enlace = fila.querySelector(".correo-fila-contenido");
    if (!enlace) return false;
    window.location.href = enlace.href;
    return true;
  }

  function volverALaLista() {
    const url = new URL(window.location.href);
    url.searchParams.delete("mensaje_id");
    window.location.href = url.toString();
  }

  async function accionEnLote(url, cuerpo) {
    const respuesta = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
    if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
  }

  document.addEventListener("keydown", async function (e) {
    if (e.ctrlKey || e.altKey || e.metaKey || escribiendoEnCampo(e)) return;
    const i18n = window.GUILDA_I18N || {};
    const actual = filaSeleccionada();

    if (e.key === "j") {
      e.preventDefault();
      navegarA((actual && actual.nextElementSibling) || lista.querySelector(".correo-fila-wrap"));
      return;
    }
    if (e.key === "k") {
      e.preventDefault();
      if (actual) navegarA(actual.previousElementSibling);
      return;
    }
    if (!actual) return; // el resto de atajos actúan sobre el mensaje abierto

    const casilla = actual.querySelector(".correo-fila-check");
    const id = casilla ? casilla.dataset.mensajeId : null;
    if (!id) return;
    const siguiente = actual.nextElementSibling || actual.previousElementSibling;

    if (e.key === "#" || e.key === "Delete") {
      e.preventDefault();
      try {
        await accionEnLote("/correo/mensajes/eliminar", { ids: [id] });
        if (window.mostrarToast) window.mostrarToast(i18n.correoEliminarOk || "Eliminado.", "exito");
        if (!navegarA(siguiente)) volverALaLista();
      } catch (err) {
        if (window.mostrarToast) window.mostrarToast(i18n.correoAccionError || "No se pudo completar la acción.", "error");
      }
    } else if (e.key === "u") {
      e.preventDefault();
      try {
        await accionEnLote("/correo/mensajes/marcar-leido", { ids: [id], leido: false });
        if (window.mostrarToast) window.mostrarToast(i18n.correoMarcarLeidoOk || "Actualizado.", "exito");
        volverALaLista();
      } catch (err) {
        if (window.mostrarToast) window.mostrarToast(i18n.correoAccionError || "No se pudo completar la acción.", "error");
      }
    } else if (e.key === "e") {
      e.preventDefault();
      const select = document.querySelector(".correo-ribbon-select");
      const opcionArchivo = select
        ? Array.from(select.options).find((o) => o.value && /archiv/i.test(o.textContent))
        : null;
      if (!opcionArchivo) {
        if (window.mostrarToast) window.mostrarToast(i18n.correoSinCarpetaArchivo || "Esta cuenta no tiene una carpeta de archivo.", "error");
        return;
      }
      try {
        await accionEnLote("/correo/mensajes/mover", { ids: [id], carpeta: opcionArchivo.value });
        if (window.mostrarToast) window.mostrarToast(i18n.correoMoverOk || "Movido.", "exito");
        if (!navegarA(siguiente)) volverALaLista();
      } catch (err) {
        if (window.mostrarToast) window.mostrarToast(i18n.correoAccionError || "No se pudo completar la acción.", "error");
      }
    }
  });
})();
