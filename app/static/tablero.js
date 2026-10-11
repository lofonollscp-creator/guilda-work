// Tablero de tareas: arrastrar una tarjeta a otra columna cambia su estado. Mejora progresiva: el selector de cada tarjeta (con teclado y
// lectores de pantalla) sigue siendo la vía principal y funciona igual sin JavaScript; arrastrar solo rellena ese mismo selector y lo envía.
(function () {
  "use strict";
  const tablero = document.querySelector(".tareas-tablero");
  if (!tablero) return;
  let arrastrada = null;

  tablero.addEventListener("dragstart", (e) => {
    const tarjeta = e.target.closest && e.target.closest(".tareas-tarjeta[draggable]");
    if (!tarjeta) return;
    arrastrada = tarjeta;
    tarjeta.classList.add("es-arrastrada");
    tablero.classList.add("esta-arrastrando");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", tarjeta.dataset.tarea || "");
  });
  tablero.addEventListener("dragend", () => {
    if (arrastrada) arrastrada.classList.remove("es-arrastrada");
    arrastrada = null;
    tablero.classList.remove("esta-arrastrando");
    tablero.querySelectorAll(".es-destino").forEach((c) => c.classList.remove("es-destino"));
  });
  tablero.addEventListener("dragover", (e) => {
    const columna = e.target.closest && e.target.closest(".tareas-columna");
    if (!arrastrada || !columna) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    tablero.querySelectorAll(".es-destino").forEach((c) => { if (c !== columna) c.classList.remove("es-destino"); });
    columna.classList.add("es-destino");
  });
  tablero.addEventListener("drop", (e) => {
    const columna = e.target.closest && e.target.closest(".tareas-columna");
    if (!arrastrada || !columna) return;
    e.preventDefault();
    const destino = columna.dataset.estado;
    const formulario = arrastrada.querySelector(".tareas-tarjeta-mover");
    const selector = formulario && formulario.querySelector("select[name='estado']");
    if (selector && destino && selector.value !== destino && [...selector.options].some((o) => o.value === destino)) {
      selector.value = destino;
      columna.classList.remove("es-destino");
      formulario.requestSubmit ? formulario.requestSubmit() : formulario.submit();
    }
  });
})();
