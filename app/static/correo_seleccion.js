// Selección múltiple de mensajes con checkboxes + barra de acciones en
// lote, al estilo Outlook. Sin SPA: cada acción hace un fetch a una ruta en
// lote de app/rutas_correo.py y recarga la página al terminar.
(function () {
  const lista = document.getElementById("correo-lista-mensajes");
  const barra = document.getElementById("correo-bulkbar");
  if (!lista || !barra) return;

  const contador = document.getElementById("correo-bulkbar-cuenta");
  const selectCarpeta = document.getElementById("correo-bulkbar-carpeta");

  function idsSeleccionados() {
    return Array.from(lista.querySelectorAll(".correo-fila-check:checked")).map((c) => c.dataset.mensajeId);
  }

  function actualizarBarra() {
    const ids = idsSeleccionados();
    if (ids.length === 0) {
      barra.hidden = true;
      return;
    }
    barra.hidden = false;
    contador.textContent = ids.length + (ids.length === 1 ? " seleccionado" : " seleccionados");
  }

  lista.querySelectorAll(".correo-fila-check").forEach((casilla) => {
    casilla.addEventListener("click", (e) => e.stopPropagation());
    casilla.addEventListener("change", actualizarBarra);
  });

  document.getElementById("correo-bulkbar-cancelar").addEventListener("click", () => {
    lista.querySelectorAll(".correo-fila-check:checked").forEach((c) => (c.checked = false));
    actualizarBarra();
  });

  // Doble clic en un mensaje: entra en "modo pantalla completa" (oculta
  // el rail de cuentas y la lista, ver .correo-shell.es-pantalla-completa
  // en style.css) -- pedido explícitamente porque las columnas fijas de
  // 220px+340px dejan poco sitio para leer. Un solo clic sigue
  // navegando tal cual (recarga con ?mensaje_id=), así que no hace
  // falta prevenir el primer clic: en el SEGUNDO clic de un doble clic,
  // `e.detail` vale 2 (lo reporta el propio navegador, sin temporizador
  // a mano) -- ahí se cancela la navegación normal y se repite con
  // &completa=1 añadido.
  lista.querySelectorAll(".correo-fila-contenido").forEach((enlace) => {
    enlace.addEventListener("click", (e) => {
      if (e.detail < 2) return;
      e.preventDefault();
      const url = new URL(enlace.href, window.location.origin);
      url.searchParams.set("completa", "1");
      window.location.href = url.toString();
    });
  });

  const i18n = window.GUILDA_I18N || {};

  barra.querySelectorAll("[data-accion]").forEach((boton) => {
    boton.addEventListener("click", async () => {
      const ids = idsSeleccionados();
      if (ids.length === 0) return;
      const accion = boton.dataset.accion;
      const cuerpo = { ids };
      let url = "";
      let mensajeOk;

      if (accion === "eliminar") {
        if (!confirm("¿Eliminar " + ids.length + " mensaje(s) de la caché local? No se puede deshacer.")) return;
        url = "/correo/mensajes/eliminar";
        mensajeOk = i18n.correoEliminarOk;
      } else if (accion === "marcar-leido") {
        cuerpo.leido = boton.dataset.valor === "true";
        url = "/correo/mensajes/marcar-leido";
        mensajeOk = i18n.correoMarcarLeidoOk;
      } else if (accion === "destacar") {
        cuerpo.destacado = boton.dataset.valor === "true";
        url = "/correo/mensajes/destacar";
        mensajeOk = i18n.correoDestacarOk;
      } else if (accion === "mover") {
        if (!selectCarpeta || !selectCarpeta.value) return;
        cuerpo.carpeta = selectCarpeta.value;
        url = "/correo/mensajes/mover";
        mensajeOk = i18n.correoMoverOk;
      } else {
        return;
      }

      try {
        const respuesta = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cuerpo),
        });
        if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
        if (window.mostrarToast && mensajeOk) window.mostrarToast(mensajeOk, "exito");
        window.location.reload();
      } catch (err) {
        if (window.mostrarToast) {
          window.mostrarToast(i18n.correoAccionError || "No se pudo completar la acción.", "error");
        }
      }
    });
  });
})();
