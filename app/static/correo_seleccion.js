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

  barra.querySelectorAll("[data-accion]").forEach((boton) => {
    boton.addEventListener("click", async () => {
      const ids = idsSeleccionados();
      if (ids.length === 0) return;
      const accion = boton.dataset.accion;
      const cuerpo = { ids };
      let url = "";

      if (accion === "eliminar") {
        if (!confirm("¿Eliminar " + ids.length + " mensaje(s) de la caché local? No se puede deshacer.")) return;
        url = "/correo/mensajes/eliminar";
      } else if (accion === "marcar-leido") {
        cuerpo.leido = boton.dataset.valor === "true";
        url = "/correo/mensajes/marcar-leido";
      } else if (accion === "destacar") {
        cuerpo.destacado = boton.dataset.valor === "true";
        url = "/correo/mensajes/destacar";
      } else if (accion === "mover") {
        if (!selectCarpeta || !selectCarpeta.value) return;
        cuerpo.carpeta = selectCarpeta.value;
        url = "/correo/mensajes/mover";
      } else {
        return;
      }

      await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
      window.location.reload();
    });
  });
})();
