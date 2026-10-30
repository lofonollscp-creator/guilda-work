// Aplica el tema guardado antes de pintar (evita el parpadeo claro/oscuro). Sin nada guardado (o «sistema») no se fija el atributo:
// decide @media (prefers-color-scheme) en el CSS y el panel sigue al sistema operativo.
(function () {
  try {
    var tema = localStorage.getItem("bo-tema");
    if (tema === "claro" || tema === "oscuro") document.documentElement.dataset.tema = tema;
    document.documentElement.dataset.preferencia = (tema === "claro" || tema === "oscuro") ? tema : "sistema";
    var lateral = localStorage.getItem("bo-lateral");
    if (lateral === "cerrado" || (lateral === null && window.innerWidth <= 900)) document.documentElement.dataset.lateral = "cerrado";
  } catch (e) { /* almacenamiento bloqueado: se sigue al sistema */ }
})();
