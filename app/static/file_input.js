// Componente único de "subir archivo" (ver .file-input en style.css) --
// muestra el nombre del archivo elegido (o "N archivos" si hay varios)
// junto al botón, en vez de dejar el estado "sin elegir ningún archivo"
// del control nativo. Texto "archivos" traducido vía window.GUILDA_I18N
// (fichero estático, no pasa por Jinja -- ver toasts.js).
document.querySelectorAll(".file-input input[type=file]").forEach(function (input) {
  var nombreEl = input.closest(".file-input").querySelector(".file-input-nombre");
  if (!nombreEl) return;
  var textoVacio = nombreEl.textContent;
  input.addEventListener("change", function () {
    if (!input.files || input.files.length === 0) {
      nombreEl.textContent = textoVacio;
    } else if (input.files.length === 1) {
      nombreEl.textContent = input.files[0].name;
    } else {
      var palabraArchivos = (window.GUILDA_I18N && window.GUILDA_I18N.archivos) || "archivos";
      nombreEl.textContent = input.files.length + " " + palabraArchivos;
    }
  });
});
