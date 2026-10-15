// Barra compacta del mensaje: arriba se ve la cabecera y la barra de acciones completas; al desplazar el mensaje más allá de ellas, queda pegada arriba una
// barra de una sola línea con las acciones principales. La barra compacta no ocupa sitio en el flujo, así que no hay saltos al aparecer o desaparecer.
(function () {
  const ancla = document.getElementById("correo-barra-compacta");
  const panel = document.querySelector(".correo-lectura-pane");
  const fija = document.querySelector(".correo-lectura-fija");
  if (!ancla || !panel || !fija) return;
  function actualizar() {
    const pasada = panel.scrollTop > fija.offsetTop + fija.offsetHeight - 8;
    ancla.dataset.visible = pasada ? "1" : "0";
  }
  panel.addEventListener("scroll", actualizar, { passive: true });
  window.addEventListener("scroll", actualizar, { passive: true });   // en móvil se desplaza la página, no el panel
  const subir = ancla.querySelector("[data-subir-al-inicio]");
  if (subir) subir.addEventListener("click", function () { panel.scrollTo({ top: 0, behavior: "smooth" }); window.scrollTo({ top: 0, behavior: "smooth" }); });
  actualizar();
})();
