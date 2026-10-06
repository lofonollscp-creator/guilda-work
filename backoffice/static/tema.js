// Aplica el tema guardado antes de pintar (evita el parpadeo claro/oscuro).
(function () {
  try {
    var tema = localStorage.getItem("bo-tema");
    if (tema === "claro" || tema === "oscuro") document.documentElement.dataset.tema = tema;
    var lateral = localStorage.getItem("bo-lateral");
    if (lateral === "cerrado" || (lateral === null && window.innerWidth <= 900)) document.documentElement.dataset.lateral = "cerrado";
  } catch (e) { /* almacenamiento bloqueado: se usa el tema por defecto */ }
})();
