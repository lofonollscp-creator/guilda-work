// Relojes en vivo de la barra superior (jornada y tarea en curso).
(function () {
  function tick() {
    document.querySelectorAll(".top-bar-vivo[data-inicio]").forEach(function (el) {
      var s = Math.max(0, Math.floor((new Date() - new Date(el.dataset.inicio)) / 1000) - parseInt(el.dataset.pausado || "0", 10));
      var p = function (n) { return String(n).padStart(2, "0"); };
      el.textContent = p(Math.floor(s / 3600)) + ":" + p(Math.floor((s % 3600) / 60)) + ":" + p(s % 60);
    });
  }
  // Fecha y hora exactas en el huso horario del tenant.
  var reloj = document.querySelector(".top-bar-fecha[data-zona]");
  function relojTenant() {
    if (!reloj) return;
    var lang = document.documentElement.lang || "es";
    try {
      var ahora = new Date();
      var dia = new Intl.DateTimeFormat(lang, { timeZone: reloj.dataset.zona, weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(ahora);
      var hora = new Intl.DateTimeFormat(lang, { timeZone: reloj.dataset.zona, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(ahora);
      reloj.querySelector(".top-bar-fecha-dia").textContent = dia;
      reloj.querySelector(".top-bar-fecha-hora").textContent = hora;
    } catch (e) { /* huso desconocido para el navegador: se queda lo renderizado por el servidor */ }
  }
  relojTenant();
  setInterval(relojTenant, 1000);
  tick();
  setInterval(tick, 1000);
  // Cierra el menú "Nuevo" al hacer clic fuera.
  document.addEventListener("click", function (e) {
    document.querySelectorAll(".top-bar-nuevo[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });
})();
