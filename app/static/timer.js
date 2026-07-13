var UMBRAL_AVISO_SEGUNDOS = 4 * 3600; // 4 horas: a partir de aquí, avisar de que sigue activa

function actualizarTimers() {
  document.querySelectorAll(".task-timer[data-inicio]").forEach(function (el) {
    var inicio = new Date(el.dataset.inicio);
    var pausado = parseInt(el.dataset.pausado || "0", 10);
    var ahora = new Date();
    var segundos = Math.max(0, Math.floor((ahora - inicio) / 1000) - pausado);
    var h = String(Math.floor(segundos / 3600)).padStart(2, "0");
    var m = String(Math.floor((segundos % 3600) / 60)).padStart(2, "0");
    var s = String(segundos % 60).padStart(2, "0");
    el.textContent = h + ":" + m + ":" + s;

    var tarea = el.closest(".active-task");
    if (tarea) {
      tarea.classList.toggle("is-olvidada", segundos >= UMBRAL_AVISO_SEGUNDOS);
    }
  });
}
actualizarTimers();
setInterval(actualizarTimers, 1000);
