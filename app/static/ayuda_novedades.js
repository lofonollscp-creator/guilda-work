/* Aviso «Novedades en la ayuda» del menú de ajustes: se enseña mientras la persona no haya abierto la última novedad.
   Lo recuerda este navegador (localStorage); si no está disponible, el aviso se ve siempre, sin romper nada. */
(function () {
  var enlace = document.getElementById("ayuda-novedad");
  if (!enlace) return;
  var CLAVE = "guilda.ayuda.novedad.vista";
  var id = enlace.dataset.novedad;
  var vista = null;
  try { vista = window.localStorage.getItem(CLAVE); } catch (e) { /* navegador sin almacenamiento */ }
  if (vista === id) return;
  enlace.hidden = false;
  enlace.addEventListener("click", function () {
    try { window.localStorage.setItem(CLAVE, id); } catch (e) { /* sin almacenamiento */ }
    enlace.hidden = true;
  });
})();
