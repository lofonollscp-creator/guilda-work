// Selección por clic/arrastre en el calendario de Tareas: permite crear una
// tarea nueva sobre uno o varios días (o, en vista de día, sobre un rango de
// horas) sin pasar por el formulario de la lista.
(function () {
  const panel = document.getElementById("cal-quick-create");
  if (!panel) return;

  const campoInicio = document.getElementById("qc-fecha-inicio");
  const campoFin = document.getElementById("qc-fecha-vencimiento");
  const campoAsunto = document.getElementById("qc-asunto");
  const etiqueta = document.getElementById("qc-rango-label");

  const celdas = Array.from(document.querySelectorAll(".cal-seleccionable"));
  const valores = celdas.map((c) => c.dataset.fecha);

  let arrastrando = false;
  let celdaInicio = null;

  function limpiarSeleccion() {
    celdas.forEach((c) => c.classList.remove("is-seleccionada"));
  }

  function marcarRango(a, b) {
    const ia = valores.indexOf(a);
    const ib = valores.indexOf(b);
    if (ia === -1 || ib === -1) return;
    const desde = Math.min(ia, ib);
    const hasta = Math.max(ia, ib);
    limpiarSeleccion();
    celdas.forEach((c, i) => {
      if (i >= desde && i <= hasta) c.classList.add("is-seleccionada");
    });
  }

  function formatoLegible(valor) {
    const [fecha, hora] = valor.split("T");
    const [anio, mes, dia] = fecha.split("-");
    return hora ? `${dia}/${mes} a las ${hora}` : `${dia}/${mes}/${anio}`;
  }

  function abrirCreacionRapida(fechaA, fechaB) {
    const desde = fechaA <= fechaB ? fechaA : fechaB;
    const hasta = fechaA <= fechaB ? fechaB : fechaA;
    campoInicio.value = desde;
    campoFin.value = hasta;
    etiqueta.textContent = desde === hasta ? formatoLegible(desde) : `${formatoLegible(desde)} – ${formatoLegible(hasta)}`;
    panel.hidden = false;
    campoAsunto.value = "";
    campoAsunto.focus();
  }

  window.cerrarCreacionRapidaTarea = function () {
    panel.hidden = true;
    limpiarSeleccion();
  };

  celdas.forEach((celda) => {
    celda.addEventListener("mousedown", (e) => {
      if (e.target.closest(".cal-chip") || e.target.closest("a")) return;
      arrastrando = true;
      celdaInicio = celda.dataset.fecha;
      marcarRango(celdaInicio, celdaInicio);
      e.preventDefault();
    });
    celda.addEventListener("mouseenter", () => {
      if (arrastrando) marcarRango(celdaInicio, celda.dataset.fecha);
    });
    celda.addEventListener("mouseup", () => {
      if (!arrastrando) return;
      arrastrando = false;
      abrirCreacionRapida(celdaInicio, celda.dataset.fecha);
    });
  });

  document.addEventListener("mouseup", () => {
    if (arrastrando) {
      arrastrando = false;
      limpiarSeleccion();
    }
  });
})();
