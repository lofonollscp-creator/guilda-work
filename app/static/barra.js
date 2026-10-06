// Relojes en vivo de la barra superior (jornada y tarea en curso).
(function () {
  function tick() {
    document.querySelectorAll(".top-bar-vivo[data-inicio]").forEach(function (el) {
      var s = Math.max(0, Math.floor((new Date() - new Date(el.dataset.inicio)) / 1000) - parseInt(el.dataset.pausado || "0", 10));
      var p = function (n) { return String(n).padStart(2, "0"); };
      el.textContent = p(Math.floor(s / 3600)) + ":" + p(Math.floor((s % 3600) / 60)) + ":" + p(s % 60);
    });
  }
  tick();
  setInterval(tick, 1000);
  // Cierra el menú "Nuevo" al hacer clic fuera.
  document.addEventListener("click", function (e) {
    document.querySelectorAll(".top-bar-nuevo[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });
})();
