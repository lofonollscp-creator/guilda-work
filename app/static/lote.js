// Acciones sobre varias tareas marcadas: la barra se oculta mientras no haya ninguna y enseña solo el valor que pide la acción elegida.
// Sin JavaScript la barra está siempre visible y funciona igual (las casillas pertenecen al formulario por su atributo form).
(function () {
  "use strict";
  var barra = document.getElementById("lote-form");
  if (!barra) return;
  var script = document.currentScript || document.querySelector("script[src*='lote.js']");
  var t = (script && script.dataset) || {};
  var accion = document.getElementById("lote-accion");
  var contador = document.getElementById("lote-contador");
  var todas = document.getElementById("lote-todas");
  var casillas = function () { return Array.prototype.slice.call(document.querySelectorAll("input.lote-casilla")); };

  function valores() {
    barra.querySelectorAll("[data-valor-para]").forEach(function (c) { c.hidden = c.dataset.valorPara !== accion.value; c.disabled = c.hidden; });
  }
  function actualizar() {
    var marcadas = casillas().filter(function (c) { return c.checked; }).length;
    barra.classList.toggle("lote-oculta", marcadas === 0);
    contador.textContent = marcadas === 0 ? (t.tTodas || "") : (marcadas === 1 ? t.tMarcadasUno : (t.tMarcadas || "%s").replace("%s", marcadas));
    todas.checked = marcadas > 0 && marcadas === casillas().length;
  }
  accion.addEventListener("change", valores);
  todas.addEventListener("change", function () { casillas().forEach(function (c) { c.checked = todas.checked; }); actualizar(); });
  document.addEventListener("change", function (e) { if (e.target.classList && e.target.classList.contains("lote-casilla")) actualizar(); });
  valores();
  actualizar();
})();
